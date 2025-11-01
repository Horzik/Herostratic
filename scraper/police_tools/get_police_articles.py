from config import POLICE_ARTICLES_FP, URL_KEYWORDS, LOG_DIR, ERRORS_LOG_FP, POLICE_ARCHIVES_FP, YEAR_LINKS_FP
from scraper.police_tools.archives.get_year_links import scrape_archive
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL
from utils.io_utils import async_json_read, atomic_json_write, CriticalDataError
from utils.logger import LogConfig, init_logging, get_logger, destroy
from utils.network_utils import create_session, get_bytes

from aiohttp import ClientSession
from datetime import timedelta
from bs4 import BeautifulSoup, ResultSet, Tag
from asyncio import gather, Lock, Semaphore, run
import logging
import json
import time


logConfig = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_police_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
)
init_logging(logConfig)
logger = get_logger('get_popo_articles')

type ArticleParseMetadata = tuple[list[str], int, int, int]
type ArticleResultsMetadata = tuple[int, int, int, int]
type ArchiveResultsMetadata = tuple[dict[str, dict[int, str]], int]

async def _read_and_write(
    domain: str,
    articles: list[str],
    year: int,
    lock: Lock
) -> None:
    """ I/O helper for the 'scrape_listings' function. \n
        Dedupes and appends non-existing article urls.
    """
    async with lock:
        # Read the data
        data = await async_json_read(POLICE_ARTICLES_FP)
        year_str = str(year)
        # Prepare the keys
        if domain not in data:
            data[domain] = {}
        if year_str not in data[domain]:
            data[domain][year_str] = []

        # Append the results
        articles = list(set(articles))  # Dedupe current scrape
        existing_urls = set(data[domain][year_str])  # What's already saved
        new_urls = [url for url in articles if url not in existing_urls]  # Only new ones
        data[domain][year_str].extend(new_urls)

        # Write the results back
        atomic_json_write(data, POLICE_ARTICLES_FP)
        logger.info(f"Success: written {len(articles)} for {domain} in year {year}")


def process_article_results(article_results: list) -> ArticleResultsMetadata:
    """ Process all the article results from parsing the listings pages.
        Aggregate and return their stats.
    """

    saved_articles = 0
    failed_articles = 0
    articles_processed = 0
    total_pages = 0
    for i, result in enumerate(article_results):
        if isinstance(result, Exception):
            logger.error(f"Police scraping task {i} failed with exception: {result}")
            failed_articles += 1
            continue
        if result is None:
            logger.error(f"Error: result is None for task {i}")
            failed_articles += 1
            continue
        articles, pages, all_articles = result
        saved_articles += articles
        articles_processed += all_articles
        total_pages += pages

    return saved_articles, failed_articles, articles_processed, total_pages


def process_archive_results(
    archive_jobs: list,
    archive_results: list
) -> ArchiveResultsMetadata:
    """ Process all archive results from parsing the archive pages. \n
        Return the target sites and number of failed tasks.
    """

    sites = {}
    failed_archives = 0 # todo return the actual failed archive, not just int
    # Get the domains from tasks, check and process each result
    for (domain, _), arch_result in zip(archive_jobs, archive_results):
        # Check for failed coroutine results
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

    # Write for debug and clarity (not actually part of the pipe)
    logger.debug(f"Writing year links results....")
    with open(YEAR_LINKS_FP, 'w') as f:
        json.dump(sites, f, ensure_ascii=False, indent=2)
    logger.debug(f"Results:: {sites}")

    return sites, failed_archives


def parse_articles_listing(
    url: str,
    page_bytes: bytes,
    metadata: ArticleParseMetadata,
    domain: str,
    year: int
) -> tuple[ArticleParseMetadata, str | None] | None:
    """ Parse the html content of the current articles listing page """

    # Unpack the stuff
    articles, all_articles_count, pages_scraped, max_pages = metadata
    main_soup = BeautifulSoup(page_bytes, 'lxml')
    article_list = main_soup.select(POLICE_SELECTOR['listing_selectors']['article_selector'])
    if not article_list:
        logger.error(f"Failed getting the article list element {domain}"
                     f" and url '{url}' element, check the html.")
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
        # todo try detecting the numbers directly and check for the dots.
        max_pages_el = main_soup.select(POLICE_SELECTOR['listing_selectors']['last_page'])
        if max_pages_el:
            max_pages = int(max_pages_el[-1].text)
        else:
            max_pages = '80085'

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

    parsing_result: ArticleParseMetadata = (articles, all_articles_count, pages_scraped, max_pages)
    return parsing_result, current_url


async def scrape_listings(
    url: str,
    year: int,
    domain: str,
    session: ClientSession,
    semaphore: Semaphore,
    lock: Lock
) -> tuple[int, int, int] | None:
    """ Scrape the domain for article links
    """
    current_url = url
    articles = []
    all_articles_count = 0
    pages_scraped = 0
    max_pages = 0
    metadata: ArticleParseMetadata = (articles, all_articles_count, pages_scraped, max_pages)
    try:
        while current_url:
            # Fetch bytes from url
            page_bytes = await get_bytes(url=current_url, session=session, semaphore=semaphore, gov_site=True)
            if page_bytes is None:
                logger.error(f"Error: failed fetching '{current_url}', domain: '{domain}' year: '{year}', continuing....")
                return None
            parsing_result, current_url = parse_articles_listing(current_url, page_bytes, metadata, domain, year)
            metadata: ArticleParseMetadata = parsing_result

        # Write and return the results
        await _read_and_write(domain, articles, year, lock)
        return len(articles), pages_scraped, all_articles_count

    # Re-raise writing error
    except CriticalDataError:
        raise
    # Catch any generic error
    except Exception as e:
        logger.error(f" {domain}/{year} FAILED for '{current_url}'...Error ===>")
        logger.exception(e)
    return None


async def scraper(fp: str = POLICE_ARCHIVES_FP):
    """Main orchestrator, runs archive jobs (to get year links of archives), then the article jobs (to get article urls)."""

    with open(fp, "r") as a:
        archives: dict = json.load(a)

    # Init async and open the session.
    timer_start = time.time()
    semaphore = Semaphore(30)
    file_lock = Lock()
    async with create_session() as session:

        # First we get the "year links" for each archive.
        archive_jobs = [
            (domain, scrape_archive(url, domain, session, semaphore)) # Add the domain.
            for domain, urls in archives.items()
            for url in urls
        ]
        # Gather the coroutines and await, this shouldn't take long.
        logger.info(f'Scraping {len(archive_jobs)} archive links....')
        archive_results = await gather(*[coro for _, coro in archive_jobs],
            return_exceptions=True
        )
        # Process the archive results (years and their links are added to the sites)
        sites, failed_archives = process_archive_results(archive_jobs, archive_results)
        logger.debug(f"Finished archive jobs in {time.time() - timer_start} seconds") # todo time is weird

        # Next we scrape each of the year links for all relevant articles
        logger.debug(f"Preparing article jobs")
        article_jobs = [
            ((domain, year), scrape_listings(url, year, domain, session, semaphore, file_lock)) # List of ((domain, year), coroutine)
            for domain, years in sites.items()
            for year, urls in years.items()
            # todo do this uniformly OR use some OOP trix
            for url in (urls if isinstance(urls, list) else [urls])
        ]
        # Gather the coroutines and await.
        if {len(archives) - failed_archives} != {len(archives)}:
            logger.error(f"Error: failed parsing archive links:: {failed_archives}")
            logger.error(f"All years not scraped: {len(archives) - failed_archives}/{len(archives)}. Exiting... ")
            # logger.error(f"CONTINUING ANYWAYS")
            return None
        logger.info(f"Scraping {len(article_jobs)} tasks from {len(archives) - failed_archives}/{len(archives)} archives...")
        article_results = await gather(*[ coro for _, coro in article_jobs],
            return_exceptions=True
        )

        # Process the final results.
        saved_articles, failed_articles, articles_processed, total_pages = process_article_results(article_results)

    # Final count,
    timer_end = time.time()
    elapsed_seconds = timer_end - timer_start
    formatted_time = str(timedelta(seconds=elapsed_seconds))
    logger.info(f"Finished scraping in {formatted_time}")
    logger.info(f"Processed {articles_processed} articles from {total_pages} pages, saved {saved_articles}, failed {failed_articles}")
    logger.info(f"Exiting...")
    exit(0)


def main():
    run(scraper())
    destroy()


if __name__ == "__main__":
    main()