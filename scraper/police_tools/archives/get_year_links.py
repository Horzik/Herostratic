from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL, TABLE_SELECTORS, DOMAIN_SELECTORS
from utils.logger import LogConfig, init_logging, get_logger
from utils.network_utils import get_bytes
from config import LOG_DIR, ERRORS_LOG_FP

from bs4 import BeautifulSoup, ResultSet, Tag
from aiohttp import ClientSession
from asyncio import Semaphore
import logging
import re


logConfig = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_year_links.log',
        log_errors_file_path=ERRORS_LOG_FP
)
init_logging(logConfig)
logger = get_logger('get_year_links')


type YearLinks = dict[str, str | list[str]]


def process_year_elements(year_table: ResultSet[Tag], url: str) -> YearLinks:
    """ Process the target 'year link' table for year links """

    all_years: YearLinks = {}
    for element in year_table:
        logger.debug(f"Year table of '{url}' :: {year_table}")
        year_href = element.get('href')
        logger.debug(f"year href of '{url}' :: {year_href}")

        if year_href.startswith('http'):
            # Some refs have the base url already
            year_link = year_href
        else:
            # While others don't
            year_link = BASE_POLICE_URL + year_href

        if not year_link:
            logger.error(f"Missing year_link for url: '{url}'...")
            logger.error(f"Year element: {element}")
            continue

        year_text = element.get_text(strip=True)
        try:
            # Get only the year from the text
            match = re.search(r'\b(20\d{2})\b', year_text)
            if not match:
                continue
            year = match.group(1)

            if year not in all_years:
                all_years[year] = []
            all_years[year].append(year_link)

        except ValueError:
            logger.exception(f"Failed to parse year '{year_text}' ...")
            raise

    if (len(all_years)) == 0:
        logger.error(f"Couldn't find any year links in: '{url}'...")
        logger.error(f"The failed field table ::: {year_table}")
        raise ValueError("No year links found")

    return all_years


async def validate_year_links(all_years: YearLinks, url: str, session: ClientSession, semaphore: Semaphore) -> bool:
    """ Gets the content of each year link and verifies it contains the article listings. \n
        Note. Does not produce or read any stats, just checks...
    """
    try:
        for year, link_or_links in all_years.items():
            logger.debug(f"Validating year {year} for '{link_or_links}'")
            # Handle both single URL and list of URLs
            links = [link_or_links] if isinstance(link_or_links, str) else link_or_links

            for link in links:
                content = await get_bytes(link, session, semaphore, gov_site=True)
                if content is None:
                    return False
                soup = BeautifulSoup(content, 'lxml')

                # Check if there is the page navigation
                pager = soup.select_one('p.pager')
                if not pager:
                    logger.error(f"Failed validating year link '{link}' for year '{year}'")
                    return False

        return True

    except Exception:
        logger.exception(f"Error for validating year links in url '{url}...'")
        raise


async def parse_jihomor_archive(soup: BeautifulSoup, session: ClientSession, semaphore: Semaphore) -> YearLinks:
    """
        Get the year table, and crawl through to get the years links. \n
        First link => Second link => Multiple urls per year.
    """

    jihomor_years: YearLinks = {}
    content_el = soup.select_one(POLICE_SELECTOR['article_selectors']['content'])
    years_table = content_el.select('p:nth-of-type(2) a')
    for year_el in years_table:
        # Save the year for reference
        year_text = year_el.get_text(strip=True)
        if year_text not in jihomor_years:
            jihomor_years[year_text] = []

        # Go to the year
        year_url = BASE_POLICE_URL + year_el.get('href')
        year_bytes = await get_bytes(year_url, session, semaphore, gov_site=True)

        # Create new soup and get the next link.
        # The page here has only one link :)))
        jihomor_soup = BeautifulSoup(year_bytes, 'lxml')
        next_link = BASE_POLICE_URL + jihomor_soup.select_one('div.infobox a').get('href')

        # Go to the final url and get the links
        next_bytes = await get_bytes(next_link, session, semaphore, gov_site=True)
        jihomor_soup2 = BeautifulSoup(next_bytes, 'lxml')

        years_table = jihomor_soup2.select_one('div#content p:nth-of-type(2)')
        for link in years_table.find_all('a'):
            # Go over each link and add it to the 'jihomor_years' dict
            year_link = BASE_POLICE_URL + link.get('href')
            jihomor_years[year_text].append(year_link)

    return jihomor_years


def select_years_table(domain: str, url: str, soup: BeautifulSoup) -> ResultSet[Tag] | None:
    """ Find the correct years table element on the archive page """

    # TODO IF ZLIN OR VYS ==> SELECT A DIFFERENT TABLE
    years_table = soup.select(POLICE_SELECTOR['archive_selectors']['year_links'])
    if not years_table:
        # Try the most common selectors first
        for i, og_selector in enumerate(TABLE_SELECTORS):
            years_table = soup.select(og_selector)
            if years_table:
                logger.debug(f'Found the years element selector on attempt {i + 1} for url: "{url}"...')
                return years_table

        # Next try the special cases
        for municipalities, selector in DOMAIN_SELECTORS.items():
            muni_list = [municipalities] if isinstance(municipalities, str) else municipalities
            # Check against the possible municipalities
            if any(muni in domain for muni in muni_list):
                years_table = soup.select(selector)
                # if not years_table:
                #     logger.error(f"Table parse failed for url '{url}'")
                #     return None
                return years_table

    # Just return the original
    return years_table


async def parse_archive(
    archive_bytes: bytes,
    url: str,
    domain: str,
    session: ClientSession,
    semaphore: Semaphore
) -> YearLinks | None :
    """ Parse the archive page to return the year links  """

    soup = BeautifulSoup(archive_bytes, 'lxml')
    years_table = select_years_table(domain, url, soup)

    # Jihomor needs it's own logic
    if 'Jihomor' in domain and not years_table:
        # Worst case, parse separately then validate
        jihomor_years = await parse_jihomor_archive(soup, session, semaphore)
        logger.debug(f"Validating jihomor links...")
        all_years = jihomor_years
        validated = await validate_year_links(jihomor_years, url, session, semaphore)

    else:
        # Process all other domains, parse the YearLinks, then validate
        all_years = process_year_elements(years_table, url)
        logger.debug(f"Validating year links for url '{url}'...")
        validated = await validate_year_links(all_years, url, session, semaphore)

    if validated:
        logger.debug(f"Success validating year links for url '{url}'...")
    else:
        logger.error(f"Failed to validate year links for url '{url}', returning None...")
        return None

    return all_years


async def scrape_archive(
    url: str,
    domain: str,
    session: ClientSession,
    semaphore: Semaphore
) -> tuple[str, YearLinks] | None:
    """ Main function. \n
        Returns a tuple of (url, YearLinks), where YearLinks contain article listings for the archive years.
    """

    try:
        logger.debug(f"Parsing {domain} for year links...")
        page_bytes = await get_bytes(url=url, session=session, semaphore=semaphore, gov_site=True)
        if page_bytes is None:
            logger.error(f"Couldn't get the main content from '{url}'...")
            return None

        all_years = await parse_archive(page_bytes, url, domain, session, semaphore)
        logger.info(f"Found {len(all_years)} years in '{url}'")

        return domain, all_years

    except Exception:
        logger.exception(f"Error parsing '{url}'")
        raise
