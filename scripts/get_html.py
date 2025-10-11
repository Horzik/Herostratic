import aiohttp
import asyncio
import aiofiles
from bs4 import BeautifulSoup

from utils.network_utils import get_bytes
from config import HTML_FP

POLICE_ARCHIVE = "https://policie.gov.cz/clanek/zpravodajstvi-archiv-zpravodajstvi-zpravodajstvi-archiv.aspx"
POLICE_ARTICLE = "https://policie.gov.cz/clanek/loupezne-prepadeni-v-decine.aspx"
URL = "https://policie.gov.cz/clanek/zpravodajstvi-krajskeho-reditelstvi-policie-kraje-vysocina.aspx"


async def get_html(url, session, semaphore, lock):
    print(f"Parsing url:: {url}...")
    try:
        content_bytes = await get_bytes(url, session, semaphore)
        soup = BeautifulSoup(content_bytes, 'lxml')
        pretty_file = soup.prettify()
        if pretty_file is not None:
            async with lock:
                async with aiofiles.open(HTML_FP, mode='w', encoding='utf-8') as f:
                    await f.write(pretty_file)
                    # loop = asyncio.get_running_loop()
                    # await f.write(await loop.run_in_executor(None, page_content)
        else:
            print(f"Page content is empty")
            return
    except Exception as e:
        print(f"Error getting page: {e}")

    print(f"Success: parsed the tree")
    return

async def scraper():
    # Init concurrency primitives
    semaphore = asyncio.Semaphore(10)
    file_lock = asyncio.Lock()

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
        tree_tasks = [
            get_html(POLICE_ARTICLE, session, semaphore, file_lock),
        ]

        await asyncio.gather(*tree_tasks, return_exceptions=True)


def main():
    asyncio.run(scraper())

if __name__ == "__main__":
    main()
