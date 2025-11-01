import asyncio
import logging
import random
import time
from datetime import timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from config import POLICE_ARCHIVES_FP, POLICE_SITES_FP, LOG_DIR, ERRORS_LOG_FP
from scraper.oop_police import BaseScraper
from scraper.site_configs import BASE_POLICE_URL, POLICE_ARCHIVE_SELECTORS
from utils.logger import LogConfig, destroy

# TODO this does NOT parse all archives correctly ==> ZLK and VYS are returning wrong links (not the ones with year links)
class ScrapeArchive(BaseScraper):
    SITE_NAME = 'popo_archives'
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_SITES_FP
    OUTPUT_FILE = POLICE_ARCHIVES_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 30
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_oop_archives.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    async def parser(self, url):
        main_content_bytes = await self.fetch(url)
        main_soup = BeautifulSoup(main_content_bytes, 'lxml')

        # Get the police municipality for this archive
        municipality_element = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['municipality'])
        if municipality_element:
            municipality = municipality_element['alt'].strip(' název')
        else:
            self.logger.warning(f'Error, no municipality element for url {url}')
            municipality = ''

        # If we get archive link => win, return
        archive_element = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['archive_link'])
        if archive_element:
            self.logger.debug(f"Getting ref: {archive_element.get('href')}")
            archive_link = urljoin(BASE_POLICE_URL, archive_element.get('href'))
            if archive_link:
                self.logger.info(f"Returning:: '{archive_link}' for url:: '{url}'")
                return municipality, archive_link

        # Else it's harder, go to the "zpravodajstvi" link
        zpr_ref = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['news_link'])
        if zpr_ref:
            self.logger.debug(f"Getting zprv ref: {zpr_ref.get('href')}")
            # Check if the archive links are in here
            zpr_link = urljoin(BASE_POLICE_URL, zpr_ref.get('href').lstrip('/'))
            zpravodajstvi_bytes = await self.fetch(zpr_link)
            second_soup = BeautifulSoup(zpravodajstvi_bytes, 'lxml')
            year_links = second_soup.select('a[href*="2024"], a[href*="2023"], a[href*="2022"]')

            if len(year_links) == 3:
                self.logger.info(f"Returning:: '{zpr_link}' for url:: '{url}'")
                return municipality, zpr_link
            elif len(year_links) == 1:
                archive_link = urljoin(BASE_POLICE_URL, year_links[0].get('href'))
                self.logger.info(f"Returning:: {archive_link} for url:: '{url}'")
                return municipality, archive_link
            else:
                # Last change, try finding the archive link over there (we love the police)
                second_archive_element = second_soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
                self.logger.debug(f"Getting second arch ref: {second_archive_element.get('href')}")
                second_archive_link = urljoin(BASE_POLICE_URL, second_archive_element.get('href').lstrip('/'))
                if second_archive_link:
                    self.logger.info(f"Returning:: '{second_archive_link}' for url:: '{url}'")
                    return municipality, second_archive_link
        return None

    def process_results(self, results):
        archive_dict = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception) or result is None:
                self.logger.warning(f"Warning: Task {i} failed due to unknown issue: {result}")
                continue
            municipality, archive_link = result
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
        processed_res = self.process_results(results)
        await self.write_results(processed_res)

        duration = timedelta(seconds=time.perf_counter() - start_time)
        self.logger.info(f"Finished in {duration}, exiting...")

async def main():
    async with ScrapeArchive() as scr:
        try:
            await scr.run()
        finally:
            destroy()

if __name__ == '__main__':
    asyncio.run(main())