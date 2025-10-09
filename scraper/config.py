from pathlib import Path

# Define the file paths
ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
SITES_FP = DATA_DIR / "sites.txt"
SITEMAPS_FP = DATA_DIR / "sitemaps.json"
NOSITEMAPS_FP = DATA_DIR / "nositemaps.txt"
ARTICLES_FP = DATA_DIR / "articles.json"

# Parsing and scraping filters and keywords
EXCLUDE_SITEMAP_KEYWORDS = ['auto', 'moto', 'sport', 'volby', 'fotbal', 'hokej', 'finance', 'ekonomika', 'hry', 'politika']
URL_KEYWORDS = ['graffiti', 'vandal', 'sprejer']
EXCLUDE_URL_KEYWORDS = ['ukrajin', 'israel', 'palestin', 'násilí', 'fyzick', 'útok', 'anti', 'hate', 'rasis']

# Sitemap constants
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
URL_EL = f".//{SITEMAP_NS}url"
LOC_EL = f"{SITEMAP_NS}loc"
LASTMOD_EL = f"{SITEMAP_NS}lastmod"
SITEMAP_INDEX_EL = f".//{SITEMAP_NS}loc"

# Various constants
MAX_RETRIES = 3
TIMEOUT = 10
