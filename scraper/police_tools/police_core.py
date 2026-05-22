from dataclasses import dataclass, field
from typing import TypedDict, NamedTuple


@dataclass
class ListingScrapeMetadata:
    articles: list[str] = field(default_factory=list)
    all_articles_count: int = 0
    pages_scraped: int = 0
    listing_max_pages: int = 0

class ScrapeLogData(NamedTuple):
    saved_articles: int
    failed_articles: int
    articles_processed: int
    total_pages: int

class PoliceArticleResult(TypedDict):
    source: str
    archive_category: str  # year or 'non_years'
    url: str
    title: str
    year: int | str | None # Backwards comp
    date: str | None
    region: str | None
    district: str | None
    municipality: str | None
    author: str | None
    description: str
    content: str
    files: list[tuple[str, str]] # (file_path, file_type)
    keywords: list[str]
    scraped_at: str
    html: str

@dataclass
class ScrapingStats:
    saved_articles: int = 0
    failed_articles: int = 0
    articles_processed: int = 0
    missing_date: int = 0
    missing_author: int = 0
    with_files: int = 0

type Region = str
type ArchCategory = str
type FileUrl = str
type FileName = str
type NextUrl = str
type ResBuffer = list[tuple[Region, ArchCategory, PoliceArticleResult]]
type FileMetadata = tuple[FileUrl, FileName]
