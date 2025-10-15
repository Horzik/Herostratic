import asyncio
import json
import logging
import random
import aiofiles
import aiohttp
from typing import Tuple
from bs4 import BeautifulSoup

from utils.logger import destroy, LogConfig, init_logging, get_logger
from utils.network_utils import get_bytes, create_session
from config import POLICE_ARCHIVES_FP, POLICE_SITES_FP, LOG_DIR, ERRORS_LOG_FP
from scraper.site_configs import POLICE_ARCHIVE_SELECTORS, BASE_POLICE_URL


config = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_popo_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )
init_logging(config)
logger = get_logger()

def load_target_sites() -> list:
    with open(POLICE_SITES_FP, "r") as p:
        sites = []
        for line in p:
            line = line.strip().strip("',")
            if line:
                sites.append(line)
    return sites


# Check if a target page has a sitemap, save it and write the resto to "NOSITEMAPS"
async def get_police_archives(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> Tuple[str, str] | None:
    await asyncio.sleep(random.uniform(2, 5))
    try:
        main_content_bytes = await get_bytes(url, session, semaphore, gov_site=True)
        main_soup = BeautifulSoup(main_content_bytes, 'lxml')

        # Get the police municipality for this archive
        municipality_element = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['municipality'])
        if municipality_element:
            municipality = municipality_element['alt'].strip(' název')
        else:
            logger.warning("Error, no municipality element")
            municipality = ''

        # If we get archive link => win, return
        archive_element = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['archive_link'])
        if archive_element:
            logger.info(f"Getting ref: {archive_element.get('href')}")
            archive_link = BASE_POLICE_URL + archive_element.get('href').lstrip('/')
            if archive_link:
                logger.info(f"Got a direct link for {url}")
                return municipality, archive_link

        # Else it's harder, go to the "zpravodajstvi" link
        zpr_ref = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['news_link'])
        if zpr_ref:
            logger.info(f"Getting zprv ref: {zpr_ref.get('href')}")
            zpr_link = BASE_POLICE_URL + zpr_ref.get('href').lstrip('/')
            zpravodajstvi_bytes = await get_bytes(zpr_link, session, semaphore)
            second_soup = BeautifulSoup(zpravodajstvi_bytes, 'lxml')

            # Check if the archive is already in here
            year_links = second_soup.select('a[href*="2024"], a[href*="2023"], a[href*="2022"]')
            if year_links:
                logger.info(f"Got a nested link for {url}")
                return municipality, zpr_link

            # Else, try finding the archive link here
            else:
                second_archive_element = second_soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
                logger.info(f"Getting second arch ref: {second_archive_element.get('href')}")
                second_archive_link = BASE_POLICE_URL + second_archive_element.get('href').lstrip('/')
                if second_archive_link:
                    logger.info(f"Got a double nested link for {url}")
                    return municipality, second_archive_link

    except Exception as e:
        logger.error(f"Error reading {url}::")
        logger.error(e)

    # Else no link
    logger.warning(f"Couldn't find the archive for {url}")
    return None


async def scraper():
    # Load the police sites
    sites = load_target_sites()

    # Open the session with the context manager
    semaphore = asyncio.Semaphore(3)
    async with create_session() as session:

        # Get the tasks and await for results
        archive_tasks = [
            get_police_archives(url, session, semaphore)
            for url in sites
        ]
        results = await asyncio.gather(*archive_tasks, return_exceptions=True)

        # Place each link to their respective municipalities
        archive_dict = {}
        for result in results:
            if isinstance(result, Exception) or result is None:
                logger.warning(f"Warning: unknown issue occurred when parsing results: {result}")
                continue

            municipality, archive_link = result
            if municipality not in archive_dict:
                archive_dict[municipality] = [archive_link]
            else:
                archive_dict[municipality].append(archive_link)

        logger.info(f"Finished all tasks, "
                    f"found {len(archive_dict)}/{len(sites)} archive links, "
                    f"exiting....")

    async with aiofiles.open(POLICE_ARCHIVES_FP, "w", encoding='utf-8') as p:
        await p.write(json.dumps(archive_dict, indent=2, ensure_ascii=False))


def main():
    try:
        asyncio.run(scraper())
    finally:
        destroy() # Kill the log handlers

if __name__ == "__main__":
    main()