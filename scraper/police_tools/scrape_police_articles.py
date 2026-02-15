import asyncio
import base64
import json
import logging
import re
import time

from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import timedelta, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import TypedDict

from config import (POLICE_ARTICLES_FP, LOG_DIR, ERRORS_LOG_FP, POLICE_RESULTS_FP,
                    PIG_RANKS, DATE_REGEX, ALL_KEYWORDS, FAILED_POLICE_RESULTS_FP,
                    FILES_DIR, ALL_DISTRICTS_FP, ALL_MUNIS_FP)
from scraper.core import BaseScraper
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL
from utils.get_file_type import detect_file_category
from utils.io_utils import async_json_read, atomic_json_write, async_text_read
from utils.logger import LogConfig, destroy
from utils.network_utils import FetchError
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
    files: list[tuple[str, str]] # (file_path, file_type)
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

type FileUrl = str
type FileName = str
type FileMetadata = tuple[FileUrl, FileName]

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
    def write_failed_article(res_url):
        # todo store in cache then write on exit. Store as set (dedupe)
        with open(FAILED_POLICE_RESULTS_FP, 'a') as f:
            f.write(res_url + '\n')


    def log_report(self, elapsed_time):
        self.logger.info(f"Finished scraping in {elapsed_time} seconds.")
        self.logger.info(f"Processed {self.stats.articles_processed} articles, saved {self.stats.saved_articles}.")
        self.logger.info(f"{self.stats.failed_articles} articles failed.")
        self.logger.info(f"{self.stats.missing_date} articles missing date, {self.stats.missing_author} missing author.")
        self.logger.info(f"{self.stats.with_files} articles have documents.")
        self.logger.info(f"Exiting...")


    @staticmethod
    def parse_date(content_el) -> str | None:
        """Returns the date as iso string."""
        date_text = None
        for p in content_el:
            text = p.get_text()
            match = re.search(DATE_REGEX, text)
            if match:
                raw_date = match.group(0).strip()
                date_text = parse_czech_date(raw_date)

        return date_text


    @staticmethod
    def parse_author(content_el):
        """Returns the police officers author by parsing for police ranks."""
        author_text = None
        for p in content_el:
            text = p.get_text()
            for line in text.split('\n'):
                for rank in PIG_RANKS:
                    if rank in line:
                        author_text = (rank + line.split(rank, 1)[1]).strip()
        return author_text


    @staticmethod
    def resolve_year(arch_cat, date_text):
        """Category might be a year, if not try parsing the date_text."""
        try:
            year = int(arch_cat.strip())
        except ValueError:
            year = None

        if date_text and not year:
            year = int(date_text[:4])
        return year


    def resolve_archive_category(self, arch_cat, date_text, soup, url, region):
        """Fed 'arch_cat' can be many things. Get a clear archive category.
        """
        if arch_cat == "non_years" and date_text is not None:
            arch_cat = str(date_text[:4])
        elif arch_cat == "non_years" and date_text is None:
            drobek_el = soup.select_one(POLICE_SELECTOR['article_selectors']['drobek'])
            if drobek_el:
                drobek_text = drobek_el.get_text()
                arch_cat = drobek_text[-4:]
            else:
                self.logger.error(f"No drobek found for '{url}', '{region}'::'{arch_cat}....'")
        return arch_cat


    def match_location(self, title, description, content_text) -> tuple[str | None, str | None]:
        """First use the pattern to find and matches in a text. Then use the lookups to find the nominative.
        """
        full_text = f"{title}\n{description}\n{content_text}".lower()
        district_match = self.district_pattern.search(full_text)
        muni_match = self.muni_pattern.search(full_text)

        return (
            self.district_lookup[district_match.group()] if district_match else None,
            self.muni_lookup[muni_match.group()] if muni_match else None,
        )


    @staticmethod
    def extract_content_text(content_el, non_text_els):
        """Parse the article for the content text."""
        content_text = ''
        for tag in content_el:
            if tag in non_text_els:
                continue

            tag_text = tag.get_text().strip()
            if len(tag_text) > 10: # Skip non-interesting text elements
                content_text += tag_text + '\n'

        return content_text


    @staticmethod
    def collect_non_text_els(title_el, description_el, imgs_el, docs_el) -> set:
        """Elements to be excluded when parsing the 'content_text'."""
        non_text_els = set()
        if title_el:
            non_text_els.update(title_el[0])
        if description_el:
            non_text_els.update(description_el[0])
        if imgs_el:
            non_text_els.update(imgs_el)
        if docs_el:
            non_text_els.update(docs_el)
        return non_text_els


    def select_element_lists(self, soup: BeautifulSoup, url: str, region: str, arch_cat: str):
        """Returns various tag lists."""
        title_el = soup.select('div#content > h1')
        description_el = soup.select('div#content > p:first-of-type')
        content_el = soup.select('div#content')
        imgs_el = soup.select('div#content > div.graybox > div')
        docs_el = soup.select('div.related')
        sound_el = soup.select('span.audio-text')

        # All articles need to have these elements
        required = {
            'title': title_el,
            'description': description_el,
            'content': content_el
        }
        for name, element in required.items():
            if not element:
                self.logger.error(f"Missing '{name}' from '{url}', '{region}'/'{arch_cat}'")
                return None
        return title_el, description_el, content_el, imgs_el, docs_el, sound_el


    def process_single_result(self, result):
        if not result['date']:
            self.stats.missing_date += 1
        if not result['author']:
            self.stats.missing_author += 1
        if result['files']:
            self.stats.with_files += 1

        self.stats.saved_articles += 1


    @staticmethod
    def find_youtube_links(soup) -> list[str] | None:
        """Goes through the whole soup and looks for 'youtube' links, returns them in a list."""
        text = str(soup)

        # Pattern to get the url path for any direct link or inside the iframe ('youtube-nocookie')
        pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube-nocookie\.com/embed/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})'
        matches = re.findall(pattern, text)
        if matches:
            return [f'https://www.youtube.com/watch?v={vid}' for vid in set(matches)]  # Deduplicate, return full URLs
        else:
            return None


    async def download_ytb_video(self, ytb_url, url_path) -> tuple[str, str] | None:
        """Use the 'yt_dlp' lib to download 'youtube' links.
           Returns a tuple of (file_path, file_type).
        """
        import yt_dlp
        abs_dir: Path = FILES_DIR / url_path
        opts = {
            'outtmpl': str(abs_dir / '%(title)s.%(ext)s'),
            'format': 'best[height<=720]',
            'quiet': True,
        }
        try:
            # Downloads and returns the video title (used as the file name), wrapped to be non-blocking
            def _download():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    dl_info = ydl.extract_info(ytb_url, download=True)
                    return ydl.prepare_filename(dl_info)

            file_name = await asyncio.to_thread(_download)
            rel_path = str(url_path + '/' + Path(file_name).name)
            return str(rel_path), 'video'

        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f"Error downloading a youtube video from: {url_path}...")
            self.logger.error(e)
            return None


    # todo make as a util
    async def download_file(self, file_url, file_name, dir_name) -> tuple[str, str] | None:
        """Saves target {file_url} bytes as {file_name} at {dir_name}.
        """
        abs_file_path = FILES_DIR / dir_name / file_name # Where to write the file
        rel_file_path = dir_name + '/' + file_name # Stored in PG

        file_bytes = BytesIO(await self.fetch(file_url))
        file_type = detect_file_category(bytes(file_bytes.getbuffer()[:32])) # Reads the magic bytes and determines the type
        try:
            with open(abs_file_path, 'wb') as f:
                f.write(file_bytes.getbuffer())
            return str(rel_file_path), file_type

        except Exception as e:
            self.logger.error(f"Error downloading file from {dir_name}...")
            self.logger.error(e)
            raise


    async def parse_gallery_links(self, imgs_el) -> set[FileMetadata]:
        """Police gallery parser which returns links to the images inside."""
        links_set: set[FileMetadata] = set()

        def _add_gallery_img(soup, _links_set, count):
            """Directly mutates the _links_set."""
            img_el = soup.select_one('div#image > img')
            if not img_el:
                raise ValueError(f"Failed selecting gallery link 'img_el")
            img_name = img_el.get('alt')
            if not img_name:
                raise ValueError(f"Failed selecting gallery link 'img_name")
            img_href = img_el.get('src')
            if not img_href:
                raise ValueError(f"Failed selecting gallery link 'img_href")

            img_link = self.BASE_URL + "/" + img_href
            _links_set.add((img_link, img_name + f"_{count}"))

        # First get the gallery link (any image link goes to the gallery, select the first one)
        gallery_link_el = imgs_el.select_one('p.galThumb a')
        if not gallery_link_el:
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


    def parse_docs_links(self, docs_el, sound_el=None) -> set[FileMetadata]:
        doc_files: set[FileMetadata] = set()

        # Regular doc files are in a list directly on the page.
        docs_list = docs_el.select('ul > li')
        if docs_list is not None:
            for li in docs_list:
                doc_li_el = li.select_one('a')
                if doc_li_el:
                    file_name = doc_li_el.get_text(strip=True)
                    file_url = self.BASE_URL + li.select_one('a').get('href')
                    doc_files.add((file_url, file_name))

        # Sound have their own element.
        if sound_el is not None:
            sound_file_path = sound_el.get('data-file')
            if sound_file_path:
                sound_file_url = self.BASE_URL + "/" + sound_file_path
                self.logger.debug(f"Sound file url:: {sound_file_url}")
                sound_file_name = sound_file_path.rsplit('.')[0].rsplit('/')[1]  # The path we get looks like "soubor/vandal-2109-mp3.aspx" ==> get just the unique string in the middle
                self.logger.debug(f"Sound file name:: {sound_file_name}")
                doc_files.add((sound_file_url, sound_file_name))

        return doc_files


    async def download_files(self, imgs_el, docs_el, sound_el, soup, url) -> list[tuple[str, str]]:
        """Downloads the article embedded files (pictures/videos/sounds).
           Returns a list of tuple(file_path, file_type).
        """
        files_results: list[tuple[str, str]] = []
        dir_name = re.search(r'/([^/]+)\.[^.]+$', url).group(1).strip()

        # First get any 'youtube' links.
        ytb_urls = self.find_youtube_links(soup)
        if ytb_urls:
            for ytb_url in ytb_urls:
                dl_res = await self.download_ytb_video(ytb_url, dir_name)
                if dl_res:
                    files_results.append(dl_res)

        # Then get 'policie.cz' specific files.
        gallery_links = set()
        docs_links = set()
        if imgs_el:
            gallery_links = await self.parse_gallery_links(imgs_el[0])
        if docs_el:
            docs_links = self.parse_docs_links(docs_el[0], sound_el[0] if sound_el else None)

        # Download any links we get
        files_links = gallery_links | docs_links
        if files_links:
            # Make the target dir if needed.
            file_dir_abs_path = FILES_DIR / dir_name
            if not file_dir_abs_path.is_dir():
                file_dir_abs_path.mkdir(parents=True, exist_ok=True)

            for file_url, file_name in files_links:
                clean_file_name = file_name.replace('/', '_').replace('\\', '_')
                result = await self.download_file(file_url, clean_file_name, dir_name)
                if result is not None:
                    files_results.append(result)

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


    async def fetch_page(self, url: str, region: str, arch_cat: str) -> tuple:
        """Helper to get both the soup and elements.
           Checks if the soup isn't actually just 404 (that is valid status but invalid article listing).
        """
        soup = await self.get_soup(url)
        if soup is None:
            self.logger.debug(f"Failed getting soup for '{url}' from '{region}'::'{arch_cat}")
            raise ValueError("'Soup' is None")

        police_404 = soup.select_one('div.main > h1')
        if police_404:
            if 'Požadovaná stránka není dostupná' in police_404.get_text():
                self.logger.debug(f"Internal 404 - article not found - '{url}")
                raise ValueError("Invalid Soup")

        el_lists = self.select_element_lists(soup, url, region, arch_cat)
        if el_lists is None:
            self.logger.debug(f"Failed parsing elements for '{url}' from '{region}'::'{arch_cat}")
            raise ValueError("'Elements' is None")

        return soup, el_lists


    async def scrape_article(self, url: str, region: str, arch_cat: str) -> PoliceArticleResult | None:
        """The main scraping method."""
        soup, el_lists = await self.fetch_page(url, region, arch_cat)
        title_el, description_el, content_el, imgs_el, docs_el, sound_el = el_lists

        title_text = title_el[0].get_text()
        description_text = description_el[0].get_text().strip()
        date_text = self.parse_date(content_el)
        author_text = self.parse_author(content_el)
        arch_cat = self.resolve_archive_category(arch_cat, date_text, soup, url, region)
        year = self.resolve_year(arch_cat, date_text)
        page_bytes = await self.fetch(url)  # For 'html_base64'
        files = await self.download_files(imgs_el, docs_el, sound_el, soup, url)

        # For 'content_text' we first define unwanted elements, then exclude them from the content_text parse
        non_text_els = self.collect_non_text_els(title_el, description_el, imgs_el, docs_el)
        content_text = self.extract_content_text(content_el, non_text_els)

        # Try parsing a location from the text
        district, municipality = self.match_location(title_text, description_text, content_text)

        # Get keywords based on url AND the content
        keywords = {
            key for key in ALL_KEYWORDS
                if (key in url.lower()
                    or key in content_text.lower()
                    or key in description_text.lower())
        }

        return PoliceArticleResult({
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
        })


    # todo async is pointless here
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
        """Store dicts of all word-cases and their nominative as 'lookup's.
           Store sorted regex patterns of the all word-cases as 'pattern's.
        """
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


    async def scrape_site(self, queue, workers, work_items):
        for item in work_items:
            await queue.put(item)
        await queue.join()

        for w in workers:
            w.cancel()

        if len(self.results_buffer) > 0:
            await self.flush_buffer()


    async def setup_scrape(self):
        queue = asyncio.Queue()
        async def _worker(scrape_queue: asyncio.Queue):
            """Listens for input from queue. Manages the buffer writes. """
            while True:
                region, archive_category, url = await scrape_queue.get()
                try:
                    result = await self.scrape_article(url, region, archive_category)
                    self.process_single_result(result)
                    self.results_buffer.append((region, archive_category, result))
                    self.logger.info(f"Saved an article")

                    if len(self.results_buffer) > self.results_buffer_threshold:
                        self.logger.info(f"Writing from a buffer...")
                        await self.flush_buffer()

                except FetchError:
                    self.stats.failed_articles += 1
                    self.write_failed_article(url)
                except Exception:
                    self.logger.error(f"Error while scraping '{url}' from '{region}':", exc_info=True)
                    self.stats.failed_articles += 1
                    self.write_failed_article(url)
                finally:
                    self.stats.articles_processed += 1
                    self.logger.info(f"Processed {self.stats.articles_processed} out of {self.queue_size} articles.")
                    scrape_queue.task_done()

        workers = [asyncio.create_task(_worker(queue)) for _ in range(20)]
        work_items = await self.mk_work_items()
        self.queue_size = len(work_items)
        return queue, workers, work_items


    async def run(self):
        timer_start = time.time()
        await self.load_czech_locations()
        queue, workers, work_items = await self.setup_scrape()

        await self.scrape_site(queue, workers, work_items)

        timer_end = time.time()
        formatted_time = str(timedelta(seconds=timer_end - timer_start))
        self.log_report(formatted_time)


async def scrape_police_articles():
    async with PoliceArticlesScraper() as ps:
        try:
            await ps.run()

        finally:
            destroy()


if __name__ == "__main__":
    asyncio.run(scrape_police_articles(), debug=True)