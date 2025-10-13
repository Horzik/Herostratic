import asyncio
import json
import random
import aiofiles
import aiohttp
from typing import Tuple
from bs4 import BeautifulSoup

from utils.network_utils import get_bytes, create_session
from config import POLICE_ARCHIVES_FP, POLICE_SITES_FP
from scraper.site_configs import POLICE_ARCHIVE_SELECTORS, BASE_POLICE_URL


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
        main_content_bytes = await get_bytes(url, session, semaphore)
        main_soup = BeautifulSoup(main_content_bytes, 'lxml')

        # Get the police municipality for this archive
        municipality_element = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['municipality'])
        if municipality_element:
            municipality = municipality_element['alt'].strip(' název')
        else:
            print("Error, no municipality element")
            municipality = ''

        # If we get archive link => win, return
        archive_ref = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['archive_link'])
        if archive_ref:
            print(f"Getting ref: {archive_ref.get('href')}")
            archive_link = BASE_POLICE_URL + archive_ref.get('href').lstrip('/')
            if archive_link:
                print(f"Got a direct link for {url}")
                return municipality, archive_link

        # Else it's harder, go to the "zpravodajstvi" link
        zpr_ref = main_soup.select_one(POLICE_ARCHIVE_SELECTORS['news_link'])
        if zpr_ref:
            print(f"Getting zprv ref: {zpr_ref.get('href')}")
            zpr_link = BASE_POLICE_URL + zpr_ref.get('href').lstrip('/')
            zpravodajstvi_bytes = await get_bytes(zpr_link, session, semaphore)
            second_soup = BeautifulSoup(zpravodajstvi_bytes, 'lxml')

            # Check if the archive is already in here
            year_links = second_soup.select('a[href*="2024"], a[href*="2023"], a[href*="2022"]')
            if year_links:
                print(f"Got a nested link for {url}")
                return municipality, zpr_link

            # Else, try finding the archive link here
            else:
                second_archive_ref = second_soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
                print(f"Getting second arch ref: {second_archive_ref.get('href')}")
                second_archive_link = BASE_POLICE_URL + second_archive_ref.get('href').lstrip('/')
                if second_archive_link:
                    print(f"Got a double nested link for {url}")
                    return municipality, second_archive_link

    # Catch some errors
    except aiohttp.ClientConnectionError as e:
        print(f"Connection error for {url}:: {e}")
    except asyncio.TimeoutError as e:
        print(f"Timeout for {url}:: {e}")
    except aiohttp.ClientError as e:
        print(f"HTTPError for {url}:: {e}")
    except Exception as e:
        print(f"Error reading {url}::")
        print(e)

    # Else no link
    print(f"Couldn't find the archive for {url}")
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
                print(f"Some error occurred: {result}")
                continue

            municipality, archive_link = result
            if municipality not in archive_dict:
                archive_dict[municipality] = [ archive_link]
            else:
                archive_dict[municipality].append(archive_link)

        print(f"Finished all tasks.")
        print(f"Found {len(archive_dict)}/{len(sites)} links.")
        print(f"Exiting...")

    async with aiofiles.open(POLICE_ARCHIVES_FP, "w", encoding='utf-8') as p:
        await p.write(json.dumps(archive_dict, indent=2, ensure_ascii=False))


def main():
    asyncio.run(scraper())


if __name__ == "__main__":
    main()