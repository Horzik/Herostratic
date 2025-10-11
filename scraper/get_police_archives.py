import asyncio
import json
import random

import aiohttp
from bs4 import BeautifulSoup
from utils.network_utils import get_bytes

from config import POLICE_ARCHIVES_FP, BASE_POLICE_URL, POLICE_SITES_FP
from scraper.site_configs import GET_ARCHIVE_SITE_CONFIGS


# Check if a target page has a sitemap, save it and write the resto to "NOSITEMAPS"
async def get_police_archives(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore):
    await asyncio.sleep(random.uniform(2, 5))
    try:
        main_content_bytes = await get_bytes(url, session, semaphore)
        main_soup = BeautifulSoup(main_content_bytes, 'lxml')

        # If we get archive link => win, return
        archive_ref = main_soup.select_one(GET_ARCHIVE_SITE_CONFIGS['archive_link'])
        if archive_ref:
            print(f"Getting ref: {archive_ref.get('href')}")
            archive_link = BASE_POLICE_URL + archive_ref.get('href').lstrip('/')
            if archive_link:
                print(f"Got a direct link for {url}")
                return archive_link

        # Else it's harder, go to the "zpravodajstvi" link
        zpr_ref = main_soup.select_one(GET_ARCHIVE_SITE_CONFIGS['news_link'])
        if zpr_ref:
            print(f"Getting zprv ref: {zpr_ref.get('href')}")
            zpr_link = BASE_POLICE_URL + zpr_ref.get('href').lstrip('/')
            zpravodajstvi_bytes = await get_bytes(zpr_link, session, semaphore)
            second_soup = BeautifulSoup(zpravodajstvi_bytes, 'lxml')

            # Check if the archive is already in here
            year_links = second_soup.select('a[href*="2024"], a[href*="2023"], a[href*="2022"]')
            if year_links:
                print(f"Got a nested link for {url}")
                return zpr_link

            # Else, try finding the archive link here
            else:
                second_archive_ref = second_soup.select_one(GET_ARCHIVE_SITE_CONFIGS['content_archiv'])
                print(f"Getting second arch ref: {second_archive_ref.get('href')}")
                second_archive_link = BASE_POLICE_URL + second_archive_ref.get('href').lstrip('/')
                if second_archive_link:
                    print(f"Got a double nested link for {url}")
                    return second_archive_link

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
    sites = []
    with open(POLICE_SITES_FP, "r") as p:
        for line in p:
            line = line.strip().strip("',")
            if line:
                sites.append(line)

    # Init concurrency primitives
    semaphore = asyncio.Semaphore(3)

    # Configure HTTP session with connection pooling
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=30,
        ttl_dns_cache=500
    )

    # Open the session with the context manager
    async with aiohttp.ClientSession(
            connector=connector,
            # Play nice, add the headers
            headers={
                'User-Agent': 'SitemapParser/1.0 (learning project)',
                'Accept': 'application/xml, text/xml, */*',
            }
    ) as session:
        archive_tasks = [
            get_police_archives(url, session, semaphore)
            for url in sites
        ]

        results = await asyncio.gather(*archive_tasks, return_exceptions=True)
        valid_links = [link for link in results if link and not isinstance(link, Exception)]

        with open(POLICE_ARCHIVES_FP, "w", encoding='utf-8') as a:
            json.dump(valid_links, a, indent=2)

        print(f"Finished all tasks.")
        print(f"Found {len(valid_links)}/{len(sites)} links.")
        print(f"Exiting...")


def main():
    asyncio.run(scraper())


if __name__ == "__main__":
    main()