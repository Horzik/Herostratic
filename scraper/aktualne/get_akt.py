import os
from dataclasses import dataclass
import asyncio
import logging
import time

from aiofiles import open as aiopen
from bs4 import BeautifulSoup

from config import AKTUALNE_SITES_FP, AKTUALNE_ARTICLES_FP, LOG_DIR, ERRORS_LOG_FP, URL_KEYWORDS, AKT_ART_FP
from scraper.core import BaseScraper
from utils.io_utils import async_json_read, atomic_json_write
from utils.logger import LogConfig, destroy


@dataclass
class ParsingResults:
    saved_articles: int = 0
    articles_processed: int = 0
    listings_parsed: int = 0


class AktualneListingsScraper(BaseScraper):
    """ WIP => Goes over all available listings from 'aktualne' sites and returns valid article links """
    MODULE_NAME = 'get_aktualne_articles'
    BASE_URL = 'https://zpravy.aktualne.cz'
    INPUT_FILE = AKTUALNE_SITES_FP
    OUTPUT_FILE = AKT_ART_FP
    SEMAPHORE_COUNT = 50
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_aktualne_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        self.stats = ParsingResults()
        self.articles_buffer = []
        self.articles_buffer_threshold = 5


    async def write_buffer(self):
        async with self.lock:
            async with aiopen(self.OUTPUT_FILE, 'a') as a:
                for article in self.articles_buffer:
                    await a.write(article + '\n')
                self.logger.info(f"Written the buffered archives to '.../{self.OUTPUT_FILE}'")
                self.articles_buffer = [] # Reset the buffer

    async def get_listing_articles(self, url):
        # todo double check we do this right (and appending to the buffer)
        if len(self.articles_buffer) >= self.articles_buffer_threshold:
            await self.write_buffer()

        # self.logger.info(f"Parsing a listing....")
        # articles_el = soup.select('div.left-column') # Select the main content
        soup = await self.get_soup(url)
        container = soup.select_one('div.e-web-aktualne-articles-cards__flex')
        articles_list = container.select('article')

        if self.stats.articles_processed // 100:
            self.logger.debug(f"Processed {self.stats.articles_processed} articles....")

        for article in articles_list:
            # article_title = element.get('data-ga4-title') # Get the text
            article_title = article.get('aria-label')
            # self.logger.debug(f"Found title: {article_title}")
            self.stats.articles_processed += 1
            if any(keyword in article_title for keyword in URL_KEYWORDS):
                # article_link = soup.select_one('h1 > a')['href'] # todo get the actual link
                a_tag = article.select_one('h2.e-web-aktualne-articles-card-horizontal__title a')
                article_link = a_tag['href']
                self.articles_buffer.append(article_link)
                self.stats.saved_articles += 1
                self.logger.info(f"Saving an article with title: '{article_title}'...link: '{article_link}'...")


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
        # self.logger.debug(f"Parsed {self.stats.listings_parsed} pages, going to the next page...")
        return self.BASE_URL + next_href


    @staticmethod
    def assert_listing(bs_soup: BeautifulSoup):
        container = bs_soup.select_one('div.e-web-aktualne-articles-cards__flex')
        if not container:
            return None
        return True


    async def get_max_page(self, url=BASE_URL) -> int | None:
        # todo separate this or run concurrently
        loop_count = 0
        left = 1
        right = 14000
        while left <= right:
            loop_count += 1
            mid = (left + right) // 2
            test_url = f"{url}?page={mid}"
            self.logger.debug(f"test_url: {test_url}")
            soup = await self.get_soup(test_url)
            if self.assert_listing(soup):
                next_page = await self.get_next_page(soup)
                if next_page:
                    # Too low
                    left = mid + 1
                    self.logger.info(f"Continuing to the loop number {loop_count + 1}, current max page is {mid}....")
                    continue
                else:
                    # On target
                    self.logger.info(f"Found the final page: {mid}")
                    return mid
            if soup:
                # Too high
                right = mid - 1
                self.logger.info(f"Contiunuing to the loop number {loop_count + 1}, current max page is {mid}...")
                continue
        self.logger.error(f"Failed to find the final page, {loop_count} loops...")
        return None


    async def get_all_listings(self) -> dict[str, list]:
        # todo run this async (possibly prefetch as well)
        all_urls = {}
        input_urls = []
        with open(self.INPUT_FILE, 'r') as f:
            for line in f:
                input_urls.append(line.strip())

        for url in input_urls:
            max_page = await self.get_max_page(url)
            if max_page:
                all_urls[url] = []
                page_number = 1
                while page_number <= max_page:
                    all_urls[url].append(f"{url}?page={page_number}")
                    page_number += 1
                self.logger.info(f"Found {page_number} listings for {url}...")
        return all_urls


    async def mk_tasks(self):
        listings = await self.get_all_listings()
        return [self.get_listing_articles(url)
                for url_list in listings.values()
                for url in url_list]


    async def run(self):
        timer_start = time.perf_counter()
        self.logger.info(f"Starting the aktualne scraper...")

        archive_jobs = await self.mk_tasks()
        await self.scrape(archive_jobs) # todo process results? Prob not
        await self.write_buffer()
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

