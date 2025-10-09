import asyncio
import aiohttp
import aiofiles

import os
import tempfile
import json
import xml.etree.ElementTree as ET

from functools import partial
from config import (
    SITEMAPS_FP,
    ARTICLES_FP,
    URL_KEYWORDS,
    MAX_RETRIES,
    TIMEOUT,
    URL_EL,
    LOC_EL,
    SITEMAP_INDEX_EL
)


async def parse_xml_tag(content_bytes: bytes, url: str) -> ET.Element | None:
    # Try multiple encodings because the sitemaps are weird
    for encoding in ['utf-8', 'windows-1250', 'iso-8859-2']:
        decoded_bytes: str = ''
        try:
            decoded_bytes = content_bytes.decode(encoding)
            # Return if no content
            if len(decoded_bytes) <= 10:
                print(f"No content for {url}, skipping")
                return None

            # Parse the root asynchronously
            loop = asyncio.get_event_loop()
            # noinspection PyTypeChecker
            root: ET.Element = await loop.run_in_executor(None, partial(ET.fromstring, decoded_bytes))
            return root

        # Catch exceptions
        except UnicodeDecodeError as e:
            print(f"UnicodeDecodeError with {encoding}: {e}")
            continue
        except ET.ParseError as e:
            print(f"ParseError with {encoding}: {e}")
            print(f"First 500 chars with {encoding}:")
            print(decoded_bytes[:500] if 'content' in locals() else "Could not decode")
            continue

    # Final fallback return
    print(f"Could not parse {url} with any encoding")
    return None


async def extract_sitemap_urls(root: ET.Element, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> list:
    # Get the sitemap urls from the tag
    sitemap_urls = root.findall(SITEMAP_INDEX_EL)
    # Create coroutine tasks, schedule and wait
    tasks = [parse_single_map(url=loc.text, session=session, semaphore=semaphore) for loc in sitemap_urls]
    result = await asyncio.gather(*tasks)

    all_urls = [url for sublist in result for url in sublist]
    return all_urls


def extract_article_urls(root: ET.Element):
    urls = []
    # Get the tags that contain the urls
    url_elements = root.findall(URL_EL)
    for url_elem in url_elements:
        # Get the actual url
        loc = url_elem.find(LOC_EL)
        if loc is not None:
            # Filter the URLs based on keywords
            if any(keyword in loc.text for keyword in URL_KEYWORDS):
                print(loc.text)
                urls.append(loc.text)
    return urls


async def get_bytes(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> bytes | None:
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            # Incrementally increase the wait time
            wait_time = 2 ** attempt
            try:
                # Make the http request
                async with session.get(url=url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as response:

                    if response.status == 200:
                        print(f"Success for {url}, attempt {attempt + 1}")
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


async def parse_single_map(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> list[str]:
    # Get the content
    content_bytes = await get_bytes(url, session, semaphore)
    if content_bytes is None:
        print(f"No content for {url}")
        return []

    # Parse the root tag
    root: ET.Element = await parse_xml_tag(content_bytes, url)
    if root is None:
        print(f"No root for {url}")
        return []

    # Parse the sitemapindex
    if "sitemapindex" in root.tag:
        sitemap_urls = await extract_sitemap_urls(root, session, semaphore)
        return sitemap_urls

    # Parse the url set
    elif "urlset" in root.tag:
        article_urls = extract_article_urls(root)
        return article_urls

    else:
        print(f"Unknown root tag: {root.tag}")
        return []


async def process_domain(domain: str, sitemaps: list[str], session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, lock: asyncio.Lock):
    print(f"Processing {domain}")
    # Create coroutine tasks
    tasks = [parse_single_map(url=sitemap, session=session, semaphore=semaphore) for sitemap in sitemaps]
    # Schedule the tasks and await
    result = await asyncio.gather(*tasks)

    # Collect the urls from domain
    all_articles = []
    for matching_articles in result:
        all_articles.extend(matching_articles)
    # Dedupe
    all_articles = list(set(all_articles))

    # Use a lock for reading and writing
    async with lock:
        try:
            async with aiofiles.open(ARTICLES_FP, 'r') as f:
                content = await f.read()
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(None, json.loads,content)
        except (json.JSONDecodeError, FileNotFoundError):
            data = {}  # Empty file or corrupt

        # Sort the articles
        data[domain] = all_articles

        # Write atomically
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(ARTICLES_FP) or '.') as tmp:
                json.dump(data, tmp, indent=2)
                tmp_name = tmp.name
            os.replace(tmp_name, ARTICLES_FP)
            print(f"✓ {domain} complete: {len(all_articles)} URLs")
        # todo something on error (retry strategy or log)
        except Exception as e:
            print(f"Error saving to {ARTICLES_FP}: {e}")
            if tmp_name and os.path.exists(tmp_name):
                # Clean up temp the file
                os.unlink(tmp_name)
            raise
    return


async def parse_all_sitemaps() -> None:
    # Init concurrency primitives
    semaphore = asyncio.Semaphore(10)
    file_lock = asyncio.Lock()

    # Load the sitemaps
    async with aiofiles.open(SITEMAPS_FP) as f:
        content = await f.read()
        sitemaps_data: dict = json.loads(content)

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
        # Check each domain
        domain_tasks = [
            process_domain(domain, sitemaps, session, semaphore, file_lock)
            for domain, sitemaps in sitemaps_data.items()
        ]
        print(f"Processing {len(domain_tasks)} domains in parallel...")
        await asyncio.gather(*domain_tasks, return_exceptions=True)


def main():
    asyncio.run(parse_all_sitemaps())


if __name__ == "__main__":
    main()