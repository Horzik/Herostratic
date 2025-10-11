import asyncio
import json
import random

import aiohttp
from bs4 import BeautifulSoup
from scraper.network_utils import get_bytes

from config import POLICE_ARCHIVES_FP
from scraper.site_configs import GET_ARCHIVE_SITE_CONFIGS

sites = [
 'https://policie.gov.cz/web-informacni-servis-zpravodajstvi.aspx',
 'https://policie.gov.cz/sprava-hl-m-prahy-zpravodajstvi.aspx',
 'https://policie.gov.cz/uzemni-utvary-sprava-zapadoceskeho-kraje-zpravodajstvi.aspx',
 'https://policie.gov.cz/sprava-stredoceskeho-kraje-zpravodajstvi.aspx',
 'https://policie.gov.cz/sprava-jihoceskeho-kraje-zpravodajstvi.aspx',
 'https://policie.gov.cz/uzemni-utvary-krajske-reditelstvi-policie-kvk-zpravodajstvi.aspx',
 'https://policie.gov.cz/uzemni-utvary-sprava-severoceskeho-kraje-zpravodajstvi.aspx',
 'https://policie.gov.cz/krajske-reditelstvi-policie-lbk-zpravodajstvi.aspx',
 'https://policie.gov.cz/kralovehradecky-kraj-zpravodajstvi.aspx',
 'https://policie.gov.cz/krajske-reditelstvi-policie-pdk-zpravodajstvi.aspx',
 'https://policie.gov.cz/krajske-reditelstvi-policie-kvs-zpravodajstvi.aspx',
 'https://policie.gov.cz/sprava-jihomoravskeho-kraje-zpravodajstvi.aspx',
 'https://policie.gov.cz/zpravodajstvi-zlinskeho-kraje.aspx',
 'https://policie.gov.cz/krajske-reditelstvi-olomouckeho-kraje-zpravodajstvi.aspx',
 'https://policie.gov.cz/krajske-reditelstvi-severomoravskeho-kraje-zpravodajstvi.aspx',
]

# Check if a target page has a sitemap, save it and write the resto to "NOSITEMAPS"

async def get_police_archives(session, semaphore):
    base_url = "https://policie.gov.cz/"
    # Read and clean the urls
    with open(POLICE_ARCHIVES_FP, "w") as a:
        links = []
        for url in sites:
            await asyncio.sleep(random.uniform(2, 5))
            try:
                main_content_bytes = await get_bytes(url, session, semaphore)
                main_soup = BeautifulSoup(main_content_bytes, 'lxml')

                # If we get archive link => win, return
                archive_ref = main_soup.select_one(GET_ARCHIVE_SITE_CONFIGS['archive_link'])
                archive_link = base_url + archive_ref.get('href').lstrip('/')
                if archive_link:
                    print(f"Got a direct link for {url}")
                    links.append(archive_link)
                    continue

                # Else it's harder, go to the "zpravodajstvi" link
                zpr_ref = main_soup.select_one(GET_ARCHIVE_SITE_CONFIGS['news_link'])
                zpr_link = base_url + zpr_ref['href'].lstrip('/')
                zpravodajstvi_bytes = await get_bytes(zpr_link, session, semaphore)
                second_soup = BeautifulSoup(zpravodajstvi_bytes, 'lxml')

                # Check if the archive is already in here
                year_links = second_soup.select('a[href*="2024"], a[href*="2023"], a[href*="2022"]')
                if year_links:
                    print(f"Got a nested link for {url}")
                    links.append(zpr_link)
                    continue

                # Else, try finding the archive link here
                second_archive_ref = second_soup.select_one(GET_ARCHIVE_SITE_CONFIGS['content_archiv'])
                second_archive_link = base_url + second_archive_ref['href'].lstrip('/')

                if second_archive_link:
                    print(f"Got a double nested link for {url}")
                    links.append(second_archive_link)
                    continue

                # Else we are fucked
                print(f"Couldn't find the archive for {url}")
                continue

            except aiohttp.ClientConnectionError as e:
                print(f"Connection error for {url}:: {e}")
            except asyncio.TimeoutError as e:
                print(f"Timeout for {url}:: {e}")
            except aiohttp.ClientError as e:
                print(f"HTTPError for {url}:: {e}")
            except Exception as e:
                print(f"Error reading {url}::")
                print(e)

        # Dump and return
        json.dump(links, a, indent=2)
    return


async def scraper():
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
        await get_police_archives(session, semaphore)
        print(f"Finished all tasks, exiting...")


def main():
    asyncio.run(scraper())


if __name__ == "__main__":
    main()