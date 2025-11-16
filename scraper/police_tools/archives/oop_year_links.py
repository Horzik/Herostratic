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
from config import POLICE_ARCHIVES_FP, YEAR_LINKS_FP, LOG_DIR, ERRORS_LOG_FP
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


    def process_archive_results(self, archive_jobs: list, archive_results: list) -> tuple:
        """ Process all archive results from parsing the archive pages. \n
            Return the target sites and number of failed tasks.
        """

        sites = {}
        failed_archives = 0 # todo return the actual failed archive, not just int
        # Get the domains from tasks, check and process each result
        for (domain, _), arch_result in zip(archive_jobs, archive_results):
            if isinstance(arch_result, Exception):
                self.logger.error(f"Error for archive task for domain: '{domain}'...")
                self.logger.error(f"Archive result:: {arch_result}")
                failed_archives += 1
                continue
            if arch_result is None:
                self.logger.error(f"Error: domain '{domain}' returns {arch_result}....")
                failed_archives += 1
                continue

            domain, year_links = arch_result
            sites.setdefault(domain, []).append(year_links)
            # if domain not in sites:
            #     sites[domain] = {}
            # sites[domain].update(year_links)

        # Write for debug and clarity (not actually part of the pipe)
        self.logger.debug(f"Writing year links results....")
        with open(YEAR_LINKS_FP, 'w') as f:
            json.dump(sites, f, ensure_ascii=False, indent=2)

        self.logger.debug(f"Results:: Found {len(sites)} sites:: {sites}")
        return sites, failed_archives


    def process_year_elements(self, year_table: ResultSet[Tag], url: str) -> dict:
        """ Process the target 'year link' table for year links """

        all_years: dict = {}
        for element in year_table:
            year_href = element.get('href')
            if year_href.startswith('http'): # Some refs have the base url already
                year_link = year_href
            else: # While others don't
                year_link = BASE_POLICE_URL + year_href

            if not year_link:
                self.logger.error(f"Missing year_link for url: '{url}'...")
                self.logger.error(f"The failed year element: {element}")
                continue

            year_text = element.get_text(strip=True)
            try:
                match = re.search(r'\b(20\d{2})\b', year_text) # Get only the year from the text
                if not match:
                    continue
                year = match.group(1)

                if year not in all_years:
                    all_years[year] = []
                all_years[year].append(year_link)

            except ValueError:
                self.logger.exception(f"Failed to parse year '{year_text}' ...")
                raise

        if (len(all_years)) == 0:
            self.logger.error(f"Couldn't find any year links in: '{url}'...")
            self.logger.error(f"The failed field table ::: {year_table}")
            raise ValueError("No year links found")

        return all_years


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
                    if not pager:
                        self.logger.error(f"Failed validating year link '{link}' for year '{year}'")
                        self.errors.append(f"Failed year link '{link}' for year '{year}'")
                        return False
                    self.pages_scraped += 1
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

        # TODO IF ZLIN OR VYS ==> SELECT A DIFFERENT TABLE
        years_table = soup.select(POLICE_SELECTOR['archive_selectors']['year_links'])
        if not years_table:
            # Try the most common selectors first
            for i, og_selector in enumerate(TABLE_SELECTORS):
                years_table = soup.select(og_selector)
                if years_table:
                    self.logger.debug(f'Found the years element selector on attempt {i + 1} for url: "{url}"...')
                    return years_table

            # Next try the special cases
            for municipalities, selector in DOMAIN_SELECTORS.items():
                muni_list = [municipalities] if isinstance(municipalities, str) else municipalities
                # Check against the possible municipalities
                if any(muni in domain for muni in muni_list):
                    years_table = soup.select(selector)
                    # if not years_table:
                    #     self.logger.error(f"Table parse failed for url '{url}'")
                    #     return None
                    return years_table

        # Just return the original
        return years_table

    # async def parse_domain(self, domain, url, soup):
    #     if "Informační servis" in domain or "hl. m. Praha" in domain:
    #         # These two have ONLY the year links
    #         years_table = self.select_years_table(domain, url, soup)
    #         return self.process_year_elements(years_table, url)
    #
    #     if "Plzeňský kraj" in domain:
    #         async def plzen_year_links():
    #             plz_years_table = self.select_years_table(domain, url, soup)
    #             return self.process_year_elements(plz_years_table, url)
    #
    #         async def plzen_non_year_links():
    #             plzen_non_years = []
    #             first_list_el = soup.select_one('div#content ul:nth-of-type(1)')
    #             first_list = first_list_el.find_all('a')
    #             for link in first_list:
    #                 link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
    #                 plzen_non_years.append(link_url)
    #
    #             second_list_el = soup.select_one('div#content ul:nth-of-type(2)')
    #             second_list_a = second_list_el.find_all('a')
    #             for link in second_list_a:
    #                 link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
    #                 plzen_non_years.append(link_url)
    #
    #             return plzen_non_years
    #
    #         plzen_links: dict = await plzen_year_links()
    #         plzen_links["non_years"] = await plzen_non_year_links()
    #         return plzen_links
    #
    #     if "Středočeský kraj" in domain:
    #         async def stredo_year_links():
    #             arch_el = soup.select_one('a[title="Archiv zpravodajství"]')
    #             arch_link = urljoin(BASE_POLICE_URL, arch_el.get('href').lstrip('/'))
    #             arch_bytes = await self.fetch(arch_link)
    #             arch_soup = BeautifulSoup(arch_bytes, 'lxml')
    #
    #             stredo_years_table = self.select_years_table(domain, arch_link, arch_soup)
    #             return self.process_year_elements(stredo_years_table, arch_link)
    #
    #         async def stredo_non_year_links():
    #                 stredo_non_years = []
    #                 list_el = soup.select_one('div#content ul:nth-of-type(1)')
    #                 list_a = list_el.find_all('a')
    #                 for link in list_a:
    #                     link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
    #                     if "archiv" in link_url: # Skip the year archive link
    #                         continue
    #                     stredo_non_years.append(link_url)
    #                 return stredo_non_years
    #
    #         stredo_links: dict = await stredo_year_links()
    #         stredo_links["non_years"] = await stredo_non_year_links()
    #         return stredo_links
    #
    #     if "Jihočeský kraj" in domain:
    #         async def jiho_year_links():
    #             arch_el = soup.select_one('a[title="Zpravodajství - archiv"]')
    #             arch_link = urljoin(BASE_POLICE_URL, arch_el.get('href').lstrip('/'))
    #             arch_bytes = await self.fetch(arch_link)
    #             arch_soup = BeautifulSoup(arch_bytes, 'lxml')
    #
    #             stredo_years_table = self.select_years_table(domain, arch_link, arch_soup)
    #             return self.process_year_elements(stredo_years_table, arch_link)
    #
    #         async def jiho_non_year_links():
    #             jiho_non_years = []
    #             first_list_el = soup.select_one('div#content ul:nth-of-type(1)')
    #             first_list = first_list_el.find_all('a')
    #             for link in first_list:
    #                 link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
    #                 if "archiv" in link_url:  # Skip the year archive link
    #                     continue
    #                 jiho_non_years.append(link_url)
    #
    #             second_list_el = soup.select_one('div#content ul:nth-of-type(2)')
    #             second_list_a = second_list_el.find_all('a')
    #             for link in second_list_a:
    #                 link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
    #                 jiho_non_years.append(link_url)
    #
    #             return jiho_non_years
    #
    #         jiho_links: dict = await jiho_year_links()
    #         jiho_links["non_years"] = await jiho_non_year_links()
    #         return jiho_links
    #
    #     if "Jihomor" in domain:
    #         async def jihomor_year_links():
    #             arch_element = soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
    #             arch_link = urljoin(BASE_POLICE_URL, arch_element.get('href').lstrip('/'))
    #             arch_bytes = await self.fetch(arch_link)
    #             arch_soup = BeautifulSoup(arch_bytes, 'lxml')
    #             return await self.parse_jihomor_archive(arch_soup)
    #
    #         async def jihomor_non_year_links():
    #             jihomor_non_years_links = []
    #             list_element = soup.select_one('div#content ul')
    #             arch_elements = list_element.find_all('a')
    #             for link in arch_elements:
    #                 link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
    #                 if 'archiv' in link_url: # Skip the year archive link
    #                     continue
    #                 jihomor_non_years_links.append(link_url)
    #             return jihomor_non_years_links
    #
    #         jihomor_links: dict = await jihomor_year_links()
    #         jihomor_links["non_years"] = await jihomor_non_year_links()
    #         return jihomor_links
    #
    #     self.logger.error(f"Error: failed getting links for {domain}, returning an empty dict...")
    #     return {}

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
        await self.write_results(sites)
        duration = timedelta(seconds=time.perf_counter() - start_time)
        self.logger.info(f"Finished in {duration}, "
                         f"validated {self.pages_scraped - len(self.errors)}/{self.pages_scraped} links, "
                         f"exiting...")


async def main() -> None:
    async with YearLinksScraper() as scr:
        try:
            await scr.run()
        finally:
            destroy()


if __name__ == '__main__':
    asyncio.run(main())


