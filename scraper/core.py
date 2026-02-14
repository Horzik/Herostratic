from abc import ABC
from asyncio import Semaphore, Lock
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from pathlib import Path

from utils.io_utils import atomic_json_write, CriticalDataError
from utils.logger import LogConfig, init_logging, get_logger
from utils.network_utils import create_session, get_bytes, FetchError


class BaseScraper(ABC):
    """Base class for async scrapers.
       Enters with a session. Run as context manager. \n
       Provides lock/logger, uses semaphore/session internally.  \n
    """
    MODULE_NAME: str = None
    BASE_URL: str = None
    INPUT_FILE: Path = None
    OUTPUT_FILE: Path = None
    FAILED_FILE: Path = None
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


    async def fetch(self, url: str, gov_site=False) -> bytes | None:
        """Wrapper for fetching to hide the session and semaphore."""
        try:
            return await get_bytes(url, self._session, self._semaphore, gov_site)
        except FetchError as e:
            self.logger.error(f"Fetch failed {e}")
            return None


    async def get_soup(self, url: str) -> BeautifulSoup | None:
        """Helper for getting the soup. Uses the class 'fetch' method."""
        page_bytes = await self.fetch(url, gov_site=self.GOV_SITE)
        if page_bytes is None:
            return None
        return BeautifulSoup(page_bytes, 'lxml')


    def write_results(self, data: dict | list) -> None:
        # TODO uses async lock but isn't async, also probably pointless to use the lock here anyways
        """Default write method. Only useful with basic scrapers, other
           ones need an override to a more concrete method of writing.
        """
        try:
            with self.lock:
                atomic_json_write(data, self.OUTPUT_FILE)
        except CriticalDataError:
            raise


    async def get_existing_urls(self):
        """Implement based on the OUTPUT_FILE structure. \n
           Use for deduping logic.
        """
        raise NotImplementedError


    # todo if we want to use this, it should probably validate a list of all required elements
    async def validate_elements(self, url: str, el_list) -> bool:
        """Validates an element in the url's html is selectable by the Soup.
           Optional to pass in the soup directly.
        """
        try:
            for i, el in enumerate(el_list):
                if el:
                    continue
                else:
                    self.logger.error(f"Failed asserting element {i} out of {len(el_list)} for url: '{url}'.")
                    return False
            self.logger.info(f"Asserted all {len(el_list)} elements.")
            return True
        except Exception:
            self.logger.exception(f"Unknown error while asserting year links for archive '{url}...'")
            raise
