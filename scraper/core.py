from abc import ABC
from asyncio import Semaphore, Lock
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from pathlib import Path

from utils.logger import LogConfig, init_logging, get_logger
from utils.network_utils import create_session, get_bytes, FetchError, SoupError


class BaseScraper(ABC):
    """Base class for async scrapers. \n
       Use as context manager. Enters with session. \n
       Provides lock/logger, uses semaphore/session internally. \n
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
        self._session: ClientSession | None = None
        self.pages_scraped: int = 0
        self.errors: list[str] = []

    async def __aenter__(self):
        self._session = await create_session().__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.__aexit__(exc_type, exc_val, exc_tb)

    async def fetch(self, url: str, gov_site=False, video=False) -> bytes:
        """ Wrapper for fetching to hide the session and semaphore.
        """
        return await get_bytes(url, self._session, self._semaphore, gov_site=gov_site, video=video)

    async def get_soup(self, url: str) -> BeautifulSoup:
        """ Helper for getting the soup. Uses the class 'fetch' method.
        """
        try:
            page_bytes = await self.fetch(url, gov_site=self.GOV_SITE)
            return BeautifulSoup(page_bytes, 'lxml')
        # Re-raise to indicate error with Soup
        except FetchError:
            self.logger.error(f"Error getting soup for url: {url}, returning None")
            raise SoupError(url)
