import json
import aiofiles

from pathlib import Path
from typing import Coroutine
from abc import ABC, abstractmethod
from asyncio import Semaphore, Lock, gather

from utils.logger import LogConfig, init_logging, get_logger
from utils.network_utils import create_session, get_bytes


class BaseScraper(ABC):
    SITE_NAME: str = None
    BASE_URL: str = None
    INPUT_FILE: Path = None
    OUTPUT_FILE: Path = None
    SEMAPHORE_COUNT: int = None
    GOV_SITE: bool = False
    LOG_CONFIG: LogConfig = None

    def __init__(self):
        init_logging(self.LOG_CONFIG)
        self.logger = get_logger(f'{self.SITE_NAME}_scraper')
        self._session = create_session()
        self._semaphore = Semaphore(self.SEMAPHORE_COUNT)
        self._lock = Lock()

        # Task stats
        self.results = []
        self.tasks = []
        self.pages_scraped = 0
        self.errors = []
        self.start_time = None

    async def fetch(self, url, **kwargs):
        return await get_bytes(url, self._session, self._semaphore)

    @abstractmethod
    async def parser(self, url):
        return NotImplementedError

    @abstractmethod
    def start_task(self, *kwargs) -> Coroutine:
        raise NotImplementedError()

    @abstractmethod
    def prepare_tasks(self) -> list:
        """ This will place our desired task format into 'self.tasks' """
        raise NotImplementedError()

    async def scrape(self) -> list:
        async with self._session:
            self.tasks = self.prepare_tasks()
            return await gather(*self.tasks, return_exceptions=True)

    @abstractmethod
    def process_results(self, results):
        raise NotImplementedError()

    async def write_results(self, processed_results):
        async with self._lock:
            async with aiofiles.open(self.OUTPUT_FILE, "w", encoding='utf-8') as p:
                await p.write(json.dumps(processed_results, indent=2, ensure_ascii=False))
                self.logger.info(f"Saved to {self.OUTPUT_FILE}")



