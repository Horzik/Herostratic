from asyncio import gather
from dataclasses import dataclass
from aiofiles import open as aiopen
import asyncio
import logging
import time

from config import AKTUALNE_SITES_FP, LOG_DIR, ERRORS_LOG_FP, URL_KEYWORDS, AKT_ART_FP
from scraper.core import BaseScraper
from utils.logger import LogConfig, destroy



@dataclass
class ParsingResults:
    saved_articles: int = 0
    articles_processed: int = 0
    listings_parsed: int = 0


class AktualneListingsScraper(BaseScraper):
    """  Goes over all available listings from 'aktualne' sites and returns valid article links.
    """
    MODULE_NAME = 'get_aktualne_articles'
    BASE_URL = 'https://zpravy.aktualne.cz'
    INPUT_FILE = AKTUALNE_SITES_FP
    OUTPUT_FILE = AKT_ART_FP
    SEMAPHORE_COUNT = 10
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_aktualne_articles.log',
        log_errors_file_path=ERRORS_LOG_FP)


    def __init__(self):
        super().__init__()
        self.stats = ParsingResults()
        self.articles_buffer = []
        self.articles_buffer_threshold = 5


    async def flush_buffer(self):
        async with self.lock:
            async with aiopen(self.OUTPUT_FILE, 'a') as a:
                for article in self.articles_buffer:
                    await a.write(article + '\n')
                self.articles_buffer.clear()


    def add_to_buffer(self, article_title, article):
        a_tag = article.select_one('h2.e-web-aktualne-articles-card-horizontal__title a')
        article_link = a_tag['href']

        self.articles_buffer.append(article_link)
        self.logger.info(f"Added article with title: '{article_title}'...link: '{article_link}'...")
        with self.lock:
            self.stats.saved_articles += 1


    async def get_listing_articles(self, soup):
        # self.logger.info(f"Parsing a listing....")
        container = soup.select_one('div.e-web-aktualne-articles-cards__flex')
        articles_list = container.select('article')

        for article in articles_list:
            # self.logger.debug(f"Found title: {article_title}")
            article_title = article.get('aria-label')
            if any(keyword in article_title for keyword in URL_KEYWORDS):
                self.add_to_buffer(article_title, article)

        self.stats.articles_processed += 1


    async def get_next_page(self, soup):
        butt = soup.select_one('a[aria-label="next"]')
        if not butt:
            self.logger.info(f"No next page found...")
            return None

        next_href = butt.get('href')
        if not next_href:
            self.logger.error(f"Found the next page button but didn't get the href, exiting...")
            return None

        self.stats.listings_parsed += 1
        self.logger.debug(f"Parsed {self.stats.listings_parsed} pages, going to the next page...")
        return self.BASE_URL + next_href


    async def parse_archive(self, url) -> bool | None:
        new_url = url
        while new_url:
            soup = await self.get_soup(new_url)
            if not soup:
                self.logger.error(f"Couldn't get content from '{url}', returning None...")
                return None

            await self.get_listing_articles(soup)
            if len(self.articles_buffer) > self.articles_buffer_threshold:
                await self.flush_buffer()

            new_url = await self.get_next_page(soup)

        return True


    def mk_tasks(self) -> list:
        with open(self.INPUT_FILE, 'r') as f:
            tasks = [self.parse_archive(url) for url in f]
        return tasks


    async def run(self):
        self.logger.info(f"Starting the aktualne scraper...")
        timer_start = time.perf_counter()

        archive_jobs = self.mk_tasks()
        await gather(*archive_jobs, return_exceptions=True) # todo process results?

        await self.flush_buffer()
        timer_end = time.perf_counter()

        self.logger.info(f"Finished parsing {len(archive_jobs)} links in {timer_end - timer_start} seconds")
        self.logger.info(f"Parsed {self.stats.listings_parsed} listing pages, found total {self.stats.articles_processed} articles, "
                         f"saved {self.stats.saved_articles} articles. Exiting....")


async def main():
    async with AktualneListingsScraper() as als:
        try:
            await als.run()
        finally:
            destroy()


if __name__ == "__main__":
    asyncio.run(main())
