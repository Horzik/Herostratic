import asyncio
import base64
import logging
import re
import time

from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import timedelta, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import TypedDict
from urllib.parse import urljoin

from config import (
    POLICE_ARTICLES_FP, LOG_DIR, ERRORS_LOG_FP, POLICE_RESULTS_FP,
    PIG_RANKS, DATE_REGEX, ALL_KEYWORDS, FAILED_POLICE_RESULTS_FP,
    FILES_DIR, ALL_DISTRICTS_FP, ALL_MUNIS_FP)
from scraper.core import BaseScraper
from scraper.site_configs import BASE_POLICE_URL
from utils.get_file_type import detect_file_category
from utils.io_utils import atomic_json_write, read_json
from utils.logger import LogConfig, destroy
from utils.network_utils import FetchError
from utils.parsing_utils import parse_czech_date


class PoliceArticleResult(TypedDict):
    source: str
    archive_category: str  # year or 'non_years'
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

# noinspection RegExpUnnecessaryNonCapturingGroup
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

        # Cache for location search
        self.district_lookup = {}
        self.muni_lookup = {}
        self.muni_pattern: re.Pattern | None = None
        self.district_pattern: re.Pattern | None = None
        self.load_czech_locations() # Load the cache


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
        """ Returns the date as iso string.
        """
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
        """ Returns the police officer author by parsing for police ranks.
        """
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
        """ Try getting the year from category, then try from date.
        """
        try:
            year = int(arch_cat.strip())
        except ValueError:
            year = None

        if date_text and not year:
            year = int(date_text[:4])
        return year


    def resolve_archive_category(self, arch_cat, date_text, soup, url, region):
        """ Fed 'arch_cat' be either a year or the string 'non_years'. Try resolving to a year.
        """
        if arch_cat == "non_years" and date_text is not None:
            arch_cat = str(date_text[:4])
        elif arch_cat == "non_years" and date_text is None:
            # Look for the category in the site navigation.
            drobek_el = soup.select_one('div#siteNavigation')
            if drobek_el:
                drobek_text = drobek_el.get_text()
                arch_cat = drobek_text[-4:]
            else:
                self.logger.error(f"No drobek found for '{url}', '{region}'::'{arch_cat}....'")
        return arch_cat


    def match_location(self, title, description, content_text) -> tuple[str | None, str | None]:
        """ First use the pattern to find and matches in a text. Then use the lookups to find the nominative.
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
        """ Parse the article for the content text.
        """
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
        """Elements to be excluded when parsing the 'content_text'.
        """
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
        """ Returns various tag lists.
        """
        title_el = soup.select('div#content > h1')
        description_el = soup.select('div#content > p:first-of-type')
        content_el = soup.select('div#content')
        # imgs_el = soup.select('div#content > div.graybox > div')
        imgs_el = soup.select('div#content > div.graybox')
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
        """ Goes through the whole soup and looks for 'youtube' links, returns them in a list.
        """
        text = str(soup)

        # Pattern to get the url path for any direct link or inside the iframe ('youtube-nocookie')
        pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube-nocookie\.com/embed/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})'
        matches = re.findall(pattern, text)
        if matches:
            return [f'https://www.youtube.com/watch?v={vid}' for vid in set(matches)]  # Deduplicate, return full URLs
        else:
            return None


    # todo make into util
    async def download_ytb_video(self, ytb_url, dir_name) -> tuple[str, str] | None:
        """Use the 'yt_dlp' lib to download 'youtube' links.
           Returns a tuple of (file_path, file_type).
        """
        import yt_dlp
        abs_dir: Path = FILES_DIR / dir_name
        opts = {'outtmpl': str(abs_dir / '%(title)s.%(ext)s'), 'format': 'best[height<=720]', 'quiet': True}

        # Wrapper for non-blocking downloads, returns the title (used as file name)
        def _download():
            with yt_dlp.YoutubeDL(opts) as ydl:
                dl_info = ydl.extract_info(ytb_url, download=True)
                f_name = ydl.prepare_filename(dl_info)
                return f_name

        try:
            file_name = await asyncio.to_thread(_download)
            rel_path = str(dir_name + '/' + Path(file_name).name)
            return str(rel_path), 'video'
        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f"Error downloading a youtube video from: {dir_name}...")
            self.logger.error(e)
            return None


    # todo make into util?
    # TODO for videos we need a different fetch (so the timeout doesnt fuck us over)
    async def download_file(self, file_url, file_name, dir_name) -> tuple[str, str] | None:
        """ Saves target {file_url} bytes as {file_name} in {dir_name}.
            Returns the file_path and file_type.
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
        """ Police gallery parser which returns links to the images inside.
            First gets the gallery links and names of all images, then fetches
            soup for each and extract the full img link.

            Returns:
                set[FileMetadata]: Set of tuples (img_url, img_name)
        """
        # First for each img we get its gallery link and respective img name
        raw_gal_links: set[FileMetadata] = set()
        gallery_el = imgs_el.select('div.box')
        for i, box_space in enumerate(gallery_el):
            self.logger.debug(f"gallery box ref:: {box_space}")
            iframe_href = box_space.select_one('a.iframe').get('href')
            if not iframe_href:
                self.logger.debug(f"No iFrame link found in the box, skipping..")
                continue

            cleaned_href = iframe_href.strip('//').replace('%3F', '?') # The iframe href looks like "//path/to_image"
            img_link = "https://" + cleaned_href # "cleaned_href" is missing "https://"
            name_el = box_space.select_one('img.thumb')
            img_name = name_el.get('alt', 'none').replace(' ', '_') + '.png' if name_el else f"{i}.png"

            self.logger.debug(f"Found img number {i}: with gallery href {img_link}")
            raw_gal_links.add((img_link, img_name))

        # Then we fetch the gallery link, extract the actual img link and return that.
        img_links: set[FileMetadata] = set()
        for gal_link, name in raw_gal_links:
            img_soup = await self.get_soup(gal_link)
            if not img_soup:
                continue

            img_href = img_soup.select_one('div#image > img').attrs.get('src')
            img_link = urljoin(self.BASE_URL, img_href)
            self.logger.debug(f"Returning img link/name: {img_href}:::{name}")
            img_links.add((img_link, name))

        return img_links


    def parse_docs_links(self, docs_el, sound_el=None) -> set[FileMetadata]:
        """ Parse for police embedded documents, returns links to the imgs/videos/sounds of the article.
        """
        doc_files: set[FileMetadata] = set()

        # Regular doc files are in a list directly on the page.
        docs_list = docs_el.select('ul > li')
        if docs_list is not None:
            for li in docs_list:
                doc_li_el = li.select_one('a')
                if doc_li_el:
                    file_name = doc_li_el.get_text(strip=True)
                    file_url = self.BASE_URL + li.select_one('a').get('href')
                    if 'clanek/' in file_url:
                        # Check if the target link doesn't lead to another article
                        continue
                    else:
                        doc_files.add((file_url, file_name))

        # Sound have their own element.
        if sound_el is not None:
            sound_file_path = sound_el.get('data-file')
            if sound_file_path:
                sound_file_url = self.BASE_URL + sound_file_path
                self.logger.debug(f"Sound file url:: {sound_file_url}")
                sound_file_name = sound_file_path.rsplit('.')[0].rsplit('/')[1]  # "soubor/vandal-2109-mp3.aspx" ==> get just the unique string in middle
                self.logger.debug(f"Sound file name:: {sound_file_name}")
                doc_files.add((sound_file_url, sound_file_name))

        return doc_files


    async def download_files(self, imgs_el, docs_el, sound_el, soup, url) -> list[tuple[str, str]]:
        """Downloads the article embedded files (pictures/videos/sounds).
           Returns a list of tuple(file_path, file_type).
        """
        files_results: list[tuple[str, str]] = []
        dir_name = re.search(r'/([^/]+)\.[^.]+$', url).group(1).strip()

        # Get 'policie.cz' specific files that are embedded in the article
        gallery_links = set()
        docs_links = set()
        if imgs_el:
            self.logger.debug(f"gal el::")
            gallery_links = await self.parse_gallery_links(imgs_el[0])
        if docs_el:
            docs_links = self.parse_docs_links(docs_el[0], sound_el[0] if sound_el else None)

        # Download any links we found
        files_links = gallery_links | docs_links
        if files_links:
            # Make the target dir if needed.
            file_dir_abs_path = FILES_DIR / dir_name
            if not file_dir_abs_path.is_dir():
                file_dir_abs_path.mkdir(parents=True, exist_ok=True)

            for file_url, file_name in files_links:
                self.logger.debug(f"Downloading file url: {file_url} with name: {file_name}")
                clean_file_name = file_name.replace('/', '_').replace('\\', '_')
                result = await self.download_file(file_url, clean_file_name, dir_name)
                if result is not None:
                    files_results.append(result)

        # Finally get any 'youtube' links in the article
        ytb_urls = self.find_youtube_links(soup)
        if ytb_urls:
            for ytb_url in ytb_urls:
                dl_res = await self.download_ytb_video(ytb_url, dir_name)
                if dl_res:
                    files_results.append(dl_res)

        return files_results


    async def flush_buffer(self):
        """ Writes to the in-memory "all_results" first. Then it saves the batched articles.
        """
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
        page_bytes = await self.fetch(url, gov_site=self.GOV_SITE)
        if page_bytes is None:
            raise

        soup = BeautifulSoup(page_bytes, 'lxml')
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

        return soup, el_lists, page_bytes


    async def scrape_article(self, url: str, region: str, arch_cat: str) -> PoliceArticleResult | None:
        """ The main scraping method. Receives the
        """
        soup, el_lists, page_bytes = await self.fetch_page(url, region, arch_cat)
        title_el, description_el, content_el, imgs_el, docs_el, sound_el = el_lists

        title_text = title_el[0].get_text()
        description_text = description_el[0].get_text().strip()
        date_text = self.parse_date(content_el)
        author_text = self.parse_author(content_el)
        arch_cat = self.resolve_archive_category(arch_cat, date_text, soup, url, region)
        year = self.resolve_year(arch_cat, date_text)
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


    def load_result_urls(self) -> set[str]:
        """ Reads the "police_results" and returns a set of the URLs.
            Used for deduping results, ie to not re-add a result which we already have.
        """
        initial_results_urls = set()

        results_dict = read_json(self.OUTPUT_FILE)
        for region, arch_categories in results_dict.items():
            for category, articles in arch_categories.items():
                for article in articles:
                    initial_results_urls.add(article['url'])

        self.cached_results = results_dict # Assign the class attribute with all existing results
        self.logger.info(f"Initial results urls: {len(initial_results_urls)}")
        return initial_results_urls


    def load_czech_locations(self):
        """ Store dicts of all word-cases and their nominative as 'lookup's.
            Store sorted regex patterns of the all word-cases as 'pattern's.
        """
        muni_map = read_json(ALL_MUNIS_FP)
        district_map = read_json(ALL_DISTRICTS_FP)

        self.muni_lookup = {form.lower(): nominative for form, nominative in muni_map.items()}
        self.district_lookup = {form.lower(): nominative for form, nominative in district_map.items()}

        muni_set = sorted(self.muni_lookup.keys(), key=len, reverse=True)
        district_set = sorted(self.district_lookup.keys(), key=len, reverse=True)

        # The linter warning are wrong here, not sure why, but it works
        self.muni_pattern = re.compile(r'\b(?:' + '|'.join(re.escape(m) for m in muni_set) + r')\b')
        self.district_pattern = re.compile(r'\b(?:' + '|'.join(re.escape(d) for d in district_set) + r')\b')


    async def setup_scrape(self):
        queue = asyncio.Queue()

        async def _worker(q: asyncio.Queue, q_len: int):
            """ Listens for input from queue. Manages the buffer writes.
            """
            while True:
                region, archive_category, url = await q.get()
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
                except Exception: # Catch ValueErrors and anything else
                    self.logger.error(f"Error while scraping '{url}' from '{region}':", exc_info=True)
                    self.stats.failed_articles += 1
                    self.write_failed_article(url)
                finally:
                    self.stats.articles_processed += 1
                    self.logger.info(f"Processed {self.stats.articles_processed} out of {q_len} articles.")
                    q.task_done()

        def _fill_queue():
            """ Appends '(region, category, url)' from the INPUT_FILE directly into the queue.
                Returns the queue length.
            """
            target_articles = read_json(self.INPUT_FILE)
            scraped_articles = self.load_result_urls()

            seen = set()  # Keep track to dedupe
            for region, arch_categories in target_articles.items():
                for arch_cat, urls_list in arch_categories.items():
                    for url in urls_list:
                        if url not in scraped_articles and url not in seen:
                            seen.add(url)
                            queue.put_nowait((region, arch_cat, url))

        # Fill the queue, prep the workers, return both
        _fill_queue()
        queue_len = queue.qsize()
        workers = [asyncio.create_task(_worker(queue, queue_len)) for _ in range(20)]
        return queue, workers


    async def run(self):
        """ Main run method. Prepares and executes the tasks.
        """
        # Prep the queue and workers
        timer_start = time.time()
        queue, workers = await self.setup_scrape()

        # Run the tasks, kill the workers
        await queue.join()
        for w in workers:
            w.cancel()

        # Last flush and logs
        if self.results_buffer:
            await self.flush_buffer()
        self.log_report(str(timedelta(seconds=time.time() - timer_start)))


async def scrape_police_articles():
    async with PoliceArticlesScraper() as ps:
        try:
            await ps.run()
        finally:
            destroy()

if __name__ == "__main__":
    asyncio.run(scrape_police_articles(), debug=True)
