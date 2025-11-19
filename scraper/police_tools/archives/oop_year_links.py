import asyncio
import json
import logging
import time
from asyncio import gather
from datetime import timedelta
from bs4 import BeautifulSoup

from scraper.core import BaseScraper
from scraper.police_tools.archives.municipality_strategies import MUNICIPALITY_PARSERS, MunicipalityParser
from utils.logger import LogConfig, destroy
from scraper.site_configs import BASE_POLICE_URL
from config import POLICE_ARCHIVES_FP, YEAR_LINKS_FP, LOG_DIR, ERRORS_LOG_FP


# TODO self.errors is not being used
# TODO validation is not ideal, one failed link will fail the whole municipality
# TODO try making the logging somewhat better
class YearLinksScraper(BaseScraper):
    MODULE_NAME = "year_links"
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_ARCHIVES_FP
    OUTPUT_FILE = YEAR_LINKS_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 30
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'year_links.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        self.validated_links = 0


    @staticmethod
    def _get_parser_for_municipality(municipality: str) -> type[MunicipalityParser]:
        """Get parser class for municipality, raises if not found"""
        for key, parser_class in MUNICIPALITY_PARSERS.items():
            if key in municipality:
                return parser_class
        raise ValueError(f"No parser found for municipality: {municipality}")


    def process_archive_results(self, archive_jobs: list, archive_results: list) -> tuple:
        """ Process all archive results from parsing the archive pages. \n
            Return the target sites and number of failed tasks.
        """
        sites = {}
        failed_archives = 0 # todo return the actual failed archives (or use the self.errors?)
        # Get the municipalities from tasks, check and process each result
        for (municipality, coro), arch_result in zip(archive_jobs, archive_results):
            if isinstance(arch_result, Exception) or arch_result is None:
                self.logger.error(f"Error getting archive task for municipality: '{municipality}'...")
                self.logger.error(f"Task '{type(arch_result).__name__}', result:: {arch_result}")
                self.errors.append(f"municipality '{municipality}' failed. Task::'{coro}'. Result:: '{arch_result}'")
                self.pages_scraped += 1
                failed_archives += 1
                continue

            municipality, year_links = arch_result
            if municipality not in sites:
                sites[municipality] = year_links
            else: # Extend the municipality
                for year, urls in year_links.items():
                    sites[municipality].setdefault(year, []).extend(urls)
            self.pages_scraped += 1

        self.logger.debug(f"Results:: Found {len(sites)} sites:: {sites}")
        return sites, failed_archives


    async def validate_single_link(self, listing_url: str) -> bool:
        try:
            content = await self.fetch(listing_url, gov_site=True)
            if content is None:
                return False

            soup = BeautifulSoup(content, 'lxml')
            if soup.select_one('p.pager'): # Pagination means we have the listing
                return True
            else:
                self.logger.error(f"Failed validating year link '{listing_url}'")
                return False
        except Exception:
            self.logger.exception(f"Unknown error while validating year links for archive '{listing_url}...'")
            raise


    async def validate_links(self, all_years: dict, url: str) -> bool:
        """ Gets the content of each link and verifies it contains the article listings. """
        tasks = [
            self.validate_single_link(listing_url)
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


    async def parse_municipality(self, municipality, url, soup) -> dict[str, list[str]]:
        parser_class = self._get_parser_for_municipality(municipality)
        parser = parser_class(self, municipality, url, soup, self.logger)
        return await parser.parse()


    async def parse_archive(self, arch_url: str, municipality: str) -> dict[str, list[str]] | None:
        """ Parse the archive page to return the year links.  """
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
            self.logger.debug(f"Success validating year links for url '{arch_url}'...")
        else:
            self.logger.error(f"Failed to validate year links for url '{arch_url}', returning None...")
            return None

        return all_links


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


    async def prepare_tasks(self, data_fp) -> list:
        with open(data_fp, "r") as a:
            archives: dict = json.load(a)
        return [
            (municipality, self.get_all_links(arch_url, municipality))
            for municipality, urls in archives.items()
            for arch_url in urls
        ]


    async def scrape(self, tasks) -> list:
        """ Override the class 'scrape' because we are adding the 'municipality' to tasks. """
        return await gather(*[coro for _, coro in tasks],
            return_exceptions=True
        )


    async def run(self) -> None:
        start_time = time.perf_counter()
        self.logger.info(f"Starting to scrape for archives...")
        tasks = await self.prepare_tasks(self.INPUT_FILE)
        self.logger.info(f'Scraping {len(tasks)} archive links....')

        results = await self.scrape(tasks)
        sites, failed_arch_count = self.process_archive_results(tasks, results)
        if failed_arch_count < len(sites):
            await self.write_results(sites)

        duration = timedelta(seconds=time.perf_counter() - start_time)
        self.logger.info(
            f"Finished in {duration}, "
            f"success for {self.pages_scraped - failed_arch_count}/{self.pages_scraped} targets, "
            f"validated {self.validated_links} links, exiting...") # todo this can be misleading if any muni fails


async def main() -> None:
    async with YearLinksScraper() as scr:
        try:
            await scr.run()
        finally:
            destroy()


if __name__ == '__main__':
    asyncio.run(main())