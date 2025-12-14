import asyncio
from dataclasses import dataclass, field
from typing import NamedTuple

from config import POLICE_ARTICLES_FP, URL_KEYWORDS, LOG_DIR, ERRORS_LOG_FP, YEAR_LINKS_FP
from scraper.core import BaseScraper
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL
from utils.io_utils import async_json_read, atomic_json_write, CriticalDataError
from utils.logger import LogConfig, destroy

from asyncio import gather
from datetime import timedelta
from bs4 import BeautifulSoup
import logging
import time


@dataclass
class ListingScrapeMetadata:
    articles: list[str] = field(default_factory=list)
    all_articles_count: int = 0
    pages_scraped: int = 0
    max_pages: int = 0

class ScrapeLogData(NamedTuple):
    saved_articles: int
    failed_articles: int
    articles_processed: int
    total_pages: int

type NextUrl = str


class ListingsParser(BaseScraper):
    MODULE_NAME = "get_police_articles"
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = YEAR_LINKS_FP
    OUTPUT_FILE = POLICE_ARTICLES_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 10
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.INFO,
        log_file_path=LOG_DIR / 'get_police_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )


    async def _read_and_write(
        self,
        municipality: str,
        articles: list[str],
        year: int | str,
    ) -> None:
        """ I/O helper for the 'scrape_municipality' function. \n
            Dedupes and appends non-existing article urls.
        """
        async with self.lock:
            data = await async_json_read(POLICE_ARTICLES_FP)

        # Prepare the keys
        year_str = str(year)
        if municipality not in data:
            data[municipality] = {}
        if year_str not in data[municipality]:
            data[municipality][year_str] = []

        # Append the results
        articles = list(set(articles))  # Dedupe current scrape
        existing_urls = set(data[municipality][year_str])  # What's already saved
        new_urls = [url for url in articles if url not in existing_urls]
        data[municipality][year_str].extend(new_urls)

        async with self.lock:
            atomic_json_write(data, POLICE_ARTICLES_FP)
            self.logger.info(f"Writing {len(articles)} articles from '{municipality}'/'{year}'")


    def process_article_results(self, article_results: list) -> ScrapeLogData:
        """ Process all the article results from parsing the listings pages.
            Aggregate and return their stats.
        """
        saved_articles = 0
        failed_articles = 0
        articles_processed = 0
        total_pages = 0

        for i, result in enumerate(article_results):
            if isinstance(result, Exception) or result is None:
                self.logger.error(f"Police scraping task {i} failed with exception: {result}")
                failed_articles += 1
                continue
            articles, pages, all_articles = result
            saved_articles += articles
            articles_processed += all_articles
            total_pages += pages

        return ScrapeLogData(saved_articles, failed_articles, articles_processed, total_pages)

    def get_next_page(
        self,
        main_soup,
        metadata,
        year,
        municipality,
        url
    ) -> NextUrl | None:
        next_page = main_soup.select_one(POLICE_SELECTOR['pagination']['next_page'])
        if next_page:
            next_page_link = next_page['href']
            next_url = BASE_POLICE_URL + next_page_link
            metadata.pages_scraped += 1
            self.logger.debug(f"Current url: {url}")
            self.logger.debug(f"Continuing to page {metadata.pages_scraped}/{metadata.max_pages} "
                             f"in year {year} for: '{municipality}'")
        else:
            self.logger.info(f"No next page found, checked {metadata.all_articles_count} articles")
            self.logger.info(f"Found {len(metadata.articles)} articles from "
                             f"{metadata.pages_scraped} pages in year {year} for: {municipality}...")
            next_url = None

        return next_url

    def parse_listing(
        self,
        url: str,
        page_bytes: bytes,
        metadata: ListingScrapeMetadata,
        municipality: str,
        year: int
    ) -> NextUrl | None:
        """ Parse the html content of the current articles listing page """
        main_soup = BeautifulSoup(page_bytes, 'lxml')

        if metadata.max_pages == 0:
            max_pages_el = main_soup.select(POLICE_SELECTOR['listing_selectors']['last_page'])
            metadata.max_pages = int(max_pages_el[0].text) if max_pages_el else '80085'

        article_list = main_soup.select(POLICE_SELECTOR['listing_selectors']['article_selector'])
        if not article_list:
            self.logger.error(f"Failed getting the article list element, '{municipality}'//'{url}', check the html.")
            return None

        for article in article_list:
            # This should never fail, if it does let it crash
            link_el = article.select_one(POLICE_SELECTOR['listing_selectors']['article_link'])
            article_link = link_el['href']
            metadata.all_articles_count += 1
            if any(keyword in article_link for keyword in URL_KEYWORDS):
                metadata.articles.append(BASE_POLICE_URL + article_link)
                self.logger.info(f"Success scraping article...:'{article_link}'")

        # Get the next page link and change 'current_url' to continue the loop
        return self.get_next_page(main_soup, metadata, year, municipality, url)


    async def scrape_municipality(
        self,
        url: str,
        year: int | str,
        municipality: str
    ):
        """ Scrape the municipality for article links, write its results."""
        metadata = ListingScrapeMetadata()
        new_url = url
        try:
            while new_url:
                page_bytes = await self.fetch(url=new_url, gov_site=True)
                new_url = self.parse_listing(new_url, page_bytes, metadata, municipality, year)

            if len(metadata.articles) > 0:
                await self._read_and_write(municipality, metadata.articles, year)
            return len(metadata.articles), metadata.pages_scraped, metadata.all_articles_count

        except CriticalDataError: # Re-raise writing error
            raise
        except Exception as e: # Catch any generic error
            self.logger.error(f" {municipality}/{year} FAILED for '{new_url}'...Error ===>")
            self.logger.exception(e)
        return None


    async def scrape(self) -> ScrapeLogData:
        archives: dict = await async_json_read(self.INPUT_FILE)
        article_jobs = [
            ((municipality, year), self.scrape_municipality(url, year, municipality)) # Pair metadata with a coroutine to process them together
            for municipality, years in archives.items()
            for year, urls in years.items()
            for url in (urls if isinstance(urls, list) else [urls]) # Make single urls into a list
        ]

        self.logger.info(f"Scraping {len(article_jobs)} tasks...")
        results = await gather(*[coro for _, coro in article_jobs], return_exceptions=True)
        logs: ScrapeLogData = self.process_article_results(results)
        return logs


    async def run(self):
        """Main orchestrator, runs archive jobs (to get year links of archives), then the article jobs (to get article urls)."""
        timer_start = time.time()
        saved_articles, failed_articles, articles_processed, total_pages = await self.scrape()
        timer_end = time.time()
        formatted_time = str(timedelta(seconds=timer_end - timer_start))

        self.logger.info(f"Finished scraping in {formatted_time}")
        self.logger.info(f"Processed {articles_processed} articles from {total_pages} pages, saved {saved_articles}, failed {failed_articles}")
        self.logger.info(f"Exiting...")
        exit(0)


async def main():
    async with ListingsParser() as ap:
        try:
            await ap.run()
        finally:
            destroy()


if __name__ == "__main__":
    asyncio.run(main())
