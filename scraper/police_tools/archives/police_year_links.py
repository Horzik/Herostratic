import asyncio
import json
import logging
import time
from asyncio import gather
from bs4 import BeautifulSoup
from datetime import timedelta

from config import POLICE_ARCHIVES_FP, YEAR_LINKS_FP, LOG_DIR, ERRORS_LOG_FP
from scraper.core import BaseScraper
from scraper.police_tools.archives.municipality_strategies import MUNICIPALITY_PARSERS, MunicipalityParser
from scraper.site_configs import BASE_POLICE_URL
from utils.io_utils import atomic_json_write, CriticalDataError
from utils.logger import LogConfig, destroy


class YearLinksScraper(BaseScraper):
    MODULE_NAME = "year_links"
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_ARCHIVES_FP
    OUTPUT_FILE = YEAR_LINKS_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 10
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'year_links.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        self.validated_links = 0


    def write_results(self, data: dict | list) -> None:
        """ Wraps the 'atomic_write' func in the class lock.
        """
        try:
            atomic_json_write(data, self.OUTPUT_FILE)
        except CriticalDataError:
            raise


    @staticmethod
    def get_parser_for_municipality(municipality: str) -> type[MunicipalityParser]:
        """ Get the specific parser class for a municipality.
        """
        for key, parser_class in MUNICIPALITY_PARSERS.items():
            if key in municipality:
                return parser_class
        raise ValueError(f"No parser found for municipality: {municipality}")


    def process_archive_results(self, archive_results: list) -> tuple:
        """Process all archive results from parsing the archive pages. \n
           Return the target sites and number of failed tasks.
        """
        sites = {}
        urls_count = 0
        failed_arch_count = 0 # todo return the actual failed archives
        # Get the municipalities from tasks, check and process each result
        for result in archive_results:
            self.pages_scraped += 1
            if isinstance(result, Exception) or result is None:
                self.errors.append(f"Archive task failed: {result}")
                failed_arch_count += 1
                continue

            # Append to and return the 'sites'
            municipality, year_links = result
            if municipality not in sites:
                sites[municipality] = year_links
            else:
                for year, urls in year_links.items():
                    urls_count += len(urls)
                    sites[municipality].setdefault(year, []).extend(urls)

        self.logger.debug(f"Results:: Found {urls_count} urls across {len(sites)} sites.")
        return sites, failed_arch_count


    async def has_pagination(self, listing_url: str) -> bool:
        """Checks if the url has the page pagination element.
        """
        try:
            content = await self.fetch(listing_url, gov_site=True)
            if content is None:
                return False
            soup = BeautifulSoup(content, 'lxml')
            if soup.select_one('p.pager'):
                return True
            else:
                self.logger.error(f"Failed validating year link '{listing_url}'")
                return False
        except Exception:
            self.logger.exception(f"Unknown error while validating year links for archive '{listing_url}...'")
            raise


    async def validate_links(self, all_years: dict, url: str) -> bool:
        """Gets the content of each link and verifies it contains the article listings.
           Validation is 'all or nothing' => finding one failed link will return False.
        """
        tasks = [
            self.has_pagination(listing_url)
            for _, urls in all_years.items()
            for listing_url in urls
        ]
        results = await gather(*tasks, return_exceptions=True)

        all_validated = True
        for res in results:
            if isinstance(res, Exception):
                self.logger.error(f"Error for archive task for municipality: '{url}'...")
                self.errors.append(f"Url '{url}' was not validated and failed with exception. Task::'{res}'")
                all_validated = False
            elif res is True:
                self.validated_links += 1
            elif res is False:
                self.logger.error(f"Failed validating a link: '{url}'...")
                self.errors.append(f"Url '{url}' was not validated. Task::'{res}'")
                all_validated = False

        return all_validated


    async def parse_municipality(self, municipality: str, url: str, soup: BeautifulSoup) -> dict[str, list[str]]:
        parser_class = self.get_parser_for_municipality(municipality)
        parser = parser_class(self, municipality, url, soup, self.logger)
        return await parser.parse()


    async def parse_archive(self, arch_url: str, municipality: str) -> dict[str, list[str]] | None:
        """ Parse the archive page to return the year links.
        """
        archive_bytes = await self.fetch(arch_url, gov_site=True)
        if archive_bytes is None:
            self.logger.error(f"Failed fetching content for url '{arch_url}'...")
            return None

        soup = BeautifulSoup(archive_bytes, 'lxml')
        all_links = await self.parse_municipality(municipality, arch_url, soup)
        if not all_links:
            self.logger.error(f"No links found for municipality '{municipality}'...")
            return None

        validated = await self.validate_links(all_links, arch_url)
        if validated:
            return all_links
        else:
            self.logger.error(f"Failed to validate year links for url '{arch_url}', returning None...")
            return None



    async def get_all_links(self, arch_url: str, municipality: str) -> tuple[str, dict] | None:
        try:
            self.logger.debug(f"Parsing {municipality} for year links...")
            all_years = await self.parse_archive(arch_url, municipality)
            if all_years is None:
                self.logger.error(f"Failed parsing year links for municipality '{municipality}'/''{arch_url}...")
                return None

            self.logger.info(f"Found {len(all_years)} years in '{arch_url}'")
            return municipality, all_years
        except Exception:
            self.logger.exception(f"Exception error parsing '{arch_url}'")
            raise


    async def mk_tasks(self, data_fp) -> list:
        with open(data_fp, "r") as a:
            archives: dict = json.load(a)

        return [
            self.get_all_links(arch_url, municipality)
            for municipality, urls in archives.items()
            for arch_url in urls
        ]


    async def run(self) -> None:
        start_time = time.perf_counter()
        self.logger.info(f"Starting to scrape for archives...")
        tasks = await self.mk_tasks(self.INPUT_FILE)
        self.logger.info(f'Scraping {len(tasks)} archive links....')

        results = await gather(*tasks, return_exceptions=True)

        sites, failed_arch_count = self.process_archive_results(results)
        if sites:
            self.write_results(sites)

        duration = timedelta(seconds=time.perf_counter() - start_time)
        self.logger.info(
            f"Finished in {duration}, "
            f"success for {self.pages_scraped - failed_arch_count}/{self.pages_scraped} targets, "
            f"validated {self.validated_links} links, exiting...")


async def main() -> None:
    async with YearLinksScraper() as scr:
        try:
            await scr.run()
        finally:
            destroy()

if __name__ == '__main__':
    asyncio.run(main())
