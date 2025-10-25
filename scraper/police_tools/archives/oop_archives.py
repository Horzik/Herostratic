import asyncio
import logging
import random
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from config import POLICE_ARCHIVES_FP, POLICE_SITES_FP, LOG_DIR, ERRORS_LOG_FP
from scraper.oop_police import BaseScraper
from scraper.site_configs import BASE_POLICE_URL, POLICE_ARCHIVE_SELECTORS
from utils.logger import LogConfig, destroy


class ScrapeArchive(BaseScraper):
    SITE_NAME = 'POLICIE'
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_SITES_FP
    OUTPUT_FILE = POLICE_ARCHIVES_FP
    SEMAPHORE_COUNT = 30
    GOV_SITE = True
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
            zpr_link = urljoin(BASE_POLICE_URL, zpr_ref.get('href').lstrip('/'))
            zpravodajstvi_bytes = await self.fetch(zpr_link)
            second_soup = BeautifulSoup(zpravodajstvi_bytes, 'lxml')

            # Check if the archive is already in here
            year_links = second_soup.select('a[href*="2024"], a[href*="2023"], a[href*="2022"]')
            if len(year_links) == 3:
                self.logger.info(f"Returning:: '{zpr_link}' for url:: '{url}'")
                return municipality, zpr_link

            elif len(year_links) == 1:
                # self.logger.info(f"The year_links ref is:: {year_links}....")
                archive_link = urljoin(BASE_POLICE_URL, year_links[0].get('href'))
                self.logger.info(f"Returning:: {archive_link} for url:: '{url}'")
                return municipality, archive_link

            # Try finding the archive link here
            else:
                second_archive_element = second_soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
                self.logger.debug(f"Getting second arch ref: {second_archive_element.get('href')}")
                second_archive_link = urljoin(BASE_POLICE_URL, second_archive_element.get('href').lstrip('/'))
                if second_archive_link:
                    self.logger.info(f"Returning:: '{second_archive_link}' for url:: '{url}'")
                    return municipality, second_archive_link
        return None

    async def start_task(self, url: str):
        await asyncio.sleep(random.uniform(0.1, 0.5)) # Play nice, it is the police after all
        try:
            municipality, link = await self.parser(url)
            return municipality, link
        except Exception as e: # Catch anything we might have missed
            self.logger.exception(f"Error reading {url}::{e}")
        self.logger.warning(f"Couldn't find the archive for {url}")
        return None

    def prepare_tasks(self) -> list:
        with open(self.INPUT_FILE, 'r') as f:
            return [self.start_task(line.strip()) for line in f]

    def process_results(self, results):
        archive_dict = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception) or result is None:
                self.logger.warning(f"Warning: unknown issue occurred with a task no.${i}: {result}")
                continue
            municipality, archive_link = result
            archive_dict.setdefault(municipality, []).append(archive_link)
        return archive_dict

    async def run(self):
        results = await self.scrape()
        processed_res = self.process_results(results)
        await self.write_results(processed_res)


async def main():
    scraper = ScrapeArchive()
    try:
        await scraper.run()
    finally:
        destroy()

if __name__ == '__main__':
    asyncio.run(main())