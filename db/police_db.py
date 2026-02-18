from logging import Logger
from typing import TypedDict

import asyncpg

from config import ALL_KEYWORDS
from db.pg_utils import get_db_strategy
from db.police_normalizer import NormalizedArticleResult
from utils.io_utils import async_json_read


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
            setweight(to_tsvector('czech', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('czech', coalesce(description, '')), 'B') ||
            setweight(to_tsvector('czech', coalesce(content, '')), 'C')
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

class InsertArticleData(TypedDict):
    source: str
    url: str
    year: str
    date: str
    author: str
    title: str
    description: str
    content: str


async def insert_article_locations(db, reg, dist, muni):
    await db.fetchval("""
        INSERT INTO locations (region, district, municipality)
        VALUES ($1, $2, $3)
        ON CONFLICT (region, district, municipality) DO UPDATE
        SET region = EXCLUDED.region
        RETURNING id
    """, reg, dist, muni
)


async def insert_article_data(db, location_id, data: InsertArticleData):
    source, url, year, date, author, title, description, content = data
    await db.fetchval("""
        INSERT INTO articles (source, url, location_id, year, date, author, title, description, content)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT DO NOTHING
        RETURNING id
    """, location_id, source, url, year, date, author, title, description, content
)


async def insert_keywords(db):
    """Mainly for separating actual graffiti articles from other vandalism."""
    await db.executemany("""
        INSERT INTO keywords (keyword)
        VALUES ($1)
        ON CONFLICT DO NOTHING
    """, [kw for kw in ALL_KEYWORDS]
                             )

async def insert_article_keywords(db, article_id, keyword):
    await db.execute("""
        INSERT INTO article_keywords (article_id, keyword_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, article_id, keyword
)


async def insert_article_html(db, article_id, html_base64):
    await db.execute("""
        INSERT INTO article_html (article_id, html_base64)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, article_id, html_base64
)


async def insert_article_files(db, article_id, file_path, file_type):
    await db.execute("""
        INSERT INTO article_files (article_id, file_path, file_type)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
    """, article_id, file_path, file_type
)


async def create_indices(db):
    await db.execute("""
            CREATE INDEX idx_articles_location_id ON articles(location_id);
            CREATE INDEX idx_article_keyword_id ON article_keywords(keyword_id);
            CREATE INDEX idx_articles_search_vector ON articles USING GIN(search_vector);
        """
)

class PgConn:
    def __init__(self, address):
        self.address = address
        self.conn = None

    async def __aenter__(self):
        self.conn = await asyncpg.connect(self.address)  # postgres@localhost/test
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            await self.conn.close()


class PoliceSql(PgConn):
    def __init__(self, address: str, logger: Logger):
        super().__init__(address=address)
        self.logger: Logger | None = logger

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.logger.error(f"Database error: {exc_val}")


    async def normalize_results(self, domain_name: str) -> list[NormalizedArticleResult]:
        fp, strategy = get_db_strategy(domain_name)
        results = await async_json_read(fp)
        normalized_results = strategy(results)
        self.logger.info(f"Returning normalized results of: '{domain_name}'")
        return normalized_results


    async def run_sql_command(self, sql: str):
        self.logger.info(f"Executing SQL: {sql}")
        await self.conn.execute(sql)


    async def mk_default_db(self, sql: str=CREATE_POLICE_SQL_SCHEMA, kws: list[str]=ALL_KEYWORDS):
        self.logger.info(f"Creating database at {self.address}")
        await self.conn.execute(sql)
        await insert_keywords(self.conn, kws)
        self.logger.info(f"Schema creation successful")


    async def insert_police_article(self, data, location, kws, html, files):
        reg, muni, dist = location

        async with self.conn.transaction():
            # First get id or None from 'locations', use it in the main data insert
            location_id = await insert_article_locations(self.conn, reg, muni, dist)
            article_id = await insert_article_data(self.conn, location_id, data)
            await insert_article_html(self.conn, article_id, html)

            for kw in kws:
                await insert_article_keywords(self.conn, article_id, kw)
            for file in files:
                filepath, filename = file
                await insert_article_files(self.conn, filepath, filename, article_id)

            self.logger.debug(f"Inserted police article id: <{article_id}>")


    async def insert_multiple_police_articles(self, arts):
        for art in arts:
            data, location, kws, html, files = art
            await self.insert_police_article(data, location, kws, html, files)


# async def insert_to_db(domain: str):
#     normalized = await normalize_results(domain)
#     await batch_insert(normalized)
