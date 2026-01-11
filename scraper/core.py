from asyncio import Semaphore, Lock, gather
from bs4 import BeautifulSoup
from pathlib import Path
from abc import ABC
import aiofiles
import json

from utils.io_utils import atomic_json_write, CriticalDataError
from utils.logger import LogConfig, init_logging, get_logger
from utils.network_utils import create_session, get_bytes


class BaseScraper(ABC):
    """ Base class for async scrapers.
        Enters with a session ==> run as context manager. \n
        Provides lock/logger,  \n
    """
    MODULE_NAME: str = None
    BASE_URL: str = None
    INPUT_FILE: Path = None
    OUTPUT_FILE: Path = None
    SEMAPHORE_COUNT: int = None
    GOV_SITE: bool = False
    LOG_CONFIG: LogConfig = None


    def __init__(self):
        init_logging(self.LOG_CONFIG)
        self.lock = Lock()
        self.logger = get_logger(f'{self.MODULE_NAME}_scraper')
        self._semaphore = Semaphore(self.SEMAPHORE_COUNT)
        self._session = None # Create on enter, close on exit

        # Stats
        self.pages_scraped = 0
        self.errors = []


    async def __aenter__(self):
        self._session = await create_session().__aenter__()
        return self


    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.__aexit__(exc_type, exc_val, exc_tb)


    async def get_soup(self, url: str) -> BeautifulSoup | None:
        page_bytes = await self.fetch(url, gov_site=self.GOV_SITE)
        if page_bytes is None:
            self.logger.error(f"Failed to fetch page from:: '{url}'...")
            return None
        soup = BeautifulSoup(page_bytes, 'lxml')
        return soup


    async def fetch(self, url: str, gov_site=False):
        res = await get_bytes(url, self._session, self._semaphore, gov_site)
        return res if res else None


    def write_results(self, data: dict | list) -> None:
        """ Default write method. Only useful with basic scrapers, others require
            a more concrete method of writing.
        """
        try:
            with self.lock:
                atomic_json_write(data, self.OUTPUT_FILE)
        except CriticalDataError:
            raise


    # todo either remove this or make it useful
    async def parser(self, url):
        return NotImplementedError


    # todo start using this
    async def validate_element(self, url: str, selector: str, soup=None) -> bool:
        """ Asserts an element in the url's html is selectable by the Soup.
            Optional to pass in the soup directly.
         """
        try:
            f_soup = soup if soup else await self.get_soup(url)
            if f_soup.select_one(selector):
                return True
            else:
                self.logger.error(f"Failed asserting element '{selector}'...")
                return False
        except Exception:
            self.logger.exception(f"Unknown error while asserting year links for archive '{url}...'")
            raise
