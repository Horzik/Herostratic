import json
from asyncio.tasks import gather
from dataclasses import dataclass
import asyncio
import logging
from typing import TypedDict

import aiofiles
from bs4 import BeautifulSoup

from config import LOG_DIR, ERRORS_LOG_FP, AKT_ART_FP, AKT_RESULTS_FP
from scraper.core import BaseScraper
from utils.io_utils import atomic_json_write
from utils.logger import LogConfig, destroy


@dataclass
class ScrapingStats:
    saved_articles: int = 0


class ScrapeResult(TypedDict):
    url: str
    title: str
    author: str | None
    date: str | None
    text: str


class AktualneArticlesScraper(BaseScraper):
    """ WIP Scrapes aktualne article links for data. """
    MODULE_NAME = 'scrape_aktualne_articles'
    BASE_URL = 'https://zpravy.aktualne.cz'
    INPUT_FILE = AKT_ART_FP
    OUTPUT_FILE = AKT_RESULTS_FP
    GOV_SITE = True # aktualne is harsh
    SEMAPHORE_COUNT = 2
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.INFO,
        log_file_path=LOG_DIR / 'scrape_aktualne_articles.log',
        log_errors_file_path=ERRORS_LOG_FP)


    def __init__(self):
        super().__init__()
        self.stats = ScrapingStats()
        self.res_buffer = list()
        self.buffer_threshold = 10


    @staticmethod
    async def read_results() -> list:
        try:
            async with aiofiles.open(AKT_RESULTS_FP, mode='r') as fp:
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
        atomic_json_write(results, AKT_RESULTS_FP)

        self.stats.saved_articles += len(self.res_buffer)
        self.res_buffer = []
        self.logger.debug(f"Finished writing the buffer...")
        return


    async def get_content_text(self, soup: BeautifulSoup, url: str) -> str:
        container_el = soup.select_one('div.article__content')
        if not container_el:
            self.logger.error(f"Error: no article container found in url: '{url}")
            raise Exception
        text = ''
        for el in container_el:
            text = text + el.text.strip() + '\n'
        return text


    async def parse_html(self, url: str) -> ScrapeResult:
        soup = await self.get_soup(url)
        if not soup:
            self.logger.error(f"Error making the soup for url: '{url}'")
            raise Exception

        title_el = soup.select_one('h1.article-title')
        if not title_el:
            self.logger.error(f"Error parsing the title for url: '{url}'")
            raise Exception
        title_text = title_el.text.strip()

        author_el = soup.select_one('a.author__name')
        author_text = author_el.text.strip() if author_el else 'no_author' # TODO fails everytime
        date_el = soup.select_one('a.author__date')
        date_text = date_el.text.strip() if date_el else 'no_date' # TODO fails everytime
        content_text = await self.get_content_text(soup, url)

        result = ScrapeResult(
            url=url,
            title=title_text,
            author=author_text,
            date=date_text,
            text=content_text,)

        self.logger.info(f"Finished parsing url: '{url}'...")
        return result


    async def add_result(self, result: ScrapeResult):
        async with self.lock:
            if len(self.res_buffer) > self.buffer_threshold:
                await self.flush_buffer()
            self.res_buffer.append(result)


    async def scrape_article(self, url: str):
        """ The main task. """
        result = await self.parse_html(url)
        await self.add_result(result)
        return


    def process_scrape_results(self, results: list) -> None:
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Task {i} failed: {result}")
                self.errors.append(f"Task {i} failed: {result}")


    async def mk_tasks(self, fp: str) -> list:
        art_links = []
        async with aiofiles.open(fp) as a:
            a_lines = await a.readlines()
            for line in a_lines:
                art_links.append(line.strip())

        return [self.scrape_article(url) for url in art_links]


    async def run(self) -> None:
        try:
            self.logger.info(f"Scraper live...")
            jobs = await self.mk_tasks(self.INPUT_FILE)
            self.logger.info(f"Starting {len(jobs)} tasks...")
            results = await gather(*jobs, return_exceptions=True)

            self.process_scrape_results(results)
            self.logger.info(f"Success for {len(results) - len(self.errors)} out of {len(jobs)} tasks, exiting the scraper...")

        finally: # Write remaining buffer
            if len(self.res_buffer) > 0:
                async with self.lock:
                    await self.flush_buffer()


async def main():
    async with AktualneArticlesScraper() as aas:
        try:
            await aas.run()
        finally:
            destroy()


if __name__ == '__main__':
    asyncio.run(main())
