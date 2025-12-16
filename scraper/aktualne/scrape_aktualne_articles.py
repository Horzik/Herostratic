import json
from asyncio.tasks import gather
from dataclasses import dataclass
import asyncio
import logging
from typing import TypedDict

import aiofiles

from config import AKTUALNE_SITES_FP, LOG_DIR, ERRORS_LOG_FP, AKT_ART_FP, AKT_RESULTS_FP
from scraper.core import BaseScraper
from utils.io_utils import async_json_read, atomic_json_write
from utils.logger import LogConfig, destroy


@dataclass
class ScrapingStats:
    saved_articles: int = 0
    tasks_len: int = 0


class ScrapeResult(TypedDict):
    url: str
    title: str
    author: str | None
    date: str | None
    text: str


class AktualneArticlesScraper(BaseScraper):
    """ WIP => Goes over all available listings from 'aktualne' sites and returns valid article links """
    MODULE_NAME = 'aktualne_articles'
    BASE_URL = 'https://zpravy.aktualne.cz'
    INPUT_FILE = AKT_ART_FP
    OUTPUT_FILE = AKT_RESULTS_FP
    GOV_SITE = True # aktualne is harsh
    SEMAPHORE_COUNT = 2
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.INFO,
        log_file_path=LOG_DIR / 'aktualne_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )


    def __init__(self):
        super().__init__()
        self.stats = ScrapingStats()
        self.results_buffer = list()
        self.buffer_threshold = 10
        self.all_tasks_len = 0 # Can be used for progress bar


    async def write_buffer(self):
        try:
            async with aiofiles.open(AKT_RESULTS_FP, mode='r') as fp:
                data = await fp.read()
                results = json.loads(data)
        except (FileNotFoundError, json.JSONDecodeError):
            results = []
        if not isinstance(results, list):
            results = []

        results.extend(self.results_buffer)
        atomic_json_write(results, AKT_RESULTS_FP)
        self.stats.saved_articles += len(self.results_buffer)
        self.logger.debug(f"Finished writing the buffer...")
        return


    async def get_content_text(self, soup, url) -> str | None:
        container_el = soup.select_one('div.article__content')
        if not container_el:
            self.logger.error(f"Error: no article container found in url: '{url}")
            return None
        text = ''
        for el in container_el:
            text = text + el.text.strip() + '\n'
        return text


    async def parse_html(self, url: str):
        # todo type hints?
        soup = await self.get_soup(url)
        if not soup:
            self.logger.error(f"Error making the soup for url: '{url}'")
            return None

        title_el = soup.select_one('h1.article-title')
        if not title_el:
            self.logger.error(f"Error parsing the title for url: '{url}'")
            return None
        title_text = title_el.text.strip()

        author_el = soup.select_one('a.author__name')
        author_text = author_el.text.strip() if author_el else 'no_author'
        date_el = soup.select_one('a.author__date')
        date_text = date_el.text.strip() if date_el else 'no_date'

        content_text = await self.get_content_text(soup, url)
        result = ScrapeResult(
            url=url,
            title=title_text,
            author=author_text,
            date=date_text,
            text=content_text,
        )

        self.logger.info(f"Finished parsing url: '{url}'...")
        return result


    async def scrape_article(self, url):
        result = await self.parse_html(url)
        # self.logger.debug(f"Appended the results, currenmt results:: {self.results_buffer}")
        # self.logger.debug(f"Current len of buffer: {len(self.results_buffer)}")
        # self.logger.debug(f"Threshold: {self.buffer_threshold}")

        if len(self.results_buffer) > self.buffer_threshold:
            async with self.lock:
                await self.write_buffer()
                self.results_buffer = [] # Clean the buffer

        self.results_buffer.append(result)

        return


    async def mk_tasks(self) -> list:
        art_links = []
        async with aiofiles.open(self.INPUT_FILE) as a:
            a_lines = await a.readlines()
            for line in a_lines:
                art_links.append(line.strip())

        self.all_tasks_len = len(art_links)
        self.logger.debug(f"The art links:: {art_links}")
        return [self.scrape_article(url) for url in art_links]


    async def run(self):
        self.logger.info(f"Scraper live...")
        jobs = await self.mk_tasks()
        self.logger.info(f"Starting {len(jobs)} tasks...")
        # await gather(*jobs, return_exceptions=True)

        results = await gather(*jobs, return_exceptions=True)
        # Check for exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Task {i} failed: {result}")
                self.errors.append(f"Task {i} failed: {result}")

        # Write remaining buffer
        if len(self.results_buffer) > 0:
            await self.write_buffer()

        self.logger.info(f"Success for {len(results) - len(self.errors)} out of {len(jobs)} tasks, exiting the scraper...")


async def main():
    async with AktualneArticlesScraper() as aas:
        try:
            await aas.run()
        finally:
            destroy()


if __name__ == '__main__':
    asyncio.run(main())
