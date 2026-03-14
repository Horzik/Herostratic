import random
import aiohttp
import asyncio

from config import MAX_RETRIES, POPO_TIMEOUT, TIMEOUT, VIDEO_TIMEOUT
from utils.logger import get_logger


class SoupError(Exception):
    def __init__(self, url):
        self.url = url
        super().__init__(f"Exception getting soup for url: '{url}'")

class FetchError(Exception):
    def __init__(self, url: str, status: int | None = None):
        self.url = url
        self.status = status
        super().__init__(f"HTTP {status} for '{url}'" if status else f"Fetch failed for '{url}'")

class DownloadError(Exception):
    def __init__(self, url: str, msg = ''):
        self.url = url
        self.msg = msg
        super().__init__(f"Download error for '{url}'...{self.msg}")

# Returns a new ClientSession with default config
def create_session():
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=50,
        ttl_dns_cache=500
    )
    return aiohttp.ClientSession(
        connector=connector,
        headers={
            # Play nice, add the headers
            'User-Agent': 'SitemapParser/1.0 (learning project)',
            'Accept': 'application/xml, text/xml, text/html, */*',
        }
    )

# todo adaptive semaphore or other adaptive rate-limit prevention
# todo leaky bucket ('aiolimiter', 'httpx.AsyncClient()'), TTFB (increase semaphore count OR outgoing requests)
async def get_bytes(
    url: str,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    gov_site=False, # Longer timeout
    verify=True, # Verify SSL certificate of the target url
    video=False # Extra long timeout
) -> bytes:
    """ Helper for fetching bytes.
        Retry strategy (with backoff as 'wait_time').
    """
    logger = get_logger('network')
    timeout = (
        POPO_TIMEOUT if gov_site
        else VIDEO_TIMEOUT if video
        else TIMEOUT
    )

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            await asyncio.sleep(random.uniform(0.3, 0.5)) # Be little nice, sleep by default and wait on retries
            wait_time = 3 ** attempt
            try:
                async with session.get(url=url, timeout=aiohttp.ClientTimeout(total=timeout), verify_ssl=verify) as response:
                    if response.status == 200:
                        content_bytes = await response.read()
                        return content_bytes

                    # "Too many requests" ==> wait extra long
                    elif response.status == 429:
                        logger.warning(f"429 for '{url}', attempt {attempt + 1}, waiting extra long")
                        jitter = random.uniform(0, wait_time)
                        await asyncio.sleep(wait_time + 10 + jitter)

                    # Retry-able errors
                    elif response.status == 500:
                        logger.warning(f"HTTP 500 for '{url}', attempt {attempt + 1}/{MAX_RETRIES}, sleeping for extra long...")
                        await asyncio.sleep(wait_time + 30)
                    elif response.status in [502, 503, 504]:
                        logger.warning(f"HTTP {response.status} for '{url}', attempt {attempt + 1}/{MAX_RETRIES}")
                        jitter = random.uniform(0, wait_time)
                        await asyncio.sleep(wait_time + jitter)

                    # 404, 403, 400, etc - don't retry
                    else:
                        logger.error(f"HTTP {response.status} for '{url}', not retrying")
                        raise FetchError(url, response.status)

            # Log exceptions
            except aiohttp.ClientConnectionError as e:
                logger.warning(f"Connection error for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            except asyncio.TimeoutError as e:
                logger.warning(f"Timeout for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            except aiohttp.ClientError as e:
                logger.warning(f"HTTPError for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")

            # Retry after exception, add a jitter
            if attempt < MAX_RETRIES - 1:
                jitter = random.uniform(0, wait_time)
                logger.warning(f"Retrying after {wait_time + jitter:.1f}s...")
                await asyncio.sleep(wait_time + jitter)

        raise FetchError(url)