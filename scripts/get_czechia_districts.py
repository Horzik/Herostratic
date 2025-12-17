from bs4 import BeautifulSoup
import asyncio
import aiofiles

from config import DISTRICTS_FP
from utils.network_utils import create_session, get_bytes


"""
    This module parses the 'statnisprava' site (which btw, does not have a valid SSL :)) in order
    to get a path of all districts, which is later used for scraping the 'metro.cz' site.

"""
STATNI_SPRAVA_URL = 'https://www.statnisprava.cz/RSTSP/redakce.nsf/i/kraje_okresy_obce'
RESULT_FP = DISTRICTS_FP


def get_paths(el_list):
    municipality_paths = []
    for row in el_list:
        text = row.get_text(strip=True)
        municipality_paths.append(text)
    return municipality_paths


async def write_res(res, fp):
    try:
        lock = asyncio.Lock()
        async with lock:
            async with aiofiles.open(fp, 'w') as f:
                await f.writelines(f'{item}\n' for item in res)
    except Exception as e:
        print(e)
        raise


async def get_districts():
    semaphore = asyncio.Semaphore()
    session = create_session()

    async with session:
        page_bytes = await get_bytes(STATNI_SPRAVA_URL, session, semaphore, verify=False)
        soup = BeautifulSoup(page_bytes, 'lxml')
        if soup is None:
            print(f"Failed getting soup...")
            return None

        list_items = soup.select('div.clanek div.row div.col-sm-6:nth-of-type(2) ul li')
        municipality_paths = get_paths(list_items)
        await write_res(municipality_paths, RESULT_FP)
        print(municipality_paths)

    return


async def main():
    print(f"Starting the parser....")
    await get_districts()
    print(f"Finished, exiting....")

if __name__ == "__main__":
    asyncio.run(main())