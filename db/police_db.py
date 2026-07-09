import asyncio
import asyncpg
import dataclasses
import logging

from logging import Logger
from typing import Literal

from config import LOG_DIR, ERRORS_LOG_FP, DB_ADDRESS
from db.police_normalizer import NormalizedPoliceResult, db_domain_strat
from db.queries import insert_article_locations, insert_article_data, insert_article_html, \
    insert_article_keyword, insert_article_files
from utils.io_utils import async_json_read
from utils.logger import LogConfig, get_logger, init_logging


# Dataclass for metrics of the PG insertion process
@dataclasses.dataclass
class InsertionResult:
    url: str
    status: Literal["inserted", "skipped", "failed"]
    error_type: str | None = None
    error: str | None = None


 # todo config/env
class PgConn:
    def __init__(self, address=DB_ADDRESS):
        self.address = address
        self.pool = None

    async def __aenter__(self):
        self.pool = await asyncpg.create_pool(self.address)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.pool:
            await self.pool.close()


class PoliceSql(PgConn):
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'police_db.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        init_logging(self.LOG_CONFIG)
        self.logger: Logger = get_logger('police_db')
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(10)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type: # Log errors then call the parent __aexit__ which closes the connection
            self.logger.error(f"Database error: {exc_val}")
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def normalize_results(self, domain_name: str) -> list[NormalizedPoliceResult]:
        fp, strategy = db_domain_strat(domain_name)
        results = await async_json_read(fp) # todo add a middleman "staging" layer which reads the raw files instead of this main DB process
        normalized_results = strategy(results)
        self.logger.info(f"Returning normalized results of: '{domain_name}'")
        return normalized_results

    async def insert_police_article(self, location, article, html, kws, files):
        async with self.semaphore:
            async with self.pool.acquire() as conn:
                try:
                    async with conn.transaction():
                        location_id = await insert_article_locations(
                            conn,
                            location.region,
                            location.district,
                            location.municipality
                        )
                        article_id = await insert_article_data(conn, location_id, article)

                        # If None then article already in database
                        if article_id is None:
                            return InsertionResult(article.url, "skipped", None, None)

                        # Use article ID for HTML insert
                        self.logger.info(f"Inserting article url: '{article.url}'")
                        await insert_article_html(conn, article_id, html)

                        # Insert article keywords and files
                        for kw in kws:
                            await insert_article_keyword(conn, article_id, kw)
                        for file in files:
                            await insert_article_files(conn, article_id, file.file_path, file.file_type)

                        self.logger.debug(f"Inserted police article id: <{article_id}>")
                        return InsertionResult(article.url, "inserted", None, None)

                # todo catch finer errors
                except Exception as e:
                    self.logger.exception(f"Failed to insert article url: '{article.url}'")
                    return InsertionResult(article.url, "failed", type(e).__name__, str(e))

    def log_stats(self, results):
        inserted = [r for r in results if r.status == "inserted"]
        skipped = [r for r in results if r.status == "skipped"]
        failed = [r for r in results if r.status == "failed"]
        self.logger.info(f"Finished PoliceDB. Handled {len(results)} articles in total.")
        self.logger.info(f"Inserted: {len(inserted)}")
        self.logger.info(f"Skipped: {len(skipped)}")
        self.logger.info(f"Failed: {len(failed)}")

    async def insert_police_results(self):
        self.logger.info('Running PoliceDb main...')
        norm_pol_res = await self.normalize_results('policie')
        insertion_results = await asyncio.gather(*[
            self.insert_police_article(
                art.location,
                art.article,
                art.html,
                art.keywords,
                art.article_files
            ) for art in norm_pol_res
        ])
        self.log_stats(insertion_results)
        self.logger.info("Exiting PoliceDb main...")
