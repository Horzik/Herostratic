import aiohttp
import asyncio
from config import MAX_RETRIES, POPO_TIMEOUT, TIMEOUT
from utils.logger import get_logger


def create_session():
    # Configure HTTP session with connection pooling
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=30,
        ttl_dns_cache=500
    )

    return aiohttp.ClientSession(
        connector=connector,
        # Play nice, add the headers
        headers={
            'User-Agent': 'SitemapParser/1.0 (learning project)',
            'Accept': 'application/xml, text/xml, text/html, */*',
        }
    )


async def get_bytes(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, gov_site=False) -> bytes | None:
    logger = get_logger('network')
    timeout = POPO_TIMEOUT if gov_site else TIMEOUT
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            # Incrementally increase the wait time
            wait_time = 2 ** attempt
            try:
                # Make the http request
                async with session.get(url=url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:

                    if response.status == 200:
                        # print(f"Success for {url}, attempt {attempt + 1}")
                        content_bytes = await response.read()
                        return content_bytes
                    elif response.status == 429:
                        logger.warning(f"429 for '{url}', attempt {attempt + 1}, waiting extra long")
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(wait_time + 10)
                            continue
                        else:
                            logger.error(f"Failed fetching '{url}' with {response.status}, all tries exhausted")
                            return None
                    elif response.status in [500, 502, 503, 504]:  # Retry-able errors
                        logger.warning(f"HTTP {response.status} for '{url}', attempt {attempt + 1}/{MAX_RETRIES}")
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Failed fetching '{url}' with {response.status}, all tries exhausted")
                            return None
                    else:  # 404, 403, 400, etc - don't retry
                        logger.error(f"HTTP {response.status} for '{url}', not retrying")
                        return None

            # Catch exceptions
            # todo create an error log (and other logs)
            except aiohttp.ClientConnectionError as e:
                logger.warning(f"Connection error for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            except asyncio.TimeoutError as e:
                logger.warning(f"Timeout for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            except aiohttp.ClientError as e:
                logger.warning(f"HTTPError for '{url}', (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            # Retry
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Retrying...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed parsing '{url}', all tries exhausted")
                return None
        # Return so that linter stays happy :))
        return None