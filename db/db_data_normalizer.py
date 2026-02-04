from typing import TypedDict

from config import POLICE_RESULTS_FP, AKT_ART_FP, METRO_ARTICLES_FP
from utils.io_utils import async_json_read

class DatabaseArticleTable(TypedDict):
    source: str
    url: str
    date: str | None
    author: str | None
    title: str
    description: str | None
    content: str
    scraped_at: str

class AllDatabaseData(TypedDict):
    location: tuple[str, str, str]
    article: DatabaseArticleTable
    keywords: set[str]
    article_files: None # todo
    html_base64: str

def police_normalizer(raw_results):
    normalized_articles = []
    for region, region_data in raw_results.items():
        for archive_link, articles in region_data.items():
            for result in articles:
                article_location = (
                    result["region"],
                    result["district"],
                    result["municipality"]
                )
                article_table_result: DatabaseArticleTable = {
                    "source": result["source"],
                    "url": result["url"],
                    "date": result["date"],
                    "author": result["author"],
                    "title": result["title"],
                    "description": result["description"],
                    "content": result["content"],
                    "scraped_at": result["scraped_at"],
                }
                article_keywords = result["keywords"]
                article_files = None  # TODO do I do this shit now or what, otherwise I need to make another module....
                article_html64 = result["html_base64"]
                normalized_articles.append({
                    'location': article_location,
                    'table_result': article_table_result,
                    'keywords': article_keywords,
                    'files': article_files,
                    'html64': article_html64,
                })
    return normalized_articles

NormalizerStrategies = [
    ('policie', POLICE_RESULTS_FP, police_normalizer),
    # ('aktualne', AKT_ART_FP, aktualne_norm),
    # ('metro', METRO_ARTICLES_FP, metro_norm)
]


def get_db_strategy(domain: str) -> tuple | None:
    for key, fp, strat in NormalizerStrategies:
        if key == domain:
            return fp, strat
    return None


async def normalize_results(domain):
    fp, strategy = get_db_strategy(domain)
    results = await async_json_read(fp)
    normalized_results = strategy(results)
    return normalized_results


async def batch_insert(normalized_data):
    # TODO this is just a mockup, we need to push to all the different tables
    await db.execute("""
           INSERT INTO articles (url, title, content, ...)
           VALUES (...)
           ON CONFLICT (url) DO NOTHING
       """, normalized_data)


async def push_to_db(domain: str):
    normalized = await normalize_results(domain)
    await batch_insert(normalized)
