import asyncio
import logging
import random
import time
from datetime import timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from config import POLICE_ARCHIVES_FP, POLICE_SITES_FP, LOG_DIR, ERRORS_LOG_FP
from scraper.core import BaseScraper
from scraper.site_configs import BASE_POLICE_URL, POLICE_ARCHIVE_SELECTORS
from utils.logger import LogConfig, destroy


# TODO !!! => make a module that goes to BASE_URL and gets the POLICE_SITES
""" 
    Checks the input municipalities 'homepages' and returns their corresponding archive pages
    This is the first refactored module, maybe not best practices, revisit...
"""
# todo 2 ==> verify we get the correct links (can we?)
# todo 3 ==> log all processed and failed archives
class ScrapeArchive(BaseScraper):
    MODULE_NAME = 'police_archives'
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_SITES_FP
    OUTPUT_FILE = POLICE_ARCHIVES_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 30
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'police_archives.log',
        log_errors_file_path=ERRORS_LOG_FP
    )


    @staticmethod
    def get_municipality_name(municipality_element) -> str:
        if municipality_element:
            muni_name = municipality_element['alt'].strip(' název')
            # Overwrite names of some of the municipalities
            if muni_name == "Název kraj":
                muni_name = "Olomoucký kraj"
            if muni_name == "Krajské ředitelství policie kraje Vysočina":
                muni_name = "Kraj Vysočina"
            if muni_name == "Krajské ředitelství Zlk":
                muni_name = "Zlínský Kraj"
            if muni_name == "Krajské ředitelství policie Lbk":
                muni_name = "Liberecký Kraj"
        else:
            muni_name = "Informační servis"
        return muni_name.strip(" -")


    async def validate_link(self, link):
        """ Checks if the link page has a 'pager' element, if not -> validated. \n
            Not sure what (if any) better way to validate lol.
        """
        content = await self.fetch(link)
        if content is None:
            self.logger.error(f"Error while validating, content not found for: '{link}'")
            self.errors.append(link)
            self.pages_scraped += 1
            return False
        soup = BeautifulSoup(content, 'lxml')
        pager = soup.select_one('p.pager')
        if pager:
            self.logger.error(f"Failed validating archive link: '{link}'")
            self.errors.append(link)
            self.pages_scraped += 1
            return False
        else:
            self.logger.debug(f"Validated link: '{link}'")
            self.pages_scraped += 1
            return True


    async def parser(self, url):
        self.logger.info(f"Parsing link: '{url}'...")
        main_content_bytes = await self.fetch(url)
        main_soup = BeautifulSoup(main_content_bytes, 'lxml')

        # Get the municipality of this site
        municipality_element = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['municipality'])
        municipality = self.get_municipality_name(municipality_element)

        # Special cases
        if municipality in ["Informační servis", "hl. m. Praha"]:
            archive_element = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['archive_link'])
            if archive_element:
                archive_link = urljoin(BASE_POLICE_URL, archive_element.get('href'))
                if archive_link:
                    self.logger.debug(f"Returning zpr link:: '{archive_link}' for url:: '{url}'")
                    return municipality, archive_link

        # Else just get the "zpravodajství" link
        zpr_ref = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['news_link'])
        if zpr_ref:
            self.logger.debug(f"Getting zprv ref: {zpr_ref.get('href')}")
            zpr_link = urljoin(BASE_POLICE_URL, zpr_ref.get('href').lstrip('/'))
            return municipality, zpr_link

        return None


    async def process_results(self, results):
        archive_dict = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception) or result is None:
                self.logger.warning(f"Warning: Task {i} failed due to unknown issue: {result}")
                continue
            municipality, archive_link = result
            if not await self.validate_link(archive_link):
                continue
            archive_dict.setdefault(municipality, []).append(archive_link)
        return archive_dict


    def prepare_tasks(self, data_fp) -> list:
        # Return a list of coroutines
        with open(data_fp, 'r') as f:
            return [self.scrape_archive(line.strip()) for line in f]


    async def scrape_archive(self, url: str):
        await asyncio.sleep(random.uniform(0.1, 0.5)) # Play nice, it is the police after all
        try:
            municipality, link = await self.parser(url)
            return municipality, link
        except Exception as e: # Catch anything we might have missed
            self.logger.exception(f"Error reading {url}::{e}")
        self.logger.warning(f"Couldn't find the archive for {url}")
        return None


    async def run(self):
        start_time = time.perf_counter()
        self.logger.info(f'Starting {__name__}...')

        tasks = self.prepare_tasks(self.INPUT_FILE)
        results = await self.scrape(tasks)
        processed_res = await self.process_results(results)
        await self.write_results(processed_res)

        duration = timedelta(seconds=time.perf_counter() - start_time)
        self.logger.info(f"Finished in {duration}, validated {self.pages_scraped - len(self.errors)}/{self.pages_scraped} links, exiting...")


async def main():
    async with ScrapeArchive() as scr:
        # todo does the try block here make sense?
        try:
            await scr.run()
        finally:
            destroy()

if __name__ == '__main__':
    asyncio.run(main())