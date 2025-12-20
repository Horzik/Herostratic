from asyncio.tasks import gather
from dataclasses import dataclass
from datetime import timedelta
import asyncio
import logging
import time
import aiofiles

from config import LOG_DIR, ERRORS_LOG_FP, DISTRICTS_FP, METRO_ARTICLES_FP, URL_KEYWORDS
from scraper.core import BaseScraper
from utils.io_utils import atomic_json_write, CriticalDataError, async_json_read
from utils.logger import LogConfig, destroy
from utils.other_utils import normalize_text


""" 
     Metro Scraper
        |    |
        |\  /|
        | \/ |
    .___|    |___.
    |            |
     |          |
      |        |
       |      |
        |    |
         ||||
          ""
"""

@dataclass
class MetroStats:
    pages_scraped: int = 0
    total_articles: int = 0
    saved_articles: int = 0

class ScrapeMetroArticles(BaseScraper):
    MODULE_NAME = 'metro_articles'
    BASE_URL = 'https://metro.cz'
    INPUT_FILE = DISTRICTS_FP # From utils "get_czechia_districts" script, only the paths (needs base url)
    OUTPUT_FILE = METRO_ARTICLES_FP
    GOV_SITE = False
    SEMAPHORE_COUNT = 10
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'metro_articles.log',
        log_errors_file_path=ERRORS_LOG_FP)


    def __init__(self):
        super().__init__()
        self.stats = MetroStats()
        self.articles_buffer = {}
        self.articles_buffer_threshold = 10
        self.custom_input = [
                ('https://www.metro.cz/praha', 'Hlavni Mesto Praha'),
                ('https://www.metro.cz/spolecnost', 'Spolecnost')]


    @staticmethod
    def find_keyword(url: str, description: str):
        for word in url.split():
            if any(keyword in word for keyword in URL_KEYWORDS):
                return True
        for word in description.split():
            if any(keyword in word for keyword in URL_KEYWORDS):
                return True
        return False


    async def flush_buffer(self) -> None:
        """ Add the buffer articles to the existing output file.
        """
        self.logger.debug(f"Flushing the buffer...")
        try:
            results = await async_json_read(self.OUTPUT_FILE)
            for region, articles in self.articles_buffer.items():
                results.setdefault(region, []).extend(articles)

            atomic_json_write(results, self.OUTPUT_FILE)

            self.articles_buffer.clear()
            self.logger.info(f"Flushed {self.stats.saved_articles} articles....")
        except CriticalDataError:
            raise


    def mk_metro_path(self, region: str) -> tuple[str, str]:
        """ We get regions from utils 'get_czechia_districts', because metro.cz has them in JS. \n
            :param region: In the format of "district(municipality)"
            :type: region str
            :return: [link, region_name]
            :rtype: tuple[str, str]
        """
        muni = region.split('(')[1].rstrip(')')
        dist = region.split('(')[0]
        municipality = muni.replace(' ', '-').lower()
        district = dist.replace(' ', '-').lower()

        # Return both the path AND the Region/District
        path = '/kraje/' + normalize_text(municipality) + "/" + normalize_text(district)
        tup = (self.BASE_URL + path, municipality + "/" + district)
        return tup


    async def next_page(self, url: str) -> str | None:
        soup = await self.get_soup(url)
        el = soup.select_one('a.ico-right') # 'next page'
        link = el.get('href') if el else None
        return link


    def find_articles(self, listings_element, region: str) -> dict:
        article_links = {}
        for art in listings_element:
            a_tag = art.select_one('a.art-link')
            art_url = a_tag.get('href')
            description = art.select_one('p').text

            if self.find_keyword(art_url, description):
                article_links.setdefault(region, []).append(art_url)
                self.logger.debug(f"Found a matching article:: '{art_url}'...'")
                self.stats.saved_articles += 1

            self.stats.total_articles += 1
            if self.stats.total_articles % 100 == 0:
                self.logger.debug(f"Checked {self.stats.total_articles} articles")

        return article_links


    async def parse_listing(self, url: str, region: str) -> dict | None:
        soup = await self.get_soup(url)
        if not soup:
            self.logger.error(f"Error getting the soup for url: '{url}'....")
            self.errors.append(url)
            return None

        listings_el = soup.select('div#content div.col-a div.art')
        if not listings_el:
            self.logger.error(f"Error getting listings_el element for url: '{url}'....")
            self.errors.append(url)
            return None

        article_links = self.find_articles(listings_el, region)
        self.stats.pages_scraped += 1
        return article_links


    async def scrape_district(self, url: str, region: str) -> None:
        district_page_count = 0
        new_url = url
        while new_url:
            found_articles = await self.parse_listing(new_url, region)
            if found_articles:
                async with self.lock:
                    # Check if buffer needs writing
                    arts_buff_len = sum(len(articles) for articles in self.articles_buffer.values())
                    if arts_buff_len >= self.articles_buffer_threshold:
                        await self.flush_buffer()
                    # Add articles to the buffer
                    for region, urls in found_articles.items():
                        self.articles_buffer.setdefault(region, []).extend(urls)
                    district_page_count += 1

            # Continue the loop until None...
            new_url = await self.next_page(new_url)
        self.logger.info(f"Finished scraping '{region}' with {district_page_count} pages...")


    async def prepare_tasks(self, custom=False) -> list | None:
        tasks = []
        if not custom:
            try:
                async with aiofiles.open(self.INPUT_FILE, 'r') as a:
                    lines = await a.readlines()
                    for district in lines:
                        home_url, region = self.mk_metro_path(district.strip())
                        tasks.append(self.scrape_district(home_url, region))
            except FileNotFoundError:
                self.logger.error(f"File {self.INPUT_FILE} not found, exiting...")
                raise FileNotFoundError
        else:
            # NOTE: Use this for scraping custom paths (link, custom_name)
            for task in self.custom_input:
                url, region = task
                tasks.append(self.scrape_district(url, region))

        return tasks


    async def run(self):
        self.logger.info(f'Starting scraper:: {__name__}...')
        start_time = time.perf_counter()

        tasks = await self.prepare_tasks()
        self.logger.debug(f"{len(tasks)} jobs in queue...")
        await gather(*tasks, return_exceptions=True)

        # Write the remaining buffer
        if self.articles_buffer:
            await self.flush_buffer()

        # todo use this as/in a class?
        duration = timedelta(seconds=time.perf_counter() - start_time)
        self.logger.info(f"""
            === SCRAPING COMPLETE ===
            Finished in {duration}s
            Errors occurred: {len(self.errors)}
            Total articles found: {self.stats.total_articles}
            Saved articles: {self.stats.saved_articles}
            Pages parsed: {self.stats.pages_scraped}
            """)
        self.logger.error(f"Errors occurred during scraping:: {self.errors}")
        self.logger.info(f"Exiting...")
        return


async def main():
    async with ScrapeMetroArticles() as sma:
        try:
            await sma.run()
        finally:
            destroy()


if __name__ == '__main__':
    asyncio.run(main())
