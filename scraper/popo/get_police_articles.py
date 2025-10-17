import asyncio
import logging
import os
import tempfile
import os.path
import time
from datetime import timedelta

import aiofiles
import json

from bs4 import BeautifulSoup

from config import POLICE_ARTICLES_FP, URL_KEYWORDS, LOG_DIR, ERRORS_LOG_FP, POLICE_ARCHIVES_FP
from utils.logger import LogConfig, init_logging, get_logger, destroy
from utils.network_utils import create_session, get_bytes
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL


logConfig = LogConfig(
        log_level=logging.INFO,
        log_file_path=LOG_DIR / 'get_popo_articles.log',
        log_errors_file_path=ERRORS_LOG_FP)
init_logging(logConfig)
logger = get_logger('get_popo_articles')


async def get_police_articles(url, year, domain, session, semaphore, lock) -> (int, int, int) or None:
    current_url = url
    articles = []
    all_articles_count = 0
    pages_scraped = 0
    max_pages = 0
    try:
        while current_url:
            # Fetch bytes from url
            page_bytes = await get_bytes(url=current_url, session=session, semaphore=semaphore, gov_site=True)
            if page_bytes is None:
                logger.error(f"Error: failed fetching '{current_url}', domain: '{domain}' year: '{year}', continuing....")
                return None

            # Get the list of articles
            main_soup = BeautifulSoup(page_bytes, 'lxml')
            article_list = main_soup.select(POLICE_SELECTOR['listing_selectors']['article_selector'])
            if not article_list:
                logger.error(f"Failed getting the article list element {domain} and url '{url}' element, check the html")
                return None

            for article in article_list:
                # Get the link to the article and append it to the list
                select_link = article.select_one(POLICE_SELECTOR['listing_selectors']['article_link'])
                article_link = select_link['href']
                all_articles_count += 1
                # Only save the articles that include the keywords
                if any(keyword in article_link for keyword in URL_KEYWORDS):
                    articles.append(BASE_POLICE_URL + article_link)
                    logger.info(f"Success scraping article...:'{article_link}'")

            if max_pages == 0:
                max_pages = int(main_soup.select(POLICE_SELECTOR['listing_selectors']['last_page'])[-1].text)


            # Get the next page link and change 'current_url' to continue the loop
            next_page = main_soup.select_one(POLICE_SELECTOR['pagination']['next_page'])
            if next_page:
                next_page_link = next_page['href']
                current_url = BASE_POLICE_URL + next_page_link
                pages_scraped += 1
                logger.debug(f"Continuing to page {pages_scraped}/{max_pages} in year {year} for: '{domain}'")
            else:
                # Else stop the loop and write the collected articles
                logger.info(f"No next page found, checked {all_articles_count} articles")
                logger.info(f"Saving {len(articles)} articles from {pages_scraped} pages in year {year} for: {domain}...")
                current_url = None

        # Write the results
        async with lock:
            try:
                # Read the existing articles
                async with aiofiles.open(POLICE_ARTICLES_FP, 'r', encoding='utf-8') as a:
                    content = await a.read()
                    loop = asyncio.get_event_loop()
                    data = await loop.run_in_executor(None, json.loads, content)
            # If no file, start with empty object
            except (json.JSONDecodeError, FileNotFoundError):
                logger.debug("Failed to open POLICE_ARTICLES_FP, creating empty dict...")
                data = {}

            if domain not in data:
                data[domain] = {}
            if year not in data[domain]:
                data[domain][year] = []

            articles = list(set(articles)) # Dedupe current scrape
            existing_urls = set(data[domain][year])  # What's already saved
            new_urls = [url for url in articles if url not in existing_urls]  # Only new ones
            data[domain][year].extend(new_urls)

            # Write atomically
            try:
                tmp_name = None
                with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(POLICE_ARTICLES_FP)) as tmp:
                    json.dump(data, tmp, indent=4, ensure_ascii=False)
                    tmp_name = tmp.name
                os.replace(tmp_name, POLICE_ARTICLES_FP)
                logger.info(f"Success: got {len(articles)} for {domain} in year {year}")

            # Catch errors for writing the results
            except Exception as r:
                logger.critical(f"!!ERROR WRITING RESULTS!!")
                logger.critical(f"ERROR: {r}")
                if tmp_name and os.path.exists(tmp_name):
                    os.unlink(tmp_name)

        return len(articles), pages_scraped, all_articles_count

    # Catch any generic error
    except Exception as e:
        logger.error(f"Error reading '{current_url}', domain: '{domain}' year: '{year}'. Error ===>")
        logger.error(e)
    return None


# Returns all years and their article listings links for the target domain (ie from the link)
async def parse_archive(url, domain, session, semaphore) -> tuple[str, dict[int, str]] | None:
    try:
        page_bytes = await get_bytes(url=url, session=session, semaphore=semaphore, gov_site=True)
        if page_bytes is None:
            logger.error(f"Couldn't get the main content from {url}")
            return None

        main_soup = BeautifulSoup(page_bytes, 'lxml')

        # Check all possible locations of the year links
        # todo could be a lot nicer
        if 'Vysočina' in domain or 'Zlk' in domain or 'Zlínsk' in domain:
            # Special hack for the two problem sites (iykyk)
            content_ref = main_soup.select('table tr td a')
            logger.debug(f"Using special table selector for {domain}, found {len(content_ref)} links")
        else:
            content_ref = main_soup.select(POLICE_SELECTOR['archive_selectors']['year_links'])
            if not content_ref:
                logger.warning(f"No primary selector, trying table...")
                content_ref = main_soup.select('table td a')
                if not content_ref:
                    logger.warning(f"No table, trying p tags...")
                    content_ref = main_soup.select('#content p a')
                    if not content_ref:
                        logger.warning(f"No p tags, trying ul...")
                        content_ref = main_soup.select('ul li a')
                        if not content_ref:
                            logger.error(f"Failed getting content '{domain}'...")
                            return None

        logger.debug(f"Parsing {domain} for year links...")

        # Aggregate the years and their links
        all_years: dict[int, str] = {}
        for year_element in content_ref:
            year_ref = year_element.get('href')
            year_link = BASE_POLICE_URL + year_ref
            if not year_link:
                logger.error(f"Missing year_link for url: '{url}'...")
                logger.error(f"Year element: {year_element}")
                continue
            year_text = year_element.get_text(strip=True)
            try:
                import re
                # Get only the year from year_text
                match = re.search(r'\b(20\d{2})\b', year_text)
                if not match:
                    continue
                year = int(match.group(1))
                all_years[year] = year_link
            except ValueError:
                logger.error(f"Failed to parse year '{year_text}' ...")

        # Return all years for the domain
        if (len(all_years)) == 0:
            logger.error(f"Couldn't find any year links in '{domain}'...")
            logger.error(f"The content element::: {content_ref}")
            return None

        logger.info(f"Found {len(all_years)} years in '{url}'")
        return domain, all_years

    except Exception as e:
        logger.error(f"Error reading {url}: {e}")
        return None


async def scraper():
    # Load the archive sites
    with open(POLICE_ARCHIVES_FP, "r") as r:
        content = r.read()
        archives: dict = json.loads(content)

    # Init the async primitives and open the session
    timer_start = time.time()
    semaphore = asyncio.Semaphore(30)
    file_lock = asyncio.Lock()
    async with create_session() as session:

        # Create list of tuples: (domain, year, coroutine)
        archive_tasks = [
            (domain, parse_archive(url, domain, session, semaphore))
            for domain, urls in archives.items()
            for url in urls
        ]
        # Omit the domain from results and run each archive parse
        archive_results = await asyncio.gather(*[task for _, task in archive_tasks],
            return_exceptions=True
        )

        # Get the domains from tasks, check and process each result
        sites = {}
        failed_archives = 0
        for (domain, _), arch_result in zip(archive_tasks, archive_results):
            # Check errors
            if isinstance(arch_result, Exception):
                logger.error(f"Error for archive task for domain: '{domain}'...")
                logger.error(f"Archive result:: {arch_result}")
                failed_archives += 1
                continue
            if arch_result is None:
                logger.error(f"Error: domain '{domain}' returns {arch_result}....")
                failed_archives += 1
                continue
            domain, year_links = arch_result
            if domain not in sites:
                sites[domain] = {}
            sites[domain].update(year_links)

        # Scrape all years of all archives
        police_tasks = [
            get_police_articles(url, year, domain, session, semaphore, file_lock)
            for domain, years in sites.items()
            for year, url in years.items()
        ]
        saved_articles = 0
        failed_articles = 0
        articles_processed = 0
        total_pages = 0

        # Run the articles tasks and check result
        logger.info(f"Scraping {len(police_tasks)} tasks from {len(archives) - failed_archives}/{len(archives)} archives...")
        article_results = await asyncio.gather(*police_tasks, return_exceptions=True)
        for i, result in enumerate(article_results):
            if isinstance(result, Exception):
                logger.error(f"Police scraping task {i} failed with exception: {result}")
                failed_articles += 1
                continue
            if result is None:
                logger.error(f"Error: domain '{domain}' returns {result}....")
                failed_articles += 1
                continue
            articles, pages, all_articles = result
            saved_articles += articles
            articles_processed += all_articles
            total_pages += pages

    # Final count
    timer_end = time.time()
    elapsed_seconds = timer_end - timer_start
    formatted_time = str(timedelta(seconds=elapsed_seconds))
    logger.info(f"Finished scraping in {formatted_time}")
    logger.info(f"Processed {articles_processed} articles from {total_pages} pages, saved {saved_articles}, failed {failed_articles}")
    logger.info(f"Exiting...")


def main():
    asyncio.run(scraper())
    destroy()


if __name__ == "__main__":
    main()