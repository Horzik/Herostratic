from asyncio import Semaphore, Lock, gather
from bs4 import BeautifulSoup
from pathlib import Path
from abc import ABC
import aiofiles
import json

from utils.logger import LogConfig, init_logging, get_logger
from utils.network_utils import create_session, get_bytes


class BaseScraper(ABC):
    """ Base class for async scrapers. Handles session/semaphore. \n
        Open and run the children as context managers.
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
        self.logger = get_logger(f'{self.MODULE_NAME}_scraper')
        self.lock = Lock()
        self._session = None # Create on enter, close on exit
        self._semaphore = Semaphore(self.SEMAPHORE_COUNT)

        # Task stats
        self.pages_scraped = 0
        self.errors = []


    async def __aenter__(self):
        self._session = await create_session().__aenter__()
        return self


    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.__aexit__(exc_type, exc_val, exc_tb)


    async def parser(self, url):
        return NotImplementedError


    @staticmethod
    async def scrape(tasks) -> list:
        """ Runs all jobs of the provided coroutines list. """
        return await gather(*tasks, return_exceptions=True)


    async def get_soup(self, url) -> BeautifulSoup | None:
        page_bytes = await self.fetch(url, gov_site=self.GOV_SITE)
        if page_bytes is None:
            return None
        soup = BeautifulSoup(page_bytes, 'lxml')
        return soup


    async def fetch(self, url: str, gov_site=False):
        res = await get_bytes(url, self._session, self._semaphore, gov_site)
        return res if res else None


    async def write_results(self, processed_results):
        """ Writes the passed results into 'OUTPUT_FILE' \n"""
        async with self.lock:
            async with aiofiles.open(self.OUTPUT_FILE, "w", encoding='utf-8') as p:
                await p.write(json.dumps(processed_results, indent=2, ensure_ascii=False))
                self.logger.info(f"Saved results to '{self.OUTPUT_FILE}'")