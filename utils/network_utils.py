import random
import aiohttp
import asyncio

from config import MAX_RETRIES, POPO_TIMEOUT, TIMEOUT
from utils.logger import get_logger


class FetchError(Exception):
    def __init__(self, url: str, status: int):
        self.url = url
        self.status = status
        super().__init__(f"HTTP {status} for '{url}'")


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

# TODO adaptive semaphore or other adaptive rate-limit prevention, leaky bucket
# todo 'aiolimiter', 'httpx.AsyncClient()'


# Function to fetch target url and return its bytes
async def get_bytes(
    url: str,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    gov_site=False,
    verify=True
) -> bytes | None:
    logger = get_logger('network')
    timeout = POPO_TIMEOUT if gov_site else TIMEOUT
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            # Be little nice, sleep by default and wait on retries
            await asyncio.sleep(random.uniform(0.3, 0.5))
            wait_time = 3 ** attempt
            # todo use the TTFB for congestion control (increase semaphore count OR outgoing requests)
            try:
                async with session.get(url=url, timeout=aiohttp.ClientTimeout(total=timeout), verify_ssl=verify) as response:
                    # todo abstract the response handling?
                    if response.status == 200:
                        # Sometimes the status is 200 even though the page is 404...
                        # todo this can get messy if the url includes a random '404' number by accident
                        if "404" in str(response.url):
                            raise FetchError(url, response.status)

                        content_bytes = await response.read()
                        return content_bytes

                    # "Too many requests" ==> wait extra long
                    elif response.status == 429:
                        logger.warning(f"429 for '{url}', attempt {attempt + 1}, waiting extra long")
                        if attempt < MAX_RETRIES - 1:
                            jitter = random.uniform(0, wait_time)  # Add randomness
                            await asyncio.sleep(wait_time + 10 + jitter)
                            continue
                        else:
                            logger.error(f"Failed fetching '{url}' with {response.status}, all tries exhausted")
                            raise FetchError(url, response.status)

                    # Retry-able errors
                    elif response.status == 500:
                        logger.warning(f"HTTP 500 for '{url}', attempt {attempt + 1}/{MAX_RETRIES}, sleeping for extra long...")
                        await asyncio.sleep(wait_time + 30)
                        continue

                    elif response.status in [502, 503, 504]:
                        logger.warning(f"HTTP {response.status} for '{url}', attempt {attempt + 1}/{MAX_RETRIES}")
                        if attempt < MAX_RETRIES - 1:
                            jitter = random.uniform(0, wait_time)  # Add randomness
                            await asyncio.sleep(wait_time + jitter)
                            continue
                        else:
                            logger.error(f"Failed fetching '{url}' with {response.status}, all tries exhausted")
                            raise FetchError(url, response.status)

                    else:  # 404, 403, 400, etc - don't retry
                        logger.error(f"HTTP {response.status} for '{url}', not retrying")
                        raise FetchError(url, response.status)

            # Catch exceptions
            except aiohttp.ClientConnectionError as e:
                logger.warning(f"Connection error for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            except asyncio.TimeoutError as e:
                logger.warning(f"Timeout for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            except aiohttp.ClientError as e:
                logger.warning(f"HTTPError for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")

            # Retry after exception, add a jitter
            if attempt < MAX_RETRIES - 1:
                jitter = random.uniform(0, wait_time)  # Add randomness
                logger.warning(f"Retrying after {wait_time + jitter:.1f}s...")
                await asyncio.sleep(wait_time + jitter)
            else:
                logger.error(f"Failed parsing '{url}', all tries exhausted")
                return None
        return None
