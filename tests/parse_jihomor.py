import asyncio
import json
from asyncio import Semaphore

from aiohttp import ClientSession
from bs4 import BeautifulSoup

from config import JIHOMOR_LINKS_FP
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL
from utils.network_utils import create_session, get_bytes

kokoti = {
    # "2008": [
    #   "https://policie.gov.cz/ks-brno.aspx"
    # ],
    # "2009": [
    #   "https://policie.gov.cz/archiv-zpravodajstvi-2009.aspx"
    # ],
    "2010": [
      "https://policie.gov.cz/krajske-reditelstvi-policie-jmk-zpravodajstvi-archiv-zpravodajstvi-2010.aspx"
    ],
    "2011": [
      "https://policie.gov.cz/zpravodajstvi-archiv-zpravodajstvi-2011.aspx"
    ],
    "2012": [
      "https://policie.gov.cz/zpravodajstvi-archiv-zpravodajstvi-2012.aspx"
    ],
    "2013": [
      "https://policie.gov.cz/zpravodajstvi-archiv-zpravodajstvi-2013.aspx"
    ],
    "2014": [
      "https://policie.gov.cz/zpravodajstvi-archiv-zpravodajstvi-2014.aspx"
    ],
    "2015": [
      "https://policie.gov.cz/zpravodajstvi-archiv-zpravodajstvi-2015.aspx"
    ],
    "2016": [
      "https://policie.gov.cz/zpravodajstvi-archiv-zpravodajstvi-2016.aspx"
    ],
    "2017": [
      "https://policie.gov.cz/zpravodajstvi-archiv-zpravodajstvi-2017.aspx"
    ],
    "2018": [
      "https://policie.gov.cz/zpravodajstvi-archiv-zpravodajstvi-2018.aspx"
    ],
    "2019": [
      "https://policie.gov.cz/archiv-2008-az-2020-archiv-zpravodajstvi-2019.aspx"
    ],
    "2020": [
      "https://policie.gov.cz/archiv-2008-az-2020-archiv-zpravodajstvi-2020.aspx"
    ],
    "2021": [
      "https://policie.gov.cz/archiv-2008-az-2021-archiv-zpravodajstvi-2021.aspx"
    ],
    "2022": [
      "https://policie.gov.cz/archiv-2008-az-2022-archiv-zpravodajstvi-2022.aspx"
    ],
    "2023": [
      "https://policie.gov.cz/archiv-2008-az-2022-archiv-zpravodajstvi-2023.aspx"
    ],
    "2024": [
      "https://policie.gov.cz/archiv-zpravodajstvi-2024.aspx"
    ],
    "Jihomoravského kraje":  [
      "https://policie.gov.cz/sprava-jihomoravskeho-kraje-zpravodajstvi.aspx"
    ],
    "Reditelství Brno": [
      "https://policie.gov.cz/zpravodajstvi-mr-brno.aspx"
    ],
    "Blansko":  [
      "https://policie.gov.cz/zpravodajstvi-uo-blansko.aspx"
    ],
    "Brno-venkov": [
      "https://policie.gov.cz/uo-brno-venkov.aspx"
    ],
    "Břeclav":  [
      "https://policie.gov.cz/uo-breclav.aspx"
    ],
    "Hodonín": [
      "https://policie.gov.cz/uo-hodonin.aspx"
    ],
    "Vyškov ":  [
      "https://policie.gov.cz/uo-vyskov.aspx"
    ],
    "Znojmo": [
      "https://policie.gov.cz/zpravodajstvi-uo-znojmo.aspx"
    ]
}


async def parse_jihomor_archive(soup: BeautifulSoup, session: ClientSession, semaphore: Semaphore, domain):
    """
        Get the year table, and crawl through to get the years links. \n
        First link => Second link => Multiple urls per year.
    """

    jihomor_years = {}
    next_link = BASE_POLICE_URL + soup.select_one('div.infobox a').get('href')
    # Go to the final url and get the links
    next_bytes = await get_bytes(next_link, session, semaphore, gov_site=True)
    jihomor_soup2 = BeautifulSoup(next_bytes, 'lxml')
    years_table = jihomor_soup2.select_one('div#content p:nth-of-type(2)')
    for link in years_table.find_all('a'):
        # Go over each link and add it to the 'jihomor_years' dict
        year_link = BASE_POLICE_URL + link.get('href')
        if domain not in jihomor_years:
            jihomor_years[domain] = []
        jihomor_years[domain].append(year_link)

    return jihomor_years

async def main():
    semaphore = Semaphore(30)
    results = {}
    async with create_session() as session:
        for domain, link in kokoti.items():
            url = link[0].strip()
            print(f"{domain}: {url}")
            page_bytes = await get_bytes(url=url, session=session, semaphore=semaphore, gov_site=True)
            if page_bytes is None:
                return None
            soup = BeautifulSoup(page_bytes, "lxml")
            links = await parse_jihomor_archive(soup, session, semaphore, domain)
            results[domain] = links

    with open (JIHOMOR_LINKS_FP, 'w') as f:
        json.dump(results, f, indent=4)

    return results

if __name__ == "__main__":
    asyncio.run(main())