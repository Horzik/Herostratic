import aiofiles
import asyncio
import base64
import json
import logging
from asyncio.tasks import gather
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import timezone, datetime
from typing import TypedDict

from config import LOG_DIR, ERRORS_LOG_FP, METRO_ARTICLES_FP, METRO_RESULTS_FP, METRO_IMG_FP, ALL_KEYWORDS
from scraper.core import BaseScraper
from utils.io_utils import atomic_json_write
from utils.logger import LogConfig, destroy


@dataclass
class ScrapingStats:
    saved_articles: int = 0
    all_tasks: int = 0

class ArticleResult(TypedDict):
    source: str
    url: str
    title: str
    region: str
    author: str | None
    date: str | None
    content: str
    keywords: set[str]
    scraped_at: str
    html_base64: str

class MetroArticleScraper(BaseScraper):
    """ WIP Scrapes aktualne article links for data. """
    MODULE_NAME = 'scrape_metro_articles'
    BASE_URL = 'https://metro.cz'
    INPUT_FILE = METRO_ARTICLES_FP
    OUTPUT_FILE = METRO_RESULTS_FP
    IMG_FILE = METRO_IMG_FP
    GOV_SITE = False
    SEMAPHORE_COUNT = 2
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'scrape_metro_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        self.stats = ScrapingStats()
        self.res_buffer = list()
        self.buffer_threshold = 10


    # async def get_imgs(self, soup) -> list:
    #     # TODO, the HTML *should* contain all we need
    #     """ Get all urls of images from the article gallery.
    #      """
    #     self.logger.debug(f"Parsing the images...")
    #
    #     imagespace_el = soup.select_one('samp.imagespace')
    #     self.logger.debug(f"Found first gallery url element...: {imagespace_el}")
    #
    #     parent_el = imagespace_el.parent
    #     self.logger.debug(f"Parent element...: {parent_el.prettify()}")
    #     self.logger.debug(f"Gallery url:: {imagespace_el}")
    #     gallery_url = parent_el.get('href').strip()
    #     curr_soup = await self.get_soup(imagespace_el) # Set the first soup
    #     # self.logger.debug(f"Got the soup....")
    #
    #     pager = curr_soup.select_one('div.navigation > br.h').get_text()
    #     self.logger.debug(f"found some pager")
    #     curr_img = int(pager.split('/')[0].strip())
    #     max_imgs = int(pager.split('/')[1].strip())
    #     self.logger.debug(f"Curr img: {curr_img} next img: {max_imgs}")
    #
    #     images_urls = []
    #     while curr_img <= max_imgs: # The next img button is always there ==> check the image count directly
    #         self.logger.debug(f"In the img loop....")
    #         img_style = curr_soup.select_one('u.odklad').get('style') # The image url is embedded in the "style" attribute
    #         url_match = re.search(r'url\((.*?)\)', img_style)
    #         if url_match:
    #             url = url_match.group(1).strip('"\'')
    #             images_urls.append(url)
    #
    #         next_page = curr_soup.select_one('div#navigation a.img-next').get('href')
    #         curr_soup = await self.get_soup(next_page)
    #         curr_img = pager.split('/')[0].strip()
    #
    #
    #     self.logger.debug(f"Saved {len(images_urls)}/{max_imgs} images:: \n "
    #                       f"{images_urls}")
    #     return images_urls


    async def read_results(self) -> list:
        try:
            async with aiofiles.open(self.OUTPUT_FILE, mode='r') as fp:
                data = await fp.read()
                results = json.loads(data)
        except (FileNotFoundError, json.JSONDecodeError):
            results = []
        if not isinstance(results, list):
            results = []
        return results


    async def flush_buffer(self):
        results = await self.read_results()
        results.extend(self.res_buffer)
        atomic_json_write(results, self.OUTPUT_FILE)

        self.stats.saved_articles += len(self.res_buffer)
        self.res_buffer = []
        self.logger.debug(f"Finished writing the buffer...")
        return


    async def get_content_text(self, soup: BeautifulSoup, url: str) -> str:
        self.logger.debug(f"Parsing the content text...")
        container_el = soup.select_one('div#art-text')
        # if not container_el:
        #     self.logger.error(f"Error: no article container found in url: '{url}")
        #     self.errors.append("fError parsing '{url}', ")
        text = ''
        for el in container_el:
            if el == 'div':
                continue
            text = text + el.text.strip() + '\n'
        return text


    def get_authors(self, soup) -> str:
        authors_el = soup.select_one('div.authors')
        authors_text = ''
        for author in authors_el:
            authors_text += author.text.strip()

        self.logger.debug(f"Authors found: '{authors_text}'")
        return authors_text


    def get_title_text(self, soup, url):
        title_el = soup.select_one('h1.arttit')
        if not title_el:
            self.logger.error(f"Error parsing the title for url: '{url}'")
            self.errors.append(f"Error parsing '{url}', ")
            raise Exception

        title_text = title_el.text.strip()
        self.logger.debug(f"Title found:: '{title_text}'")
        return title_text


    def get_date_text(self, soup):
        date_el = soup.select_one('div.art-info span.time')
        date_text = date_el.text.strip().replace('\xa0', ' ')
        self.logger.debug(f"Found date:: {date_text}")
        return date_text


    async def parse_html(self, url: str, region: str) -> ArticleResult:
        soup = await self.get_soup(url)
        if not soup:
            self.logger.error(f"Error making the soup for url: '{url}'")
            self.errors.append(f"Error parsing '{url}', ")
            raise Exception

        title_text = self.get_title_text(soup, url)
        authors_text = self.get_authors(soup)
        date_text = self.get_date_text(soup)
        content_text = await self.get_content_text(soup, url)

        keywords_from_article = {
            key for key in ALL_KEYWORDS
            if key in url or key in content_text}

        page_bytes = await self.fetch(url) # For the base64 html

        result: ArticleResult = {
            'source': 'metro',
            'url': url,
            'title': title_text,
            'region': region,
            'author': authors_text,
            'date': date_text,
            'content': content_text,
            'keywords': keywords_from_article,
            'scraped_at': datetime.now(timezone.utc).isoformat(),
            "html_base64": base64.b64encode(page_bytes).decode("ascii"),
        }

        self.logger.info(f"Finished parsing url: '{url}'...")
        return result


    async def add_result(self, result: ArticleResult):
        # TODO add the regions?
        async with self.lock:
            if len(self.res_buffer) > self.buffer_threshold:
                await self.flush_buffer()
            self.res_buffer.append(result)


    async def scrape_article(self, url: str, region: str):
        """ The main task.
        """
        result = await self.parse_html(url, region)
        await self.add_result(result)
        self.stats.saved_articles += 1
        self.logger.info(f"Finished scraping {self.stats.saved_articles} out of {self.stats.all_tasks} articles...")
        return


    def process_scrape_results(self, results: list) -> None:
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Task {i} failed: {result}")
                self.errors.append(f"Task {i} failed: {result}")


    async def mk_tasks(self, fp: str) -> list:
        self.logger.debug(f"Making the tasks...")
        async with aiofiles.open(fp) as a:
            content = await a.read()
            tasks_dict = json.loads(content)

        tasks = []
        for region, url_list in tasks_dict.items():
            for url in url_list:
                tasks.append(self.scrape_article(url.strip(), region))
                # self.logger.debug(f"Data for scrape_article::: {url.strip(), region}")

        return tasks


    async def run(self) -> None:
        try:
            self.logger.info(f"Scraper live...")
            jobs = await self.mk_tasks(self.INPUT_FILE)

            self.stats.all_tasks = len(jobs)
            self.logger.info(f"Starting {self.stats.all_tasks} tasks...")
            results = await gather(*jobs, return_exceptions=False)

            self.process_scrape_results(results)
            self.logger.info(f"Success for {len(results) - len(self.errors)} out of {len(jobs)} tasks, exiting the scraper...")

        finally: # Write the remaining buffer
            if self.res_buffer:
                async with self.lock:
                    await self.flush_buffer()


async def main():
    async with MetroArticleScraper() as mas:
        try:
            await mas.run()
        finally:
            destroy()


if __name__ == '__main__':
    asyncio.run(main())
