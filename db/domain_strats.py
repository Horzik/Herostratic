from typing import TypedDict

from config import POLICE_RESULTS_FP, CZECH_MONTHS
from datetime import date

class DbArticleTable(TypedDict):
    source: str
    url: str
    year: int | None
    date: str | None
    author: str | None
    title: str
    description: str | None
    content: str
    scraped_at: str

class DbLocationTable(TypedDict):
    region: str | None
    district: str | None
    municipality: str | None

class DbFilesTable(TypedDict):
    file_path: str | None
    file_type: str | None

class NormalizedArticleResult(TypedDict):
    location: DbLocationTable
    article: DbArticleTable
    keywords: set[str]
    article_files: DbFilesTable
    html_base64: str


def police_normalizer(raw_results):
    normalized_articles = []
    for region, region_data in raw_results.items():
        for archive_category, articles in region_data.items():
            for result in articles:
                article_location: DbLocationTable = {
                    "region": result["region"],
                    "district": result["district"],
                    "municipality": result["municipality"]
                }
                article_table_result: DbArticleTable = {
                    "source": result["source"],
                    "url": result["url"],
                    "year": result["year"], # TODO new prop
                    "date": result["date"], # TODO convert to actual 'date' from the iso string
                    "author": result["author"],
                    "title": result["title"],
                    "description": result["description"],
                    "content": result["content"],
                    "scraped_at": result["scraped_at"],
                }
                article_keywords = result["keywords"]
                article_files: DbFilesTable = {
                    "file_path": result["file_path"],
                    "file_type": result["file_type"]
                }
                article_html64 = result["html_base64"]

                normalized_result: NormalizedArticleResult = {
                    "location": article_location,
                    "article": article_table_result,
                    "keywords": article_keywords,
                    "article_files": article_files,
                    "html_base64": article_html64,
                }

                # Add this result and continue with other
                normalized_articles.append(normalized_result)

    return normalized_articles

NormalizerStrategies = [
    ('policie', POLICE_RESULTS_FP, police_normalizer),
    # ('aktualne', AKT_ART_FP, aktualne_norm),
    # ('metro', METRO_ARTICLES_FP, metro_norm)
]