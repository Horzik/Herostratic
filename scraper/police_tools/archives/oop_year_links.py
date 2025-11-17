import asyncio
import json
import logging
import re
import time
from asyncio import gather
from datetime import timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup, ResultSet, Tag

from scraper.core import BaseScraper
from scraper.police_tools.archives.municipality_strategies import MUNICIPALITY_PARSERS
from utils.logger import LogConfig, destroy
from config import POLICE_ARCHIVES_FP, YEAR_LINKS_FP, LOG_DIR, ERRORS_LOG_FP, EXCLUDE_ARCHIVE_KEYWORDS, \
    EXCLUDE_SOCIAL_KEYWORDS
from scraper.site_configs import BASE_POLICE_URL, POLICE_SELECTOR, TABLE_SELECTORS, DOMAIN_SELECTORS, \
    POLICE_ARCHIVE_SELECTORS


class YearLinksScraper(BaseScraper):
    MODULE_NAME = "year_links"
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_ARCHIVES_FP
    OUTPUT_FILE = YEAR_LINKS_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 30
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'year_links.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        self.validated_links = 0


    def process_archive_results(self, archive_jobs: list, archive_results: list) -> tuple:
        """ Process all archive results from parsing the archive pages. \n
            Return the target sites and number of failed tasks.
        """
        sites = {}
        failed_archives = 0 # todo return the actual failed archive, not just int
        # Get the domains from tasks, check and process each result
        for (domain, huh), arch_result in zip(archive_jobs, archive_results):
            if isinstance(arch_result, Exception):
                self.logger.error(f"Error for archive task for domain: '{domain}'...")
                self.logger.error(f"Task '{huh}', result:: {arch_result}")
                self.errors.append(f"Domain '{domain}' failed. Task::'{huh}'. Result:: '{arch_result}'")
                self.pages_scraped += 1

                failed_archives += 1
                continue
            if arch_result is None:
                self.logger.error(f"Error: domain '{domain}' returns {arch_result}....")
                failed_archives += 1
                self.pages_scraped += 1

                continue

            domain, year_links = arch_result
            sites.setdefault(domain, []).append(year_links)
            self.pages_scraped += 1

        # # Write for debug and clarity (not actually part of the pipe)
        # self.logger.debug(f"Writing year links results....")
        # with open(YEAR_LINKS_FP, 'w') as f:
        #     json.dump(sites, f, ensure_ascii=False, indent=2)

        self.logger.debug(f"Results:: Found {len(sites)} sites:: {sites}")
        return sites, failed_archives


    def process_year_elements(self, year_table: ResultSet[Tag], url: str) -> dict:
        """ Process the target 'year link' table for year links """
        all_year_links: dict = {}
        for element in year_table:
            year_href = element.get('href')

            if year_href.startswith('http'):
                # Some refs have the base url already
                year_link = year_href
            else:
                # While others don't
                year_link = BASE_POLICE_URL + year_href

            if not year_link:
                self.logger.error(f"Missing year_link for url: '{url}'...")
                self.logger.error(f"The failed year element: {element}")
                continue
            if any(key in year_link for key in EXCLUDE_ARCHIVE_KEYWORDS): # Skip "nehody" archives and 'nasilne'
                continue
            if any(key in year_link for key in EXCLUDE_SOCIAL_KEYWORDS): # Skip media links
                continue

            year_text = element.get_text(strip=True)
            try:
                year_match = re.search(r'\b(20\d{2})\b', year_text) # Get only the year from the text
                if not year_match:
                    year = "???"
                else:
                    year = year_match.group(1)

                if year not in all_year_links:
                    all_year_links[year] = []
                all_year_links[year].append(year_link)

                for year in all_year_links: # Dedupe
                    all_year_links[year] = list(dict.fromkeys(all_year_links[year]))

            except ValueError:
                self.logger.exception(f"Failed to parse year '{year_text}' ...")
                raise

        if (len(all_year_links)) == 0:
            self.logger.error(f"Couldn't find any year links in: '{url}'...")
            self.logger.error(f"The failed field table ::: {year_table}")
            raise ValueError("No year links found")
        self.logger.debug(f"All processed year links:: ${all_year_links}")
        return all_year_links


    async def validate_links(self, all_years: dict, url: str) -> bool:
        """ Gets the content of each link and verifies it contains the article listings. \n
            Note. Does not produce or read any stats, just checks...
        """
        try:
            for year, link_or_links in all_years.items():
                # Handle both single URL and list of URLs
                links = [link_or_links] if isinstance(link_or_links, str) else link_or_links
                for link in links:
                    content = await self.fetch(link)
                    if content is None:
                        return False
                    soup = BeautifulSoup(content, 'lxml')
                    # Check if there is the page navigation
                    pager = soup.select_one('p.pager')
                    if pager:
                        self.validated_links += 1
                    else:
                        self.logger.error(f"Failed validating year link '{link}' for year '{year}'")
                        return False
            return True
        except Exception:
            self.logger.exception(f"Error for validating year links in url '{url}...'")
            raise


    async def parse_jihomor_archive(self, soup: BeautifulSoup) -> dict:
        """
            Get the year table, and crawl through to get the years links. \n
            First link => Second link => Multiple urls per year.
        """
        jihomor_years: dict = {}
        content_el = soup.select_one(POLICE_SELECTOR['article_selectors']['content'])
        years_table = content_el.select('p:nth-of-type(2) a')

        async def process_jihomor_years(year_el):
            year_text = year_el.get_text(strip=True)
            if year_text not in jihomor_years:
                jihomor_years[year_text] = []

            if year_text == "2009":  # This year just goes directly to the listings
                year_link = BASE_POLICE_URL + year_el.get('href')
                return year_text, [year_link]

            # Go to the year
            year_url = BASE_POLICE_URL + year_el.get('href')
            year_bytes = await self.fetch(year_url)

            # This page has only one link, go to it :)
            jihomor_soup = BeautifulSoup(year_bytes, 'lxml')
            next_link = BASE_POLICE_URL + jihomor_soup.select_one('div.infobox a').get('href')

            # Go to the final url and get the links
            next_bytes = await self.fetch(next_link)
            jihomor_soup2 = BeautifulSoup(next_bytes, 'lxml')

            if year_text == "2008":  # This year has different structure
                years_table_inner = jihomor_soup2.select_one('div#content p:nth-of-type(1)')
            else:
                years_table_inner = jihomor_soup2.select_one('div#content p:nth-of-type(2)')

            year_links = []
            for link in years_table_inner.find_all('a'):
                year_link = BASE_POLICE_URL + link.get('href')
                year_links.append(year_link)
            return year_text, year_links

        results = await asyncio.gather(*[process_jihomor_years(year_el) for year_el in years_table])
        for year, links in results:
            if year:
                jihomor_years[year] = links
        return jihomor_years


    def select_years_table(self, domain: str, url: str, soup: BeautifulSoup) -> ResultSet[Tag] | None:
        """ Find the correct years table element on the archive page """
        # First parse the special cases
        for municipalities, selector in DOMAIN_SELECTORS.items():
            muni_list = [municipalities] if isinstance(municipalities, str) else municipalities
            if any(muni in domain for muni in muni_list):
                years_table = soup.select(selector)
                if years_table:
                    self.logger.debug(f'Using the special years table')
                    return years_table

        # Then try the default one
        years_table = soup.select(POLICE_SELECTOR['archive_selectors']['year_links'])
        if years_table:
            self.logger.debug(f'Using the default years table')
            return years_table

        # Finally try TABLE_SELECTORS
        for i, og_selector in enumerate(TABLE_SELECTORS):
            years_table = soup.select(og_selector)
            if years_table:
                self.logger.debug(f'Using the table_selectors years table')
                return years_table

        self.logger.error(f"Could not find year table for domain '{domain}'")
        return None


    async def parse_domain(self, domain, url, soup):
        for key, parser_class in MUNICIPALITY_PARSERS.items():
            if key in domain:
                parser = parser_class(self, domain, url, soup)
                return await parser.parse()

        self.logger.error(f"No parser found for {domain}, returning empty dict...")
        return {}


    async def parse_archive(self, url: str, domain: str) -> dict | None:
        """ Parse the archive page to return the year links.  """
        archive_bytes = await self.fetch(url)
        if archive_bytes is None:
            self.logger.error(f"Failed fetching content for url '{url}'...")
            return None

        soup = BeautifulSoup(archive_bytes, 'lxml')
        all_links = await self.parse_domain(domain, url, soup)
        if not all_links:
            self.logger.error(f"No links found for domain '{domain}'...")
            return None

        validated = await self.validate_links(all_links, url)
        if validated:
            self.logger.debug(f"Success validating year links for url '{url}'...")
        else:
            self.logger.error(f"Failed to validate year links for url '{url}', returning None...")
            return None

        return all_links


    async def get_all_links(self, url: str, domain: str) -> tuple[str, dict] | None:
        try:
            self.logger.debug(f"Parsing {domain} for year links...")
            all_years = await self.parse_archive(url, domain)
            self.logger.info(f"Found {len(all_years)} years in '{url}'")
            return domain, all_years
        except Exception:
            self.logger.exception(f"Error parsing '{url}'")
            raise


    async def prepare_tasks(self, data_fp) -> list:
        with open(data_fp, "r") as a:
            archives: dict = json.load(a)
        return [
            (domain, self.get_all_links(url, domain)) # Add the domain.
            for domain, urls in archives.items()
            for url in urls
        ]


    async def scrape(self, tasks) -> list:
        return await gather(*[coro for _, coro in tasks],
            return_exceptions=True
        )


    async def run(self) -> None:
        self.logger.info(f"Starting to scrape for archives...")
        start_time = time.perf_counter()
        tasks = await self.prepare_tasks(self.INPUT_FILE)
        self.logger.info(f'Scraping {len(tasks)} archive links....')

        results = await self.scrape(tasks)
        sites, failed_count = self.process_archive_results(tasks, results)
        if failed_count < len(sites):
            await self.write_results(sites) # TODO don't write if something fucks up
        duration = timedelta(seconds=time.perf_counter() - start_time)
        self.logger.info(f"Finished in {duration}, "
                         f"success for {self.pages_scraped - len(self.errors)}/{self.pages_scraped} targets, "
                         f"validated {self.validated_links} links, exiting...")


async def main() -> None:
    async with YearLinksScraper() as scr:
        try:
            await scr.run()
        finally:
            destroy()


if __name__ == '__main__':
    asyncio.run(main())


