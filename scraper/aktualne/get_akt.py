from asyncio.tasks import gather
from dataclasses import dataclass
import asyncio
import logging
import time

from aiofiles import open as aiopen
from bs4 import BeautifulSoup

from config import AKTUALNE_SITES_FP, LOG_DIR, ERRORS_LOG_FP, URL_KEYWORDS, AKT_ART_FP
from scraper.core import BaseScraper
from utils.logger import LogConfig, destroy


"""
    This module is an attempt to rewrite the original to make the async more pronounced, however
    it seems to have been proven otherwise (original seems to be about 3 times faster.
    The concept is nice and should work in theory, but whole bunch of changes
    would need to be done to make it work correctly. 
    
    --> Use "get_aktualne_articles.py"
"""

@dataclass
class ArtResults:
    saved_articles: int = 0
    articles_processed: int = 0
    listings_parsed: int = 0


class AktualneListingsScraper(BaseScraper):
    """ WIP => Goes over all available listings from 'aktualne' sites and returns valid article links """
    MODULE_NAME = 'aktualne_listings'
    BASE_URL = 'https://zpravy.aktualne.cz'
    INPUT_FILE = AKTUALNE_SITES_FP
    OUTPUT_FILE = AKT_ART_FP
    SEMAPHORE_COUNT = 20
    # GOV_SITE = True # aktualne is harsh
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'aktualne_listings.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        self.stats = ArtResults()
        self.articles_buffer = []
        self.articles_buffer_threshold = 5
        self.all_tasks_len = 0


    async def write_buffer(self):
        async with self.lock:
            async with aiopen(self.OUTPUT_FILE, 'a') as a:
                for article in self.articles_buffer:
                    await a.write(article + '\n')
                self.logger.info(f"Written the buffered links to '.../{self.OUTPUT_FILE}',"
                                 f" saved total {self.stats.saved_articles} articles")
                self.articles_buffer = [] # Reset the buffer


    async def save_article(self, article, article_title):
        a_tag = article.select_one('h2.e-web-aktualne-articles-card-horizontal__title a')
        article_link = a_tag['href']
        self.articles_buffer.append(article_link)
        self.logger.info(f"Saving article with title: '{article_title}'...link: '{article_link}'...")
        self.stats.saved_articles += 1
        if len(self.articles_buffer) >= self.articles_buffer_threshold:
            await self.write_buffer()



    async def get_listing_articles(self, url):
        # We stop the whole scraper if this fails
        soup = await self.get_soup(url)
        container = soup.select_one('div.e-web-aktualne-articles-cards__flex')
        articles_list = container.select('article')

        for article in articles_list:
            self.stats.articles_processed += 1
            if self.stats.articles_processed % 500 == 0: # Log progress every 500 articles
                self.logger.debug(f"Processed {self.stats.articles_processed} articles....")

            article_title = article.get('aria-label')
            if any(keyword in article_title for keyword in URL_KEYWORDS):
                await self.save_article(article, article_title)

        self.stats.listings_parsed += 1
        if self.stats.listings_parsed % 100 == 0: # Log progress every 100 parsed listings
            progress = self.stats.listings_parsed / self.all_tasks_len * 100 # Percentage
            self.logger.info(f"Parsed {progress:.1f}% of all tasks....")


    async def get_next_page(self, soup):
        butt = soup.select_one('a[aria-label="next"]')
        if not butt:
            self.logger.info(f"No next page found...")
            return None

        next_href = butt.get('href')
        if not next_href:
            self.logger.error(f"Found the next page button but didn't get the href, exiting...")
            return None

        return self.BASE_URL + next_href


    @staticmethod
    def assert_listing(bs_soup: BeautifulSoup):
        container = bs_soup.select_one('div.e-web-aktualne-articles-cards__flex')
        if not container:
            return None
        return True


    async def get_max_page(self, url=BASE_URL) -> int | None:
        # todo write the resulted max_pages programmatically instead of hardcoding like this
        if url == 'https://zpravy.aktualne.cz/':
            return 13353
        if url == 'https://zpravy.aktualne.cz/domaci/':
            return 3803

        left = 1
        right = 14000 # Approximate ceiling
        loop_count = 0
        while left <= right:
            loop_count += 1
            mid = (left + right) // 2
            test_url = f"{url}?page={mid}"
            self.logger.debug(f"test_url: {test_url}")
            soup = await self.get_soup(test_url)
            if self.assert_listing(soup):
                next_page = await self.get_next_page(soup)
                if next_page: # Too low
                    left = mid + 1
                    self.logger.info(f"Continuing to the loop number {loop_count + 1}, current max page is {mid}....")
                    continue
                else: # On target
                    self.logger.info(f"Found the final page: {mid}")
                    return mid
            if soup: # Too high
                right = mid - 1
                self.logger.info(f"Continuing to the loop number {loop_count + 1}, current max page is {mid}...")
                continue
        self.logger.error(f"Failed to find the final page, {loop_count} loops...")
        return None


    async def get_all_listings(self) -> dict[str, list]:
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
        self.all_tasks_len = len(archive_jobs) # Set the amount of tasks

        await gather(*archive_jobs, return_exceptions=True) # Not processing results because we do that in each task
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

