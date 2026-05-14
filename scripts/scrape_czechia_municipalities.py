import aiofiles
import asyncio

from bs4 import BeautifulSoup

from config import MUNICIPALITIES_FP
from utils.network_utils import create_session, get_bytes


LABDO_URL = 'https://www.labdo.cz/seznam-mest-a-obci-cr/'
RESULT_FP = MUNICIPALITIES_FP


async def write_result(res, fp):
    try:
        lock = asyncio.Lock()
        async with lock:
            async with aiofiles.open(fp, 'w') as f:
                await f.writelines(f'{item}\n' for item in res)

    except Exception as e:
        print(f"Failed writing results, returning...")
        print(e)
        raise


async def get_municipalities():
    """Written in async for ease, but it's just one direct request."""
    semaphore = asyncio.Semaphore()
    session = create_session()

    async with session:
        page_bytes = await get_bytes(LABDO_URL, session, semaphore)
        soup = BeautifulSoup(page_bytes, 'lxml')
        if soup is None:
            print(f"Failed getting soup, returning...")
            return None

        table = soup.select_one('div.td-pb-padding-side.td-page-content table')
        if table is None:
            print(f"List element not found, returning...")
            return None

        nominative_munis = [td.text.strip() for td in table.select('tr td:first-child')]
        try:
            await write_result(nominative_munis, RESULT_FP)
            print(f"Finished scraping and writing the municipalities, exiting...")
        except Exception as e:
            print(f"Error, failed writing municipalities: {e}")
            return None
        return


async def main():
    print(f"Starting the scrape of czechia municipalities...")
    await get_municipalities()
    print(f"Finished, exiting....")

if __name__ == "__main__":
    asyncio.run(main())
