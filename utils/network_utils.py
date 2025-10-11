import aiohttp
import asyncio
from config import MAX_RETRIES, TIMEOUT


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

async def get_bytes(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> bytes | None:
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            # Incrementally increase the wait time
            wait_time = 2 ** attempt
            try:
                # Make the http request
                async with session.get(url=url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as response:

                    if response.status == 200:
                        # print(f"Success for {url}, attempt {attempt + 1}")
                        content_bytes = await response.read()
                        return content_bytes
                    elif response.status == 429:
                        print(f"429 for {url}, attempt {attempt + 1}, waiting extra long")
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(wait_time + 10)
                            continue
                        else:
                            return None
                    elif response.status in [500, 502, 503, 504]:  # Retry-able errors
                        print(f"HTTP {response.status} for {url}, attempt {attempt + 1}/{MAX_RETRIES}")
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            return None
                    else:  # 404, 403, 400, etc - don't retry
                        print(f"HTTP {response.status} for {url}, not retrying")
                        return None

            # Catch exceptions
            # todo create an error log (and other logs)
            except aiohttp.ClientConnectionError as e:
                print(f"Connection error for {url}, (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            except asyncio.TimeoutError as e:
                print(f"Timeout for {url}, (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            except aiohttp.ClientError as e:
                print(f"HTTPError for {url}, (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
            # Retry
            if attempt < MAX_RETRIES - 1:
                print(f"Retrying in...")
                await asyncio.sleep(wait_time)
            else:
                print(f"Failed parsing {url}, skipping")
                return None
        # Return so that linter stays happy :))
        return None