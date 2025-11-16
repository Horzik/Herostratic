from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.site_configs import BASE_POLICE_URL, POLICE_ARCHIVE_SELECTORS


class MunicipalityParser:

    def __init__(self, scraper, domain, url, soup):
        self.scraper = scraper
        self.domain = domain
        self.url = url
        self.soup = soup

    async def parse(self) -> dict:
        """Override this in subclasses"""
        raise NotImplementedError

    async def get_non_year_links(self) -> list:
        """Override this to specify how to extract non-year links"""
        raise NotImplementedError

    async def get_year_links(self) -> dict:
        """Common year link extraction - can be overridden"""
        years_table = self.scraper.select_years_table(self.domain, self.url, self.soup)
        return self.scraper.process_year_elements(years_table, self.url)


class OnlyYearLinksParser(MunicipalityParser):
    async def parse(self) -> dict:
        return await self.get_year_links()


class AllLinksParser(MunicipalityParser):
    async def get_non_year_links(self) -> list:
        raise NotImplementedError

    async def parse(self) -> dict:
        links = await self.get_year_links()
        links["non_years"] = await self.get_non_year_links()
        return links


class PlzenParser(AllLinksParser):
    async def get_non_year_links(self) -> list:
        non_years = []
        for ul_index in [1, 2]:
            list_el = self.soup.select_one(f'div#content ul:nth-of-type({ul_index})')
            for link in list_el.find_all('a'):
                link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
                non_years.append(link_url)
            return non_years


class StredoParser(AllLinksParser):
    async def get_year_links(self):
        arch_el = self.soup.select_one('a[title="Archiv zpravodajství"]')
        arch_link = urljoin(BASE_POLICE_URL, arch_el.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')

        stredo_years_table = self.scraper.select_years_table(self.domain, arch_link, arch_soup)
        return self.scraper.process_year_elements(stredo_years_table, arch_link)

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
    async def get_year_links(self):
        arch_el = self.soup.select_one('a[title="Zpravodajství - archiv"]')
        arch_link = urljoin(BASE_POLICE_URL, arch_el.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')

        stredo_years_table = self.scraper.select_years_table(self.domain, arch_link, arch_soup)
        return self.scraper.process_year_elements(stredo_years_table, arch_link)

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


class JihomorParser(AllLinksParser):
    async def get_year_links(self):
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


class KarlovarParser(AllLinksParser):
    async def get_year_links(self):
        arch_element = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
        arch_link = urljoin(BASE_POLICE_URL, arch_element.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')

        karlo_years_table = self.scraper.select_years_table(self.domain, arch_link, arch_soup)
        return self.scraper.process_year_elements(karlo_years_table, arch_link)

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
    async def get_year_links(self):
        arch_element = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
        arch_link = urljoin(BASE_POLICE_URL, arch_element.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')

        ustec_years_table = self.scraper.select_years_table(self.domain, arch_link, arch_soup)
        return self.scraper.process_year_elements(ustec_years_table, arch_link)

    async def get_non_year_links(self) -> list:
        ustec_non_years = []
        links = self.soup.select('table a')
        for link in links:
            link_text = link.get_text(strip=True)
            if 'Územní' not in link_text and 'Krajské' not in link_text: # Get only the relevant links
                continue
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            ustec_non_years.append(link_url)
        return ustec_non_years


class LiberecParser(AllLinksParser):
    async def get_year_links(self):
        arch_element = self.soup.select_one(POLICE_ARCHIVE_SELECTORS['content_archiv'])
        arch_link = urljoin(BASE_POLICE_URL, arch_element.get('href').lstrip('/'))
        arch_bytes = await self.scraper.fetch(arch_link)
        arch_soup = BeautifulSoup(arch_bytes, 'lxml')

        liberec_years_table = self.scraper.select_years_table(self.domain, arch_link, arch_soup)
        return self.scraper.process_year_elements(liberec_years_table, arch_link)

    async def get_non_year_links(self) -> list:
        liberec_non_years = []
        links = self.soup.select('div#content p:not(.right.actions) a') # Don't select the social media links
        for link in links:
            link_text = link.get_text(strip=True)
            if 'Archiv' in link_text: # Get only the relevant links
                continue
            link_url = urljoin(BASE_POLICE_URL, link.get('href').lstrip('/'))
            liberec_non_years.append(link_url)
        return liberec_non_years


MUNICIPALITY_PARSERS = {
    "Informační": OnlyYearLinksParser,
    "hl. m. Praha": OnlyYearLinksParser,
    "Plzeňský": PlzenParser,
    "Středočeský": StredoParser,
    "Jihočeský": JihocesParser,
    "Jihomor": JihomorParser,
    "Karlovar": KarlovarParser,
    "Ústecký": UstecParser,
    "Liberec": LiberecParser,
}