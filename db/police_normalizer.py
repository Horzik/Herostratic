from dataclasses import dataclass

from config import POLICE_RESULTS_FP
from datetime import date

from db.tools.police_art_cleaner import clean_article_fields, clean_location_fields


@dataclass
class DbArticleTable:
    source: str
    url: str
    year: int | str | None
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
    html: str
    keywords: set[str]
    article_files: list[DbFile]


def police_normalizer(raw_results) -> list[NormalizedPoliceResult]:
    normalized_articles = []
    for region, region_data in raw_results.items():
        for _, articles in region_data.items():
            for result in articles:
                cleaned = clean_article_fields(result)
                cleaned_loc = clean_location_fields(result)

                article_location = DbLocationTable(
                    region=cleaned_loc["region"],
                    district=cleaned_loc["district"],
                    municipality=cleaned_loc["municipality"]
                )
                article_table_result = DbArticleTable(
                    source=cleaned["source"],
                    url=cleaned["url"],
                    year=cleaned["year"],
                    date=cleaned["date"],
                    author=cleaned["author"],
                    title=cleaned["title"],
                    description=cleaned["description"],
                    content=cleaned["content"],
                )

                # Make a list of the files (empty list if None)
                raw_files = [f for f in (result["files"] or []) if f is not None]
                article_files = [DbFile(file_path=fp, file_type=ft) for fp, ft in raw_files]

                normalized_result = NormalizedPoliceResult(
                    location=article_location,
                    article=article_table_result,
                    html=cleaned["html"],
                    keywords=result["keywords"],
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

def db_domain_strat(domain: str) -> tuple | None:
    """ Fetch the appropriate file path and a normalizer function for the target domain.
    """
    for key, fp, strat in NormalizerStrategies:
        if key == domain:
            return fp, strat
    return None
