import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from scraper.site_configs import BASE_POLICE_URL, POLICE_ARCHIVE_SELECTORS


class MunicipalityParser:
    ARCHIVE_SELECTOR = POLICE_ARCHIVE_SELECTORS['content_archiv']

    def __init__(self, scraper, domain, url, soup):
        self.scraper = scraper
        self.domain = domain
        self.url = url
        self.soup = soup

    async def parse(self) -> dict:
        raise NotImplementedError

    async def get_non_year_links(self) -> list:
        raise NotImplementedError

    async def get_year_links(self) -> dict:
        """Common year link extraction - can be overridden"""

        arch_element = self.soup.select_one(self.ARCHIVE_SELECTOR)
        arch_link = urljoin(BASE_POLICE_URL, arch_element.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')

        years_table = self.scraper.select_years_table(self.domain, self.url, arch_soup)
        return self.scraper.process_year_elements(years_table, self.url)


class OnlyYearLinksParser(MunicipalityParser):

    async def parse(self) -> dict:
        return await self.get_year_links()

    async def get_year_links(self) -> dict:
        years_table = self.scraper.select_years_table(self.domain, self.url, self.soup)
        return self.scraper.process_year_elements(years_table, self.url)


class AllLinksParser(MunicipalityParser):

    async def get_non_year_links(self) -> list:
        raise NotImplementedError

    async def parse(self) -> dict:
        links = await self.get_year_links()
        links["non_years"] = await self.get_non_year_links()
        return links


class PlzenParser(AllLinksParser):

    async def get_year_links(self) -> dict:
        """Plzen has years directly on the main page, no archive fetch needed"""
        years_table = self.scraper.select_years_table(self.domain, self.url, self.soup)
        return self.scraper.process_year_elements(years_table, self.url)

    async def get_non_year_links(self) -> list:
        non_years = []
        for ul_index in [1, 2]:
            list_el = self.soup.select_one(f'div#content ul:nth-of-type({ul_index})')
            for link in list_el.find_all('a'):
                link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
                non_years.append(link_url)
        return non_years


class StredoParser(AllLinksParser):
    ARCHIVE_SELECTOR = 'a[title="Archiv zpravodajství"]'

    async def get_non_year_links(self):
        stredo_non_years = []
        list_el = self.soup.select_one('div#content ul:nth-of-type(1)')
        list_a = list_el.find_all('a')
        for link in list_a:
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            if "archiv" in link_url:  # Skip the year archive link
                continue
            stredo_non_years.append(link_url)
        return stredo_non_years


class JihocesParser(AllLinksParser):

    async def get_non_year_links(self):
        jihoces_non_years = []
        first_list_el = self.soup.select_one('div#content ul:nth-of-type(1)')
        first_list = first_list_el.find_all('a')
        for link in first_list:
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            if "archiv" in link_url:  # Skip the year archive link
                continue
            jihoces_non_years.append(link_url)

        second_list_el = self.soup.select_one('div#content ul:nth-of-type(2)')
        second_list_a = second_list_el.find_all('a')
        for link in second_list_a:
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            jihoces_non_years.append(link_url)
        return jihoces_non_years


class KarlovarParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        karlovar_non_years = []
        first_link_el = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['zpravodajstvi'])
        first_link_url = urljoin(BASE_POLICE_URL, first_link_el.get('href').lstrip('/'))
        karlovar_non_years.append(first_link_url)

        list_el = self.soup.select_one('div#content ul')
        arch_elements = list_el.find_all('a')
        for link in arch_elements:
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            if 'archiv' in link_url: # Skip the year archive link
                continue
            karlovar_non_years.append(link_url)
        return karlovar_non_years


class UstecParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        ustec_non_years = []
        links = self.soup.select('table a')
        for link in links:
            link_text = link.get_text(strip=True)
            if 'Územní' not in link_text and 'Krajské' not in link_text: # Get only the non year links
                continue
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            ustec_non_years.append(link_url)
        return ustec_non_years


class LiberecParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        liberec_non_years = []
        links = self.soup.select('div#content p:not(.right.actions) a') # Don't select the social media links
        for link in links:
            link_text = link.get_text(strip=True)
            if 'Archiv' in link_text: # Get only the non year links
                continue
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            liberec_non_years.append(link_url)
        return liberec_non_years


class KraloveParser(OnlyYearLinksParser):
    """Kralovehradecky has only the year links, not archive fetch needed."""
    async def get_year_links(self) -> dict:
        first_link_el = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['zpravodajstvi'])
        first_year_text = re.search(r'\b(20\d{2})\b', first_link_el.get_text(strip=True)).group(1)
        first_link_url = urljoin(BASE_POLICE_URL, first_link_el.get('href').lstrip('/'))

        years_table = self.soup.select('div#content > table')[0].select('a')  # Select the FIRST table directly
        kralove_year_links = self.scraper.process_year_elements(years_table, self.url)
        kralove_year_links[first_year_text] = first_link_url
        return kralove_year_links


class PardubicParser(AllLinksParser):
    """Pardubicky has only the year links, not archive fetch needed."""
    async def get_non_year_links(self) -> list:
        pardubic_non_years = []
        links = self.soup.select('div#content ul a')
        for link in links:
            link_text = link.get_text(strip=True)
            if 'Archiv' in link_text: # Get only the non year links
                continue
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            pardubic_non_years.append(link_url)
        return pardubic_non_years


class VysoParser(AllLinksParser):
    async def get_year_links(self) -> dict:
        """Vyso has years directly on the main page, no archive fetch needed"""
        years_table = self.scraper.select_years_table(self.domain, self.url, self.soup)
        return self.scraper.process_year_elements(years_table, self.url)

    async def get_non_year_links(self) -> list:
        vyso_non_years = []
        first_link_el = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['zpravodajstvi'])
        first_link_url = urljoin(BASE_POLICE_URL, first_link_el.get('href').lstrip('/'))
        vyso_non_years.append(first_link_url)

        list_el = self.soup.select_one('div#content ul:nth-of-type(2)')
        arch_elements = list_el.find_all('a')
        for link in arch_elements:
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            vyso_non_years.append(link_url)
        return vyso_non_years


class JihomorParser(AllLinksParser):
    async def get_year_links(self):
        """Jiho has years directly on the main page, and is kinda fucked (hence 'parse_jihomor_archive')"""
        arch_element = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
        arch_link = urljoin(BASE_POLICE_URL, arch_element.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')
        return await self.scraper.parse_jihomor_archive(arch_soup)

    async def get_non_year_links(self):
        jihomor_non_years_links = []
        list_element = self.soup.select_one('div#content ul')
        arch_elements = list_element.find_all('a')
        for link in arch_elements:
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            if 'archiv' in link_url:  # Skip the year archive link
                continue
            jihomor_non_years_links.append(link_url)
        return jihomor_non_years_links


class ZlinParser(AllLinksParser):
    async def get_year_links(self) -> dict:
        """Zlin has years directly on the main page, no archive fetch needed"""
        years_table = self.scraper.select_years_table(self.domain, self.url, self.soup)
        return self.scraper.process_year_elements(years_table, self.url)

    async def get_non_year_links(self) -> list:
        zlin_non_years = []
        first_link = self.soup.select_one('ul li strong a')
        first_link_url = urljoin(BASE_POLICE_URL, first_link.get('href').lstrip('/'))
        zlin_non_years.append(first_link_url)

        nested_links = self.soup.select('ul:nth-of-type(2) ul a')
        for link in nested_links:
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            zlin_non_years.append(link_url)

        return zlin_non_years


class OlomoucParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        olomouc_non_years = []
        first_list = self.soup.select('div#content ul:nth-of-type(1) a')
        for element in first_list:
            link_url = urljoin(BASE_POLICE_URL, element.get('href').lstrip('/'))
            if 'archiv' in link_url:
                continue
            olomouc_non_years.append(link_url)

        second_list = self.soup.select('div#content ul:nth-of-type(2) a')
        for element in second_list:
            link_url = urljoin(BASE_POLICE_URL, element.get('href').lstrip('/'))
            olomouc_non_years.append(link_url)
        return list(set(olomouc_non_years))


class MoravskoslezParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        moravskoslez_non_years = []
        first_list = self.soup.select('div#content ul:nth-of-type(1) a')
        for element in first_list:
            link_url = urljoin(BASE_POLICE_URL, element.get('href').lstrip('/'))
            if 'archiv' in link_url:
                continue
            moravskoslez_non_years.append(link_url)

        second_list = self.soup.select('div#content ul:nth-of-type(2) a')
        for element in second_list:
            link_url = urljoin(BASE_POLICE_URL, element.get('href').lstrip('/'))
            moravskoslez_non_years.append(link_url)
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
    "Moravskoslez": MoravskoslezParser,
}