import asyncio
import re
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup, Tag, ResultSet
from logging import Logger
from urllib.parse import urljoin

from config import EXCLUDE_ARCHIVE_KEYWORDS, EXCLUDE_SOCIAL_KEYWORDS
from scraper.core import BaseScraper
from scraper.site_configs import BASE_POLICE_URL, POLICE_ARCHIVE_SELECTORS, POLICE_SELECTOR, MUNICIPALITY_SELECTORS, \
    TABLE_SELECTORS


class MunicipalityParser(ABC):
    ARCHIVE_SELECTOR = POLICE_ARCHIVE_SELECTORS['content_archiv']
    BASE_URL = BASE_POLICE_URL
    EXCL_ARCH_WORD = 'archiv' # todo revisit this, there was a legit reason for this but make sure it's correct

    def __init__(self, scraper, municipality, url, soup, logger):
        self.scraper: BaseScraper = scraper
        self.municipality: str = municipality
        self.url: str = url
        self.soup: BeautifulSoup = soup
        self.logger: Logger = logger


    @abstractmethod
    async def parse(self) -> dict:
        """ The main method with which we start the municipality parsing. """
        raise NotImplementedError


    def _mk_url(self, link: Tag) -> str:
        """ Join 'BASE_URL' with the href of an element """
        return urljoin(self.BASE_URL, link.get('href').lstrip('/'))


    async def get_non_year_links(self) -> list:
        raise NotImplementedError


    async def get_year_links(self) -> dict:
        """Common year link extraction - can be overridden"""
        arch_element = self.soup.select_one(self.ARCHIVE_SELECTOR)
        arch_link = urljoin(BASE_POLICE_URL, arch_element.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')

        years_table = self.select_years_table(self.municipality, arch_soup)
        return self.process_year_elements(years_table, self.url)


    def append_links_from_elements(self, el_list, links_list, remove_arch_links = True) -> list:
        """ Append the processed urls to the provided list, return that list """
        for link_el in el_list:
            link_url = self._mk_url(link_el)
            if remove_arch_links and self.EXCL_ARCH_WORD in link_url.lower():
                continue
            links_list.append(link_url)

        return links_list


    def process_year_elements(self, year_table: ResultSet[Tag], url: str) -> dict[int | str, list[str]]:
        """ Process the target 'year link' table for year links """
        all_year_links = self.parse_year_table(year_table, url)
        if (len(all_year_links)) == 0:
            self.logger.error(f"Couldn't find any year links in: '{url}'...")
            self.logger.error(f"The failed field table ::: {year_table}")
            raise ValueError("No year links found")
        # self.logger.debug(f"All processed year links:: ${all_year_links}")
        return all_year_links


    def parse_year_table(self, year_table: ResultSet[Tag], url) -> dict[str, list[str]]:
        all_year_links: dict[str, list[str]] = {}
        for element in year_table:
            year_href = element.get('href')
            year_link = year_href if year_href.startswith('http') else urljoin(self.BASE_URL, year_href)
            if not year_link:
                self.logger.error(f"Missing year_link for url: '{url}'...")
                self.logger.error(f"The failed year element: {element}")
                continue

            # Skip 'nehody'/'nasilne' and 'media' links
            if any(key in year_link for key in EXCLUDE_ARCHIVE_KEYWORDS):
                continue
            if any(key in year_link for key in EXCLUDE_SOCIAL_KEYWORDS): # Skip media links
                continue

            year_text = element.get_text(strip=True)
            try: # This try block was quite helpful for debugging
                year_match = re.search(r'\b(20\d{2})\b', year_text) # Find the actual numbers
                year = year_match.group(1) if year_match else "???"
                if year not in all_year_links:
                    all_year_links[year] = []
                all_year_links[year].append(year_link)
            except ValueError:
                self.logger.exception(f"Failed to parse year '{year_text}' ...")
                raise

        for year in all_year_links: # Dedupe and return
            all_year_links[year] = list(dict.fromkeys(all_year_links[year]))
        return all_year_links


    def select_years_table(self, municipality: str, soup: BeautifulSoup) -> ResultSet[Tag] | None:
        """ Find the correct years table element on the archive page.
        """
        for muni_key, selector in MUNICIPALITY_SELECTORS.items():
            if muni_key in municipality:
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

        self.logger.error(f"Could not find year table for municipality '{municipality}'")
        return None


    async def parse_jihomor_archive(self, soup: BeautifulSoup) -> dict:
        """ Separate parsing strategy because we love the police HTML. \n
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
            year_bytes = await self.scraper.fetch(year_url, gov_site=True)

            # This page has only one link, go to it :)
            jihomor_soup = BeautifulSoup(year_bytes, 'lxml')
            next_link = BASE_POLICE_URL + jihomor_soup.select_one('div.infobox a').get('href')

            # Go to the final url and get the links
            next_bytes = await self.scraper.fetch(next_link, gov_site=True)
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


class OnlyYearLinksParser(MunicipalityParser):
    async def parse(self) -> dict:
        return await self.get_year_links()

    async def get_year_links(self) -> dict:
        years_table = self.select_years_table(self.municipality, self.soup)
        return self.process_year_elements(years_table, self.url)


class AllLinksParser(MunicipalityParser):
    async def parse(self) -> dict:
        links = await self.get_year_links()
        links["non_years"] = await self.get_non_year_links()
        return links

    async def get_non_year_links(self) -> list:
        raise NotImplementedError


class PlzenParser(AllLinksParser):
    """ Plzen has years directly on the main page, no archive fetch needed.
    """
    async def get_year_links(self) -> dict:
        years_table = self.select_years_table(self.municipality, self.soup)
        return self.process_year_elements(years_table, self.url)

    async def get_non_year_links(self) -> list:
        non_years = []
        for ul_index in [1, 2]:
            list_el = self.soup.select_one(f'div#content ul:nth-of-type({ul_index})')
            for link_el in list_el.find_all('a'):
                link_url = self._mk_url(link_el)
                non_years.append(link_url)

        return non_years


class StredoParser(AllLinksParser):
    ARCHIVE_SELECTOR = 'a[title="Archiv zpravodajství"]'

    async def get_non_year_links(self):
        stredo_non_years = []
        target_el = self.soup.select_one('div#content ul:nth-of-type(1)')
        el_list = target_el.find_all('a')
        stredo_non_years = self.append_links_from_elements(el_list, stredo_non_years)
        return stredo_non_years


class JihocesParser(AllLinksParser):
    async def get_non_year_links(self):
        jihoces_non_years = []
        first_target_el = self.soup.select_one('div#content ul:nth-of-type(1)')
        el_list = first_target_el.find_all('a')
        jihoces_non_years = self.append_links_from_elements(el_list, jihoces_non_years)

        second_target_el = self.soup.select_one('div#content ul:nth-of-type(2)')
        second_el_list = second_target_el.find_all('a')
        jihoces_non_years = self.append_links_from_elements(second_el_list, jihoces_non_years)
        return jihoces_non_years


class KarlovarParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        karlovar_non_years = []
        first_link_el = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['zpravodajstvi'])
        first_link_url = self._mk_url(first_link_el)
        karlovar_non_years.append(first_link_url)

        target_el = self.soup.select_one('div#content ul')
        el_list = target_el.find_all('a')
        karlovar_non_years = self.append_links_from_elements(el_list, karlovar_non_years)
        return karlovar_non_years


class UstecParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        ustec_non_years = []
        el_list = self.soup.select('table a')

        for link_el in el_list:
            link_text = link_el.get_text(strip=True)
            # Special cases for a special case :)
            if 'Územní' not in link_text and 'Krajské' not in link_text: # Get only the non year links
                continue
            link_url = self._mk_url(link_el)
            ustec_non_years.append(link_url)

        return ustec_non_years


class LiberecParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        liberec_non_years = []
        el_list = self.soup.select('div#content p:not(.right.actions) a') # Don't select the social media links
        liberec_non_years = self.append_links_from_elements(el_list, liberec_non_years)
        return liberec_non_years


class KraloveParser(OnlyYearLinksParser):
    """Kralovehradecky has only the year links, not archive fetch needed."""
    async def get_year_links(self) -> dict:
        first_link_el = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['zpravodajstvi'])
        first_year_text = re.search(r'\b(20\d{2})\b', first_link_el.get_text(strip=True)).group(1)
        first_link_url = self._mk_url(first_link_el)

        years_table = self.soup.select('div#content > table')[0].select('a')  # Select the FIRST table directly
        kralove_year_links = self.process_year_elements(years_table, self.url)
        kralove_year_links[first_year_text] = [first_link_url]
        return kralove_year_links


class PardubicParser(AllLinksParser):
    """ Pardubicky has only the year links, not archive fetch needed.
    """
    async def get_non_year_links(self) -> list:
        pardubic_non_years = []
        el_list = self.soup.select('div#content ul a')
        pardubic_non_years = self.append_links_from_elements(el_list, pardubic_non_years )
        return pardubic_non_years


class VysoParser(AllLinksParser):
    """ Vyso has years directly on the main page, no archive fetch needed.
    """
    async def get_year_links(self) -> dict:
        years_table = self.select_years_table(self.municipality, self.soup)
        return self.process_year_elements(years_table, self.url)

    async def get_non_year_links(self) -> list:
        vyso_non_years = []
        first_link_el = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['zpravodajstvi'])
        first_link_url = self._mk_url(first_link_el)
        vyso_non_years.append(first_link_url)

        target_el = self.soup.select_one('div#content ul:nth-of-type(2)')
        el_list = target_el.find_all('a')
        vyso_non_years = self.append_links_from_elements(el_list, vyso_non_years, remove_arch_links=False)
        return vyso_non_years


class JihomorParser(AllLinksParser):
    """ Jiho has years directly on the main page, and is kinda fucked (hence 'parse_jihomor_archive').
    """
    async def get_year_links(self):
        arch_element = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
        arch_link = urljoin(BASE_POLICE_URL, arch_element.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')
        return await self.parse_jihomor_archive(arch_soup)

    async def get_non_year_links(self):
        jihomor_non_years_links = []
        target_el = self.soup.select_one('div#content ul')
        el_list = target_el.find_all('a')
        jihomor_non_years_links = self.append_links_from_elements(el_list, jihomor_non_years_links)
        return jihomor_non_years_links


class ZlinParser(AllLinksParser):
    async def get_year_links(self) -> dict:
        """Zlin has years directly on the main page, no archive fetch needed"""
        years_table = self.select_years_table(self.municipality, self.soup)
        return self.process_year_elements(years_table, self.url)

    async def get_non_year_links(self) -> list:
        zlin_non_years = []
        first_link_el = self.soup.select_one('ul li strong a')
        first_link_url = self._mk_url(first_link_el)
        zlin_non_years.append(first_link_url)

        nested_links = self.soup.select('ul:nth-of-type(2) ul a')
        zlin_non_years = self.append_links_from_elements(nested_links, zlin_non_years, remove_arch_links=False)
        return zlin_non_years


class OlomoucParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        olomouc_non_years = []
        el_list = self.soup.select('div#content ul:nth-of-type(1) a')
        olomouc_non_years = self.append_links_from_elements(el_list, olomouc_non_years)

        second_el_list = self.soup.select('div#content ul:nth-of-type(2) a')
        olomouc_non_years = self.append_links_from_elements(second_el_list, olomouc_non_years)
        return list(set(olomouc_non_years))


class MoravskoslezParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        moravskoslez_non_years = []
        el_list = self.soup.select('div#content ul:nth-of-type(1) a')
        moravskoslez_non_years = self.append_links_from_elements(el_list, moravskoslez_non_years)

        second_el_list = self.soup.select('div#content ul:nth-of-type(2) a')
        moravskoslez_non_years = self.append_links_from_elements(second_el_list, moravskoslez_non_years)
        return list(set(moravskoslez_non_years))


MUNICIPALITY_PARSERS = {
    "Informační": OnlyYearLinksParser,
    "hl. m. Praha": OnlyYearLinksParser,
    "Plzeňský": PlzenParser,
    "Středočeský": StredoParser,
    "Jihočeský": JihocesParser,
    "Karlovar": KarlovarParser,
    "Ústecký": UstecParser,
    "Liberec": LiberecParser,
    "Králové": KraloveParser,
    "Pardubic": PardubicParser,
    "Vyso": VysoParser,
    "Jihomor": JihomorParser,
    "Zlín": ZlinParser,
    "Olomouc": OlomoucParser,
    "Moravskoslez": MoravskoslezParser}
