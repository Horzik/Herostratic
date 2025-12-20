import json
from asyncio.tasks import gather
from dataclasses import dataclass
import asyncio
import logging
from typing import TypedDict

import aiofiles
from bs4 import BeautifulSoup

from config import LOG_DIR, ERRORS_LOG_FP, AKT_ART_FP, AKT_RESULTS_FP, METRO_ARTICLES_FP, METRO_RESULTS_FP
from scraper.core import BaseScraper
from utils.io_utils import atomic_json_write
from utils.logger import LogConfig, destroy


@dataclass
class ScrapingStats:
    saved_articles: int = 0
    all_tasks: int = 0


class ScrapeResult(TypedDict):
    url: str
    title: str
    author: str | None
    date: str | None
    text: str


class MetroArticleScraper(BaseScraper):
    # TODO get the pictures
    """ WIP Scrapes aktualne article links for data. """
    MODULE_NAME = 'scrape_metro_articles'
    BASE_URL = 'https://metro.cz'
    INPUT_FILE = METRO_ARTICLES_FP
    OUTPUT_FILE = METRO_RESULTS_FP
    GOV_SITE = False
    SEMAPHORE_COUNT = 10
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.INFO,
        log_file_path=LOG_DIR / 'scrape_metro_articles.log',
        log_errors_file_path=ERRORS_LOG_FP)


    def __init__(self):
        super().__init__()
        self.stats = ScrapingStats()
        self.res_buffer = list()
        self.buffer_threshold = 10


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


    def get_content_text(self, soup: BeautifulSoup, url: str) -> str:
        self.logger.debug(f"Parsing the content text...")

        container_el = self.get_element(soup, 'div#art-text')
        if not container_el:
            self.logger.error(f"Error: no article container found in url: '{url}")
            self.errors.append("fError parsing '{url}', ")
            raise Exception # todo raising exceptions?

        text = ''
        for el in container_el:
            self.logger.debug(f"Content loop 'el'::: {el}")
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
            self.errors.append("fError parsing '{url}', ")
            raise Exception
        title_text = title_el.text.strip()
        self.logger.debug(f"Title found:: '{title_text}'")

        return title_text


    def get_date_text(self, soup):
        date_el = soup.select_one('div.art-info span.time')
        date_text = date_el.text.strip().replace('\xa0', ' ')
        self.logger.debug(f"Found date:: {date_text}")

        return date_text


    async def parse_html(self, url: str) -> ScrapeResult:
        soup = await self.get_soup(url)
        if not soup:
            self.logger.error(f"Error making the soup for url: '{url}'")
            self.errors.append("fError parsing '{url}', ")
            raise Exception

        title_text = self.get_title_text(soup, url)
        authors_text = self.get_authors(soup)
        date_text = self.get_date_text(soup)
        content_text = self.get_content_text(soup, url)

        result = ScrapeResult(
            url=url,
            title=title_text,
            author=authors_text,
            date=date_text,
            text=content_text,)

        self.logger.info(f"Finished parsing url: '{url}'...")
        return result


    async def add_result(self, result: ScrapeResult, reg: str):
        # TODO add the regions?
        async with self.lock:
            if len(self.res_buffer) > self.buffer_threshold:
                await self.flush_buffer()
            self.res_buffer.append(result)


    async def scrape_article(self, url: str, reg):
        """ The main task. """
        self.logger.debug(f"Scraping url: '{url}'")
        result = await self.parse_html(url)
        await self.add_result(result, reg)
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
                self.logger.debug(f"Data for scrape_article::: {url.strip(), region}")

        self.logger.debug(f"Returning this as tasks:: {tasks}")
        return tasks


    async def run(self) -> None:
        try:
            self.logger.info(f"Scraper live...")
            jobs = await self.mk_tasks(self.INPUT_FILE)
            self.stats.all_tasks = len(jobs)
            self.logger.info(f"Starting {self.stats.all_tasks} tasks...")
            results = await gather(*jobs, return_exceptions=True)

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
