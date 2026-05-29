# Herostratic

A Python data pipeline that scrapes graffiti and vandalism reports from Czech police press releases and news sites into a searchable PostgreSQL database. Built as an async, multi-stage pipeline: discover → scrape → clean → normalize → insert, with full-text search and Czech-language location matching on top.

## Architecture

The pipeline runs in four stages, each independently runnable:

1. **Discovery** — walks the regional Czech police archives to find article URLs across years and non-year categories.
2. **Scraping** — fetches each article concurrently, extracts title / date / author / content / attached files, and tags it with a region / district / municipality.
3. **Cleaning** — unicode normalization, boilerplate stripping, author byline parsing, length validation.
4. **Insertion** — async insert into PostgreSQL with idempotent upserts and a tsvector full-text search index.

A cron orchestrator runs the full pipeline incrementally.

### Notable design points

- **Strategy pattern for regional sites.** The 14 Czech regional police archives all have different HTML. `MunicipalityParser` is an abstract base with 12 region-specific subclasses; South Moravia has its own dedicated parser because its archive structure changes per year.
- **MorphoDita-backed location matching.** Czech is heavily inflected. The matcher hits Charles University's MorphoDita morphology API to generate every declension form of every Czech district and municipality, compiles them into length-sorted regex patterns for greedy matching, and maps back to nominative form.
- **Resilient async I/O.** Custom retry layer with exponential backoff + jitter, per-status-code handling (429 / 500 / 502-504 / 4xx), three timeout tiers, tuned aiohttp connection pool. Producer/consumer scraping with `asyncio.Queue`, 20 workers, buffered batch writes, resume-on-restart by deduping against already-scraped URLs.
- **Postgres FTS schema.** Generated `tsvector` column with weighted full-text search across title / description / content, GIN index, normalized region/district/municipality entities, separate tables for HTML, file attachments, and keywords.

## Tech stack

Python 3.12+ · aiohttp · asyncpg · aiofiles · BeautifulSoup + lxml · yt-dlp · PostgreSQL with full-text search

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up PostgreSQL and create the schema
createdb herostratic
psql -d herostratic -f db/police_schema.sql

# 3. Configure input files
cp data/input/police_sites.txt.example data/input/police_sites.txt
# Edit police_sites.txt with the regional police archive URLs to track

# 4. Generate Czech location lookups (one-time, hits MorphoDita)
python -m scripts.scrape_czechia_municipalities
python -m scripts.scrape_czechia_districts
python -m scripts.fetch_word_cases
```

## Usage

Run the full pipeline (one cycle):

```bash
python -m scraper.cron.cron_pipeline --max_pages 5
```

Or run individual stages:

```bash
# 1. Discover year links from configured archives
python -m scraper.police_tools.archives.police_year_links

# 2. Walk listings to extract article URLs
python -m scraper.police_tools.get_police_articles

# 3. Scrape article content + files
python -m scraper.police_tools.scrape_police_articles
```

DB insertion is currently invoked from the cron orchestrator.

### CLI flags

- `--max_pages N` (`-mp`) — limit how many listing pages each scraper walks per run
- `--cron` (`-cr`) — run in cron mode

## Project structure

```
scraper/
  core.py                       # Async BaseScraper context manager
  police_tools/                 # Police pipeline
    archives/                   # Year-link discovery (Strategy pattern, 14 regions)
    get_police_articles.py      # Listings → article URLs
    scrape_police_articles.py   # Article content + files
  aktualne/                     # aktualne.cz scraper (WIP)
  metro/                        # metro.cz scraper (WIP)
  cron/                         # Pipeline orchestrator
db/
  police_schema.sql             # Postgres schema with FTS
  police_db.py                  # Async insert layer
  police_normalizer.py          # JSON → dataclass normalizer
  tools/police_art_cleaner.py   # Cleaning pipeline
utils/
  network_utils.py              # Retry, backoff, jitter, status handling
  io_utils.py                   # Atomic writes, multi-encoding XML
  logger.py                     # Per-module rotating log files
scripts/                        # One-off helpers (location data, MorphoDita, etc.)
```

## Status

- **[Done]** Police archives (`policie.gov.cz`) — full pipeline working end-to-end
- **[WIP]** News sources (`aktualne.cz`, `metro.cz`) — scrapers in progress
- **[Planned]** REST API + frontend — schema is ready

## On the name

Herostratus (4th c. BCE) burned down the Temple of Artemis at Ephesus purely to be remembered. The Ephesians made saying his name illegal. The project tracks the modern equivalent — fame-seeking destruction in public space.
