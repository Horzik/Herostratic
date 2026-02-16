import asyncio
import logging
import time
from asyncio import gather
from bs4 import BeautifulSoup
from datetime import timedelta, datetime
from dataclasses import dataclass, field
from typing import NamedTuple

from config import POLICE_ARTICLES_FP, URL_KEYWORDS, LOG_DIR, ERRORS_LOG_FP, YEAR_LINKS_FP
from scraper.args import ScraperArguments
from scraper.core import BaseScraper
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL
from utils.io_utils import async_json_read, atomic_json_write, CriticalDataError, read_json
from utils.logger import LogConfig, destroy


@dataclass
class ListingScrapeMetadata:
    articles: list[str] = field(default_factory=list)
    all_articles_count: int = 0
    pages_scraped: int = 0
    listing_max_pages: int = 0

class ScrapeLogData(NamedTuple):
    saved_articles: int
    failed_articles: int
    articles_processed: int
    total_pages: int

type NextUrl = str

class ListingsParser(BaseScraper):
    MODULE_NAME = "get_police_articles"
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = YEAR_LINKS_FP # Scraped from "oop_year_links" module
    OUTPUT_FILE = POLICE_ARTICLES_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 10
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_police_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )


    def __init__(self):
        super().__init__()
        self.existing_urls: set = set()


    async def _read_and_write(
        self,
        municipality: str,
        found_urls: list[str],
        year: int | str,
    ) -> None:
        """ I/O helper for the 'scrape_municipality' function. \n
            Dedupes and appends non-existing article urls.
        """
        async with self.lock:
            data = await async_json_read(POLICE_ARTICLES_FP)

        # Update the keys if needed
        year_str = str(year)
        if municipality not in data:
            data[municipality] = {}
        if year_str not in data[municipality]:
            data[municipality][year_str] = []

        found_urls = list(set(found_urls)) # Cute dedupe
        existing_results = set(data[municipality][year_str])
        new_urls = [url for url in found_urls if url not in existing_results]

        data[municipality][year_str].extend(new_urls)
        async with self.lock:
            atomic_json_write(data, POLICE_ARTICLES_FP)
            self.logger.info(f"Writing {len(found_urls)} articles from '{municipality}'/'{year}'")


    def aggregate_stats(self, article_results: list) -> ScrapeLogData:
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
        main_soup: BeautifulSoup,
        metadata: ListingScrapeMetadata,
        year: int,
        municipality,
        cron_max_pages,
    ) -> NextUrl | None:
        next_page = main_soup.select_one(POLICE_SELECTOR['pagination']['next_page'])

        if next_page:
            next_page_link = next_page['href']
            next_url = BASE_POLICE_URL + next_page_link
            metadata.pages_scraped += 1
            self.logger.debug(f"Continuing to page {metadata.pages_scraped}/{metadata.listing_max_pages if not cron_max_pages else cron_max_pages} in year {year} for: '{municipality}'")
        else:
            self.logger.info(f"No next page found, checked {metadata.all_articles_count} articles")
            self.logger.info(f"Found {len(metadata.articles)} articles from "
                             f"{metadata.pages_scraped} pages in year {year} for: {municipality}...")
            next_url = None
        return next_url


    async def parse_listing(
        self,
        url: str,
        metadata: ListingScrapeMetadata,
        municipality: str,
        year: int,
        cron_max_pages: int,
    ) -> NextUrl | None:
        """ Parse the html content of the current articles listing page. \n
            Mutates the "metadata", to which it appends the URL of articles we want, as well as some stats.
            Returns the url for the next page to parse, if "None" (ie no more pages) then the scraper stops.
        """
        soup = await self.get_soup(url)

        # Try getting the amount of pages of this listing, runs only once
        if metadata.listing_max_pages == 0:
            max_pages_el = soup.select(POLICE_SELECTOR['listing_selectors']['last_page'])
            metadata.listing_max_pages = int(max_pages_el[0].text) if max_pages_el else '80085'

        # Select the element which contains all the articles on this listing page
        article_list = soup.select(POLICE_SELECTOR['listing_selectors']['article_selector'])
        if not article_list:
            self.logger.error(f"Failed getting the article list element, '{municipality}'//'{url}', check the html.")
            return None

        # Loop over each article, if we get a match -> save it
        for article in article_list:
            link_el = article.select_one(POLICE_SELECTOR['listing_selectors']['article_link']) # If this select fails just crash
            article_link = BASE_POLICE_URL + link_el['href']
            metadata.all_articles_count += 1
            # Check existing results and a keyword match
            if article_link not in self.existing_urls and any (keyword in article_link for keyword in URL_KEYWORDS):
                metadata.articles.append(article_link)
                self.logger.info(f"Found an article...:'{article_link}'")

        # Return the next page link, which will change the 'new_url' in 'scrape_municipality' to continue the loop
        return self.get_next_page(soup, metadata, year, municipality, cron_max_pages)


    async def scrape_municipality(
        self,
        url: str,
        year: int | str,
        municipality: str,
        cron_max_pages: int | None = None
    ):
        """Scrape one municipality for all article links coroutine.
           Stores found urls in "art_data" then writes them all at the end.
        """
        art_data = ListingScrapeMetadata()
        new_url = url
        try:
            # Keep changing the 'new_url' until None
            while new_url:
                # For cron, we scrape only the required amount of pages
                if cron_max_pages is not None and art_data.pages_scraped >= cron_max_pages:
                    self.logger.info(f"Finished scraping the required cron job pages...")
                    break
                new_url = await self.parse_listing(new_url, art_data, municipality, year, cron_max_pages)

            # Write any saved articles, return the metadata about the scraper
            if len(art_data.articles) > 0:
                await self._read_and_write(municipality, art_data.articles, year)
            return len(art_data.articles), art_data.pages_scraped, art_data.all_articles_count
        except CriticalDataError: # Raise writing error
            raise
        except Exception as e: # Catch any generic error
            self.logger.error(f" {municipality}/{year} failed for '{new_url}'...Error ===>")
            self.logger.exception(e)
        return None


    def mk_full_coros(self, archives):
        """ Returns coroutines to scrape all archive pages from the INPUT_FILE.
        """
        article_scrape_coros = [
            self.scrape_municipality(url, year, municipality)
            for municipality, years in archives.items()
            for year, urls in years.items()
            for url in (urls if isinstance(urls, list) else [urls])  # Make single urls into a list
        ]

        return article_scrape_coros


    def mk_cron_coros(self, archives, cron_max_pages: int):
        """Makes coros and defines what a "year" is."""
        current_year = str(datetime.now().year)
        article_scrape_coros = [
            self.scrape_municipality(url, year, municipality, cron_max_pages)
            for municipality, years in archives.items()
            for year, urls in years.items() if (year == current_year or year == "non_years")
            for url in (urls if isinstance(urls, list) else [urls])  # Has to be a list
        ]

        return article_scrape_coros


    async def set_existing_urls(self):
        """Used for deduping tasks."""
        initial_results_urls = set()
        results_dict = await async_json_read(self.OUTPUT_FILE)
        for domain, years in results_dict.items():
            for year, articles in years.items():
                for article in articles:
                    initial_results_urls.add(article)

        # self.logger.info(f"Initial results urls: {len(initial_results_urls)}")
        self.existing_urls = initial_results_urls
        return initial_results_urls


    async def scrape(self, cron_max_pages: int | None) -> bool:
        """Main orchestrator, runs archive jobs (to get year links of archives), then the article jobs (to get article urls).
        """

        # Keep a ref for the Return
        pre_scrape_parsed_arts = await self.set_existing_urls()
        if cron_max_pages:
            self.logger.info(f"Running '{self.MODULE_NAME}' in CRON mode, pages to check: {cron_max_pages}.")

        archives: dict = read_json(self.INPUT_FILE)
        article_scrape_coros = self.mk_cron_coros(archives, cron_max_pages) if cron_max_pages else self.mk_full_coros(archives)
        self.logger.info(f"Scraping {len(article_scrape_coros)} tasks...")
        results = await gather(*[coro for coro in article_scrape_coros], return_exceptions=True)

        # Process the results and aggregate the stats for logs
        logs: ScrapeLogData = self.aggregate_stats(results)
        (saved_articles, failed_articles, articles_processed, total_pages) = logs
        self.logger.info(f"Processed {articles_processed} articles from {total_pages} pages, saved {saved_articles}, failed {failed_articles}")

        # Return true if we found any new articles
        post_scrape_parse_arts = await self.set_existing_urls()
        found_new_articles = len(pre_scrape_parsed_arts) != len(post_scrape_parse_arts)
        return found_new_articles


async def get_police_articles(cron_max_pages: int | None = None):
    async with ListingsParser() as ap:
        start = time.perf_counter()
        try:
            found_new_articles = await ap.scrape(cron_max_pages)
            ap.logger.info(f"Finished scraping in {str(timedelta(seconds=time.perf_counter() - start))}. Exiting...")
            return found_new_articles
        finally:
            destroy()


if __name__ == "__main__":
    # Arguments for the cron job pipeline
    args = ScraperArguments().init_argparse().parse_args()
    print(f"Args:: {args}")
    run_as_cron = bool(args.cron)

    # How many pages of article listings should the scraper check, default to 5 if a cron job
    max_pages = args.max_pages if args.max_pages else (5 if run_as_cron else None)
    asyncio.run(get_police_articles(cron_max_pages=max_pages))
