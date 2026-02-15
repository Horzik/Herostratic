import asyncio
import base64
import json
import logging
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import timedelta, datetime, timezone
from io import BytesIO
from typing import TypedDict

from config import (POLICE_ARTICLES_FP, LOG_DIR, ERRORS_LOG_FP, POLICE_RESULTS_FP,
                    PIG_RANKS, DATE_REGEX, ALL_KEYWORDS, FAILED_POLICE_RESULTS_FP,
                    FILES_DIR, ALL_DISTRICTS_FP, ALL_MUNIS_FP)
from scraper.core import BaseScraper
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL
from utils.get_file_type import detect_file_category
from utils.io_utils import async_json_read, atomic_json_write, async_text_read
from utils.logger import LogConfig, destroy
from utils.parsing_utils import parse_czech_date


class PoliceArticleResult(TypedDict):
    source: str
    archive_category: str  # Can be either a year or district/city
    url: str
    title: str
    year: int | None
    date: str | None
    region: str | None
    district: str | None
    municipality: str | None
    author: str | None
    description: str
    content: str
    files: list[tuple[str, str]] | None # (file_path, file_type)
    keywords: list[str]
    scraped_at: str
    html_base64: str

@dataclass
class ScrapingStats:
    saved_articles: int = 0
    failed_articles: int = 0
    articles_processed: int = 0
    missing_date: int = 0
    missing_author: int = 0
    with_files: int = 0

type Region = str
type ArchCategory = str
type ResBuffer = list[tuple[Region, ArchCategory, PoliceArticleResult]]

type FileLink = str
type FileName = str
type FileMetadata = tuple[FileLink, FileName]

class PoliceArticlesScraper(BaseScraper):
    MODULE_NAME = 'scrape_police_articles'
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_ARTICLES_FP
    OUTPUT_FILE = POLICE_RESULTS_FP
    FAILED_FILE = FAILED_POLICE_RESULTS_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 10
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'scrape_police_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        self.stats = ScrapingStats()
        self.cached_results: dict = {}
        self.results_buffer: ResBuffer = []
        self.results_buffer_threshold = 50
        self.queue_size = 0
        # Cache for text search
        self.district_lookup = {}
        self.muni_lookup = {}
        self.muni_pattern: re.Pattern | None = None
        self.district_pattern: re.Pattern | None = None


    @staticmethod
    def get_date(content_ref) -> str | None:
        """Returns the date as iso string."""
        date_text = None
        for p in content_ref:
            text = p.get_text()
            match = re.search(DATE_REGEX, text)
            if match:
                raw_date = match.group(0).strip()
                parsed_date = parse_czech_date(raw_date)
                date_text = parsed_date.isoformat()

        return date_text


    @staticmethod
    def get_author(content_ref):
        """Returns the police officers author by parsing for police ranks."""
        author_text = None
        for p in content_ref:
            text = p.get_text()
            for line in text.split('\n'):
                for rank in PIG_RANKS:
                    if rank in line:
                        author_text = (rank + line.split(rank, 1)[1]).strip()

        return author_text


    @staticmethod
    def get_year(arch_cat, date_text):
        """Category might be a year, if not try parsing the date_text."""
        try:
            year = int(arch_cat.strip())
        except ValueError:
            year = None

        if date_text and not year:
            year = int(date_text[:4])
        return year


    def get_archive_category(self, arch_cat, date_text, soup, url, region):
        """Get a clear archive category"""
        if arch_cat == "non_years" and date_text is not None:
            arch_cat = str(date_text[:4])

        elif arch_cat == "non_years" and date_text is None:
            drobek_ref = soup.select_one(POLICE_SELECTOR['article_selectors']['drobek'])
            if drobek_ref:
                drobek_text = drobek_ref.get_text()
                arch_cat = drobek_text[-4:]
            else:
                self.logger.error(f"No drobek found for '{url}', '{region}'::'{arch_cat}....'")

        return arch_cat


    # todo municipalities are often NOT in "nominative" (which the patterns expect), we could feed them all here and get ALL options LUL "https://prirucka.ujc.cas.cz/"
    def get_location(self, title, description, content_text) -> tuple[str | None, str | None]:
        """Used the patterns (which are created on load) to find any matching districts or municipalities."""
        full_text = f"{title}\n{description}\n{content_text}".lower()
        district_match = self.district_pattern.search(full_text)
        muni_match = self.muni_pattern.search(full_text)

        return (
            self.district_lookup[district_match.group()] if district_match else None,
            self.muni_lookup[muni_match.group()] if muni_match else None,
        )


    @staticmethod
    def get_content_text(content_ref, non_text_elements):
        """Parse the article for the content text."""
        content_text = ''
        for tag in content_ref:
            if tag in non_text_elements:
                continue
            tag_text = tag.get_text().strip()
            if len(tag_text) > 10:
                content_text += tag_text + '\n'
        return content_text


    @staticmethod
    def get_non_text_elements(title_ref, description_ref, imgs_ref, docs_ref) -> set:
        """These elements are used to parse the actual 'content_text'."""
        non_text_elements = set()
        if title_ref:
            non_text_elements.update(title_ref[0])
        if description_ref:
            non_text_elements.update(description_ref[0])
        if imgs_ref:
            non_text_elements.update(imgs_ref)
        if docs_ref:
            non_text_elements.update(docs_ref)
        return non_text_elements


    def get_elements(self, soup: BeautifulSoup, url: str, region: str, arch_cat: str):
        """Selects various elements and returns them in a tuple."""
        title_ref = soup.select('div#content > h1')
        description_ref = soup.select('div#content > p:first-of-type')
        content_ref = soup.select('div#content')
        imgs_ref = soup.select('div#content > div.graybox > div')
        docs_ref = soup.select('div.related')
        p_tags = soup.select('div#content p')

        # All articles need to have these elements
        required = {
            'title': title_ref,
            'description': description_ref,
            'content': content_ref
        }
        for name, element in required.items():
            if not element:
                self.logger.error(f"Missing '{name}' from '{url}', '{region}'/'{arch_cat}'")
                return None
        return p_tags, title_ref, description_ref, content_ref, imgs_ref, docs_ref



    @staticmethod
    def write_failed_article(res_url):
        # todo not the most optimal way of writing (writes one by one)
        with open(FAILED_POLICE_RESULTS_FP, 'a') as f:
            f.write(res_url + '\n')


    def validate_result(self, result, region, arch_cat, url) -> bool:
        if isinstance(result, Exception):
            self.logger.error(
                f"Error scraping police article: '{region}'/'{arch_cat}', url: '{url}' failed with exception: {result}")
            self.stats.failed_articles += 1
            self.write_failed_article(url)
            return False
        if not isinstance(result, dict):
            self.logger.error(f"Error: result not a dict. Region '{region}'/'{arch_cat}', url: '{url}'...")
            self.stats.failed_articles += 1
            self.write_failed_article(url)
            return False
        return True


    def process_single_result(self, job_data, result):
        self.stats.articles_processed += 1
        region, arch_cat, url = job_data

        if not self.validate_result(result, region, arch_cat, url):
            return

        if not result['date']:
            self.stats.missing_date += 1
        if not result['author']:
            self.stats.missing_author += 1
        if result['files']:
            self.stats.with_files += 1
        self.stats.saved_articles += 1


    @staticmethod
    def find_youtube_links(soup) -> list[str] | None:
        """Goes through the whole soup and looks for youtube links, returns them in a list."""
        text = str(soup)
        # Any normal ytb links AND the iframe ('youtube-nocookie')
        pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube-nocookie\.com/embed/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})'
        matches = re.findall(pattern, text)
        if matches:
            return [f'https://www.youtube.com/watch?v={vid}' for vid in set(matches)]  # Deduplicate, return full URLs
        else:
            return None


    async def download_ytb_video(self, ytb_url, url_path) -> tuple[str, str] | None:
        """Use the 'yt_dlp' lib to download youtube links.
           Returns a tuple of (file_path, file_type).
        """
        import yt_dlp

        abs_dir = FILES_DIR / url_path
        opts = {
            'outtmpl': str(abs_dir / '%(title)s.%(ext)s'),
            'format': 'best[height<=720]',
            'quiet': True,
        }
        try:
            # Wrap the download to be non-blocking
            def _download():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    dl_info = ydl.extract_info(ytb_url, download=True)
                    return ydl.prepare_filename(dl_info)

            file_name = await asyncio.to_thread(_download)
            rel_path = url_path + '/' + Path(file_name).name
            return str(rel_path), 'video'

        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f"Error downloading a youtube video from: {url_path}...")
            self.logger.error(e)
            return None


    async def download_file(self, file_link, file_name, dir_name) -> tuple[str, str] | None:
        """Saves target :param{url_path} bytes as :param{file_name} at :param{url_path}."""
        abs_file_path = FILES_DIR / dir_name / file_name # Where to write the file
        rel_file_path = dir_name + '/' + file_name # Stored in PG

        file_bytes = BytesIO(await self.fetch(file_link))
        file_type = detect_file_category(bytes(file_bytes.getbuffer()[:32])) # Reads the magic bytes and determines the type
        try:
            with open(abs_file_path, 'wb') as f:
                f.write(file_bytes.getbuffer())
            return str(rel_file_path), file_type

        except Exception as e:
            self.logger.error(f"Error downloading file from {dir_name}...")
            self.logger.error(e)
            return None


    async def get_gallery_links(self, imgs_ref) -> set[FileMetadata]:
        """Police gallery parser which returns links to the images inside."""
        links_set: set[FileMetadata] = set()

        def _add_gallery_img(soup, _links_set, count):
            img_name = soup.select_one('div#image > img').get('alt')
            img_href = soup.select_one('div#image > img').get('src')
            img_link = self.BASE_URL + "/" + img_href
            _links_set.add((img_link, img_name + f"_{count}"))

        # First get the gallery link (any image link goes to the gallery, select the first one)
        gallery_link_el = imgs_ref.select_one('p.galThumb a')
        if not  gallery_link_el:
            return links_set

        gallery_link = gallery_link_el.get('href')
        if gallery_link and gallery_link.startswith('//'):
            gallery_link = 'https:' + gallery_link

        # Go to the gallery and add the first image
        gallery_soup = await self.get_soup(gallery_link)
        img_count = 1
        _add_gallery_img(gallery_soup, links_set, img_count)

        # Then go over all other imgs and get their links
        next_img_pager = gallery_soup.select_one('div#galerie > p.fotopager > a.nextfoto')
        while next_img_pager:
            img_count += 1
            next_gallery_link = self.BASE_URL + '/' + next_img_pager.get('href')
            next_image_soup = await self.get_soup(next_gallery_link)
            _add_gallery_img(next_image_soup, links_set, img_count)
            next_img_pager = next_image_soup.select_one('div#galerie > p.fotopager > a.nextfoto')

        return links_set


    def get_docs_links(self, docs_ref) -> set[FileMetadata]:
        doc_files: set[FileMetadata] = set()

        # Docs are in a list directly on the page
        docs_list = docs_ref.select('ul > li')
        for li in docs_list:
            file_name = li.select_one('a').get_text(strip=True)
            file_link = self.BASE_URL + li.select_one('a').get('href')
            doc_files.add((file_link, file_name))

        return doc_files


    async def get_files(self, imgs_ref, docs_ref, soup, url) -> list[tuple[str, str]] | list:
        """Download the embedded files (pictures/videos).
           Returns a list of tuple(file_path, file_type) on success and empty list on fail.
        """

        files_results: list[tuple[str, str]] = []
        dir_name = re.search(r'/([^/]+)\.[^.]+$', url).group(1).strip()

        ytb_urls = self.find_youtube_links(soup)
        if ytb_urls:
            files = files_results or []
            for ytb_url in ytb_urls:
                files.append(await self.download_ytb_video(ytb_url, dir_name))

        gallery_links = None
        docs_links = None
        try:
            if imgs_ref is not None:
                # self.logger.debug(f"Imgs_ref:: {imgs_ref}")
                gallery_links = await self.get_gallery_links(imgs_ref[0]) if imgs_ref else set()
            if docs_ref is not None:
                docs_links = self.get_docs_links(docs_ref[0]) if docs_ref else set()

            if gallery_links | docs_links:
                # Make the target dir if needed
                file_dir_abs_path = FILES_DIR / dir_name
                if not file_dir_abs_path.is_dir():
                    file_dir_abs_path.mkdir(parents=True, exist_ok=True)

                for file_link, file_name in gallery_links | docs_links:
                    file_name = file_name.replace('/', '_').replace('\\', '_')
                    file_path, file_type = await self.download_file(file_link, file_name, dir_name)
                    files_results.append((file_path, file_type))

        except Exception as e:
            self.logger.error(f"Error while getting files from {url}...", exc_info=True)
            self.logger.error(e)
            return list()

        return files_results


    async def flush_buffer(self):
        """Writes to the in-memory "all_results" first. Then it saves the batched articles."""
        async with self.lock:
            for region, arch_cat, content in self.results_buffer:
                self.cached_results.setdefault(region, {}).setdefault(arch_cat, []).append(content)

            # Write results back and clean the buffer
            atomic_json_write(self.cached_results, self.OUTPUT_FILE)
            self.results_buffer = []
        return


    async def fetch_page(self, url: str, region: str, arch_cat: str) -> tuple | None:
        """Helper to get both the soup and elements. Checks if the soup isn't actually just 404."""
        soup = await self.get_soup(url)
        if soup is None:
            raise ValueError(f"Failed getting soup for '{url}' from '{region}'::'{arch_cat}")

        elements = self.get_elements(soup, url, region, arch_cat)
        if elements is None:
            raise ValueError(f"Failed parsing elements for '{url}' from '{region}'::'{arch_cat}")

        return soup, elements


    async def parse_html(self, url: str, region: str, arch_cat: str) -> PoliceArticleResult | None:
        soup, elements = await self.fetch_page(url, region, arch_cat)
        p_tags, title_ref, description_ref, content_ref, imgs_ref, docs_ref = elements

        title_text = title_ref[0].get_text()
        description_text = description_ref[0].get_text().strip()
        date_text = self.get_date(content_ref)
        author_text = self.get_author(content_ref)
        arch_cat = self.get_archive_category(arch_cat, date_text, soup, url, region)
        page_bytes = await self.fetch(url)  # For 'html_base64'

        year = self.get_year(arch_cat, date_text)

        # To get content_text, first define elements without the text
        non_text_elements = self.get_non_text_elements(title_ref, description_ref, imgs_ref, docs_ref)
        # Then add the text from all the other elements
        content_text = self.get_content_text(content_ref, non_text_elements)

        # Try parsing a location of the article
        district, municipality = self.get_location(title_text, description_text, content_text)

        # Get keywords based on url AND the content
        keywords = {
            key for key in ALL_KEYWORDS
                if (key in url.lower()
                    or key in content_text.lower()
                    or key in description_text.lower())
        }

        files = await self.get_files(imgs_ref, docs_ref, soup, url)

        article_result: PoliceArticleResult = {
            'source': f'policie_{region.replace(' ', '_').lower()}',
            'archive_category': arch_cat,
            'url': url,
            'title': title_text,
            'year': year,
            'date': date_text,
            'region': region,
            'district': district,
            'municipality': municipality,
            'author': author_text,
            'description': description_text,
            'content': content_text,
            'files': files,
            'keywords': sorted(keywords),
            'scraped_at': datetime.now(timezone.utc).isoformat(),
            "html_base64": base64.b64encode(page_bytes).decode("ascii"),
        }
        return article_result


    async def scrape_article(self, url: str, region: str, arch_cat: str):
        """The main scraping method."""
        article_result = await self.parse_html(url, region, arch_cat)
        if not article_result:
            self.logger.error(f"Exiting scrape coro of article url '{url}'...")
            return None

        return article_result


    async def get_scraped_urls(self) -> set[str]:
        """Reads the "police_results" and returns a set of only the URLs.
           Used for deduping results, ie to not re-add a result which we already have.
        """
        initial_results_urls = set()
        results_dict = await async_json_read(self.OUTPUT_FILE)
        for region, arch_categories in results_dict.items():
            for category, articles in arch_categories.items():
                for article in articles:
                    initial_results_urls.add(article['url'])

        self.cached_results = results_dict # Assign the class attribute with all existing results
        self.logger.info(f"Initial results urls: {len(initial_results_urls)}")
        return initial_results_urls


    async def load_czech_locations(self):
        muni_map = json.loads(await async_text_read(ALL_MUNIS_FP))
        district_map = json.loads(await async_text_read(ALL_DISTRICTS_FP))

        self.muni_lookup = {form.lower(): nominative for form, nominative in muni_map.items()}
        self.district_lookup = {form.lower(): nominative for form, nominative in district_map.items()}

        muni_set = sorted(self.muni_lookup.keys(), key=len, reverse=True)
        district_set = sorted(self.district_lookup.keys(), key=len, reverse=True)

        # The linter warning are wrong here
        self.muni_pattern = re.compile(
            r'\b(?:' + '|'.join(re.escape(m) for m in muni_set) + r')\b' #noqa
        )
        self.district_pattern = re.compile(
            r'\b(?:' + '|'.join(re.escape(d) for d in district_set) + r')\b' #noqa
        )


    async def mk_work_items(self):
        """Loop that pushes items (tuples of input from file) into a queue."""
        articles_links = await async_json_read(self.INPUT_FILE)
        scraped_articles = await self.get_scraped_urls()

        seen = set() # Safety dedupe
        work_items = []
        for region, arch_categories in articles_links.items():
            for arch_cat, urls_list in arch_categories.items():
                for url in urls_list:
                    if url not in scraped_articles and url not in seen:
                        seen.add(url)
                        work_items.append((region, arch_cat, url))
        return work_items


    async def scraper(self):
            timer_start = time.time()
            await self.load_czech_locations()

            async def worker(scrape_queue: asyncio.Queue):
                """Listens for input from queue. Manages the buffer writes. """
                while True:
                    region, archive_category, url = await scrape_queue.get()
                    try:
                        result = await self.scrape_article(url, region, archive_category)
                        self.process_single_result((region, archive_category, url), result)

                        # Append the result to the buffer
                        self.results_buffer.append((region, archive_category, result))

                        # If the buffer is large enough ==> write it
                        if len(self.results_buffer) > self.results_buffer_threshold:
                            self.logger.info(f"Writing from a buffer...")
                            await self.flush_buffer()

                    except Exception:
                        self.logger.error(f"Error while scraping '{url}' from '{region}':", exc_info=True)
                    finally:
                        self.logger.info(f"Finished scraping task {self.stats.articles_processed} / {self.queue_size} :: '{url}' from '{region}':")
                        scrape_queue.task_done()

            queue = asyncio.Queue()
            workers = [asyncio.create_task(worker(queue)) for _ in range(20)]
            work_items = await self.mk_work_items()
            self.queue_size = len(work_items)

            for item in work_items:
                await queue.put(item)
            await queue.join()

            # Quit the workers and write any remaining results
            for w in workers:
                w.cancel()
            if len(self.results_buffer) > 0:
                await self.flush_buffer()

            timer_end = time.time()
            formatted_time = str(timedelta(seconds=timer_end - timer_start))
            self.logger.info(f"Finished scraping in {formatted_time}")
            self.logger.info(f"Processed {self.stats.articles_processed} articles, saved {self.stats.saved_articles}.")
            self.logger.info(f"{self.stats.failed_articles} articles failed.")
            self.logger.info(f"{self.stats.missing_date} articles missing date, {self.stats.missing_author} missing author.")
            self.logger.info(f"{self.stats.with_files} articles have documents.")
            self.logger.info(f"Exiting...")


async def scrape_police_articles():
    async with PoliceArticlesScraper() as ps:
        try:
            await ps.scraper()

        finally:
            destroy()


if __name__ == "__main__":
    asyncio.run(scrape_police_articles(), debug=True)