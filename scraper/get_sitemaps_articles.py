import os
import tempfile
import json
import asyncio
import aiohttp
import aiofiles
import xml.etree.ElementTree as ET
import logging
from functools import partial

from utils.io_utils import CriticalDataError
from utils.logger import LogConfig, init_logging, get_logger, destroy
from utils.network_utils import create_session, get_bytes
from config import (
    SITEMAPS_FP,
    ARTICLES_FP,
    URL_KEYWORDS,
    URL_EL,
    LOC_EL,
    SITEMAP_INDEX_EL, LOG_DIR, ERRORS_LOG_FP,
)


config = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'parse_sitemaps.log',
        log_errors_file_path=ERRORS_LOG_FP
    )
init_logging(config)
logger = get_logger()

async def parse_xml_tag(content_bytes: bytes, url: str) -> ET.Element | None:
    # Try multiple encodings because the sitemaps are weird
    for encoding in ['utf-8', 'windows-1250', 'iso-8859-2']:
        decoded_bytes: str = ''
        try:
            decoded_bytes = content_bytes.decode(encoding)
            # Return if no content
            if len(decoded_bytes) <= 10:
                logger.warning(f"No content for {url}, skipping")
                return None

            # Parse the root asynchronously
            loop = asyncio.get_event_loop()
            # noinspection PyTypeChecker
            root: ET.Element = await loop.run_in_executor(None, partial(ET.fromstring, decoded_bytes))
            return root

        # Catch exceptions
        except UnicodeDecodeError as e:
            logger.error(f"UnicodeDecodeError with {encoding}: {e}")
            continue
        except ET.ParseError as e:
            logger.error(f"ParseError with {encoding}: {e}")
            logger.error(f"First 500 chars with {encoding}:")
            logger.error(decoded_bytes[:500] if 'content' in locals() else "Could not decode")
            continue

    # Final fallback return
    logger.warning(f"Could not parse {url} with any encoding")
    return None


async def extract_sitemap_urls(root: ET.Element, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> list[str]:
    # Get the sitemap urls from the tag
    sitemap_urls = root.findall(SITEMAP_INDEX_EL)
    # Create coroutine tasks, schedule and wait
    tasks = [parse_single_map(url=loc.text, session=session, semaphore=semaphore) for loc in sitemap_urls]
    result = await asyncio.gather(*tasks)

    all_urls = [url for sublist in result for url in sublist]
    return all_urls


def extract_article_urls(root: ET.Element):
    # Get the tags which contain the urls
    urls = []
    url_elements = root.findall(URL_EL)

    for url_elem in url_elements:
        # Get the actual url
        loc = url_elem.find(LOC_EL)
        if loc is not None:
            # Filter the URLs based on keywords
            if any(keyword in loc.text for keyword in URL_KEYWORDS):
                # todo: Exclude some keywords?
                # todo: Dedupe by article key...
                # slug = get_article_key(loc.text)
                # if slug not in seen_slugs:
                #     seen_slugs.add(slug)
                #     urls.append(loc.text)
                #     print(loc.text)
                urls.append(loc.text)

    logger.info(f"Found {len(urls)} urls")
    return urls


async def parse_single_map(url: str, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> list[str]:
    # Get the content
    content_bytes = await get_bytes(url, session, semaphore)
    if content_bytes is None:
        logger.warning(f"No content for {url}")
        return []

    # Parse the root tag
    root: ET.Element = await parse_xml_tag(content_bytes, url)
    if root is None:
        logger.warning(f"No root for {url}")
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
        logger.warning(f"Unknown root tag: {root.tag}")
        return []


async def process_domain(domain: str, sitemaps: list[str], session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, lock: asyncio.Lock):
    logger.info(f"Processing {domain}")
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
        # Probably better to wrap the whole lock in a try block?
        try:
            # Load the json asynchronously with the running loop
            async with aiofiles.open(ARTICLES_FP, 'r') as f:
                content = await f.read()
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(None, json.loads,content)

        except (json.JSONDecodeError, FileNotFoundError):
            logger.error(f"Error, file {ARTICLES_FP} not found")

        # Sort the articles
        data[domain] = all_articles

        # Write atomically
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(ARTICLES_FP) or '.') as tmp:
                json.dump(data, tmp, indent=2)
                tmp_name = tmp.name
            os.replace(tmp_name, ARTICLES_FP)
            logger.info(f"{domain} complete: {len(all_articles)} URLs")
        # TODO something on error (another retry or log)
        except CriticalDataError as e:
            logger.error(f"Error saving to {ARTICLES_FP}: {e}")
            if tmp_name and os.path.exists(tmp_name):
                os.unlink(tmp_name) # Clean up temp the file
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

    # Open the session with the context manager
    async with create_session() as session:
        # Check each domain
        domain_tasks = [
            process_domain(domain, sitemaps, session, semaphore, file_lock)
            for domain, sitemaps in sitemaps_data.items()
        ]
        logger.info(f"Processing {len(domain_tasks)} domains in parallel...")
        await asyncio.gather(*domain_tasks, return_exceptions=True)


def main():
    asyncio.run(parse_all_sitemaps())
    destroy() # Kill the log handlers


if __name__ == "__main__":
    main()