from dataclasses import dataclass

from config import POLICE_RESULTS_FP
from datetime import date


@dataclass
class DbArticleTable:
    source: str
    url: str
    year: int | None
    date: date | None
    author: str | None
    title: str
    description: str | None
    content: str

@dataclass
class DbLocationTable:
    region: str | None
    district: str | None
    municipality: str | None

@dataclass
class DbFile:
    file_path: str
    file_type: str

@dataclass
class NormalizedPoliceResult:
    location: DbLocationTable
    article: DbArticleTable
    html_base64: str
    keywords: set[str]
    article_files: list[DbFile]


# This is just a hotfix for some dates being corrupted (either not correct isostring or bad format all together).
# Upstream should be already fixed, this is just a safety net
def parse_date_flexible(date_str: str) -> date | None:
    if not date_str:
        return None
    try:
        year, month, day = date_str.split('-')
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def police_normalizer(raw_results) -> list[NormalizedPoliceResult]:
    normalized_articles = []
    for region, region_data in raw_results.items():
        for _, articles in region_data.items():
            for result in articles:
                article_location = DbLocationTable(
                    region=result["region"],
                    district=result["district"],
                    municipality=result["municipality"]
                )
                article_table_result = DbArticleTable (
                    source = result["source"],
                    url = result["url"],
                    year = result["year"],
                    date= parse_date_flexible(result["date"]),
                    author = result["author"],
                    title = result["title"],
                    description = result["description"],
                    content = result["content"],
                )
                article_html64 = result["html_base64"]
                article_keywords = result["keywords"]

                # Make a list of the files (empty list if None)
                raw_files = [f for f in (result["files"] or []) if f is not None]
                article_files = [DbFile(file_path=fp, file_type=ft) for fp, ft in raw_files]

                normalized_result = NormalizedPoliceResult(
                    location=article_location,
                    article=article_table_result,
                    html_base64=article_html64,
                    keywords=article_keywords,
                    article_files=article_files,
                )

                # Add the result and continue with others
                normalized_articles.append(normalized_result)

    return normalized_articles

NormalizerStrategies = [
    ('policie', POLICE_RESULTS_FP, police_normalizer),
    # ('aktualne', AKT_ART_FP, aktualne_norm),
    # ('metro', METRO_ARTICLES_FP, metro_norm)
]