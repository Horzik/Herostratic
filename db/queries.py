from db.police_normalizer import DbArticleTable


async def insert_article_locations(db_conn, reg, dist, muni):
    """ Return the id, whether the location already existed or was just created.
    """
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

async def insert_article_data(db_conn, location_id, art_data: DbArticleTable):
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
    """ Mainly for separating actual graffiti articles from other vandalism.
    """
    await db_conn.executemany("""
        INSERT INTO keywords (keyword)
        VALUES ($1)
        ON CONFLICT DO NOTHING
    """, [(kw,) for kw in kws]
    )

async def insert_article_keyword(db_conn, article_id, keyword):
    """ Select the passed keyword ID and insert it along with the article ID.
    """
    await db_conn.execute("""
        INSERT INTO article_keywords (article_id, keyword_id)
        SELECT $1, id FROM keywords WHERE keyword = $2
        ON CONFLICT DO NOTHING
    """, article_id, keyword
    )

async def insert_article_html(db_conn, article_id, html):
    await db_conn.execute("""
        INSERT INTO article_html (article_id, html)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, article_id, html
    )

async def insert_article_files(db_conn, article_id, file_path, file_type):
    await db_conn.execute("""
        INSERT INTO article_files (article_id, file_path, file_type)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
    """, article_id, file_path, file_type
    )


async def select_article_urls(db_conn):
    return await db_conn.fetch("""
        SELECT url FROM articles;
    """,
    )
