import asyncio
import logging
from dataclasses import dataclass
from logging import Logger

import asyncpg

from config import ALL_KEYWORDS, LOG_DIR, ERRORS_LOG_FP
from db.pg_utils import get_db_strategy
from db.police_normalizer import NormalizedPoliceResult
from utils.io_utils import async_json_read
from utils.logger import LogConfig, get_logger, init_logging

CREATE_POLICE_SQL_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS locations (
        id SERIAL PRIMARY KEY,
        region VARCHAR(50),
        district VARCHAR(50),
        municipality VARCHAR(50),
        UNIQUE(region, district, municipality)
    );

    CREATE TABLE IF NOT EXISTS articles (
        id SERIAL PRIMARY KEY,
        source VARCHAR(255) NOT NULL,
        url TEXT NOT NULL unique,
        location_id INTEGER REFERENCES locations(id),
        year INTEGER,
        date DATE,
        author VARCHAR(100),
        title TEXT NOT NULL,
        description TEXT,
        content TEXT NOT NULL,
        search_vector tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('simple', coalesce(description, '')), 'B') ||
            setweight(to_tsvector('simple', coalesce(content, '')), 'C')
        ) STORED,
        db_inserted_at TIMESTAMP DEFAULT NOW()
    );
        
    CREATE TABLE IF NOT EXISTS keywords (
        id SERIAL PRIMARY KEY,
        keyword VARCHAR(16) NOT NULL UNIQUE
    );
        
    CREATE TABLE IF NOT EXISTS article_keywords (
        article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
        PRIMARY KEY (article_id, keyword_id)
    );
        
    CREATE TABLE IF NOT EXISTS article_html (
        article_id INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
        html_base64 TEXT NOT NULL
    );
        
    CREATE TABLE IF NOT EXISTS article_files (
        id SERIAL PRIMARY KEY,
        article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        file_path TEXT NOT NULL,
        file_type VARCHAR(20) NOT NULL CHECK (file_type IN ('image', 'video', 'document')),
        created_at TIMESTAMP DEFAULT NOW()
    );
        
    CREATE INDEX IF NOT EXISTS idx_articles_location_id ON articles(location_id);
    CREATE INDEX IF NOT EXISTS idx_article_keyword_id ON article_keywords(keyword_id);
    CREATE INDEX IF NOT EXISTS idx_articles_search_vector ON articles USING GIN(search_vector);
'''

@dataclass
class InsertArticleData:
    source: str
    url: str
    year: str
    date: str
    author: str
    title: str
    description: str
    content: str


async def insert_article_locations(db_conn, reg, dist, muni):
    """Return the id, whether the location already existed or was just created."""
    return await db_conn.fetchval("""
        WITH ins AS (
            INSERT INTO locations (region, district, municipality)
            VALUES ($1, $2, $3)
            ON CONFLICT (region, district, municipality) DO NOTHING
            RETURNING id
        )
        SELECT id FROM ins
        UNION ALL
        SELECT id FROM locations
        WHERE region = $1 AND district = $2 AND municipality = $3
        LIMIT 1
    """, reg, dist, muni
    )


async def insert_article_data(db_conn, location_id, art_data: InsertArticleData):
    print(f"Inserting article data: {art_data}")
    return await db_conn.fetchval("""
        INSERT INTO articles (location_id, source, url, year, date, author, title, description, content)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT DO NOTHING
        RETURNING id
    """, location_id, art_data.source, art_data.url,
         art_data.year, art_data.date, art_data.author,
         art_data.title, art_data.description, art_data.content
    )


async def insert_keywords(db_conn, kws):
    """Mainly for separating actual graffiti articles from other vandalism."""
    await db_conn.executemany("""
        INSERT INTO keywords (keyword)
        VALUES ($1)
        ON CONFLICT DO NOTHING
    """, [(kw,) for kw in kws]
    )

async def insert_article_keyword(db_conn, article_id, keyword):
    """Select the passed keyword ID and insert it along with the article ID"""
    await db_conn.execute("""
        INSERT INTO article_keywords (article_id, keyword_id)
        SELECT $1, id FROM keywords WHERE keyword = $2
        ON CONFLICT DO NOTHING
    """, article_id, keyword
    )


async def insert_article_html(db_conn, article_id, html_base64):
    await db_conn.execute("""
        INSERT INTO article_html (article_id, html_base64)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, article_id, html_base64
    )


async def insert_article_files(db_conn, article_id, file_path, file_type):
    await db_conn.execute("""
        INSERT INTO article_files (article_id, file_path, file_type)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
    """, article_id, file_path, file_type
)


async def create_indices(db_conn):
    await db_conn.execute("""
        CREATE INDEX idx_articles_location_id ON articles(location_id);
        CREATE INDEX idx_article_keyword_id ON article_keywords(keyword_id);
        CREATE INDEX idx_articles_search_vector ON articles USING GIN(search_vector);
    """
    )

async def get_articles_count(db_conn):
    await db_conn.fetcheval("""
        SELECT id FROM articles
    """
    )


async def get_files(db_conn):
    ids = await db_conn.fetch("""SELECT id, title FROM articles;""")
    files = await db_conn.fetch("""SELECT article_files FROM article_files;""")
    return ids, files


DB_ADDRESS = f"postgresql://postgres@localhost:5432/herostratic"
class PgConn:
    def __init__(self, address=DB_ADDRESS):
        self.address = address
        self.pool = None # get on enter
        self.conn = None # get on enter

    async def __aenter__(self):
        self.pool = await asyncpg.create_pool(self.address) # postgres@localhost/test
        self.conn = await self.pool.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            await self.pool.release(self.conn)
        if self.pool:
            await self.pool.close()


class PoliceSql(PgConn):
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'police_db.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self, address: str):
        super().__init__(address=address) # Give the inner asyncpg an address to be aentered with
        init_logging(self.LOG_CONFIG)
        self.logger: Logger = get_logger('police_db')
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(10)


    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Log errors then call the parent __aexit__ which closes the connection
        if exc_type:
            self.logger.error(f"Database error: {exc_val}")
        await super().__aexit__(exc_type, exc_val, exc_tb)


    async def normalize_results(self, domain_name: str) -> list[NormalizedPoliceResult]:
        fp, strategy = get_db_strategy(domain_name)
        results = await async_json_read(fp)
        normalized_results = strategy(results)
        self.logger.info(f"Returning normalized results of: '{domain_name}'")
        return normalized_results


    async def mk_default_db(self, sql: str=CREATE_POLICE_SQL_SCHEMA, kws: list[str]=ALL_KEYWORDS):
        self.logger.info(f"Creating database at {self.address}")
        await self.conn.execute(sql)
        await insert_keywords(self.conn, kws)
        self.logger.info(f"Schema creation successful")


    async def insert_police_article(self, location, article, html, kws, files):
        self.logger.debug("Inserting article...")
        async with self.semaphore:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # First get id or None from 'locations'
                    location_id = await insert_article_locations(
                        conn,
                        location.region,
                        location.district,
                        location.municipality
                    )

                    # Again get id or None from 'article'
                    article_id = await insert_article_data(conn, location_id, article)
                    if article_id is None:
                        self.logger.info(f"Article already exists, skipping: {article.url}")
                        return

                    # Use article ID for HTML insert
                    await insert_article_html(conn, article_id, html)

                    # Insert article keywords and files
                    for kw in kws:
                        await insert_article_keyword(conn, article_id, kw)
                    for file in files:
                        await insert_article_files(conn, article_id, file.file_path, file.file_type)
                    self.logger.debug(f"Inserted police article id: <{article_id}>")


async def insert_police_results():
    async with PoliceSql() as db:
        db.logger.info('Running PoliceDb main...')
        norm_pol_res = await db.normalize_results('policie')
        await asyncio.gather(*[
            db.insert_police_article(
                art.location,
                art.article,
                art.html_base64,
                art.keywords,
                art.article_files
            ) for art in norm_pol_res
        ])
        db.logger.info('Exiting PoliceDb main...')

async def main():
    async with PoliceSql() as db:
        db.logger.info('Running PoliceDb main...')
        db.logger.info('Exiting PoliceDb main...')

if __name__ == "__main__":
    asyncio.run(main())
