import asyncio
import logging
from logging import Logger

import asyncpg

from config import LOG_DIR, ERRORS_LOG_FP
from db.police_normalizer import NormalizedPoliceResult, db_domain_strat
from db.queries import insert_article_locations, insert_article_data, insert_article_html, insert_article_keyword, \
    insert_article_files
from utils.io_utils import async_json_read
from utils.logger import LogConfig, get_logger, init_logging


DB_ADDRESS = f"postgresql://postgres@localhost:5432/herostratic"
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
        # Log errors then call the parent __aexit__ which closes the connection
        if exc_type:
            self.logger.error(f"Database error: {exc_val}")
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def normalize_results(self, domain_name: str) -> list[NormalizedPoliceResult]:
        fp, strategy = db_domain_strat(domain_name)
        results = await async_json_read(fp)
        normalized_results = strategy(results)
        self.logger.info(f"Returning normalized results of: '{domain_name}'")
        return normalized_results

    async def insert_police_article(self, location, article, html, kws, files):
        self.logger.debug("Inserting article...")
        async with self.semaphore:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    location_id = await insert_article_locations(
                        conn,
                        location.region,
                        location.district,
                        location.municipality
                    )
                    article_id = await insert_article_data(conn, location_id, article)
                    if article_id is None:
                        # self.logger.info(f"Article already exists, skipping: {article.url}")
                        return
                    # Use article ID for HTML insert
                    self.logger.info(f"Inserting article url: '{article.url}'")
                    await insert_article_html(conn, article_id, html)
                    # Insert article keywords and files
                    for kw in kws:
                        await insert_article_keyword(conn, article_id, kw)
                    for file in files:
                        await insert_article_files(conn, article_id, file.file_path, file.file_type)
                    self.logger.debug(f"Inserted police article id: <{article_id}>")

    async def insert_police_results(self):
        self.logger.info('Running PoliceDb main...')
        norm_pol_res = await self.normalize_results('policie')
        await asyncio.gather(*[
            self.insert_police_article(
                art.location,
                art.article,
                art.html,
                art.keywords,
                art.article_files
            ) for art in norm_pol_res
        ])
        self.logger.info('Exiting PoliceDb main...')
