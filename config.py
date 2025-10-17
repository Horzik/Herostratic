from pathlib import Path

# Define the file paths
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
INPUT_DIR = DATA_DIR / "input"
LOG_DIR = DATA_DIR / "logs"

# Create the "output" and "logs" dirs if they don't exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Logs FPs
ERRORS_LOG_FP = LOG_DIR / "errors.log"

# Scrape Input
SITES_FP = INPUT_DIR / "sites.txt"
POLICE_SITES_FP = INPUT_DIR / "police_sites.txt"

# Scrape Output
SITEMAPS_FP = OUTPUT_DIR / "sitemaps.json"
NOSITEMAPS_FP = OUTPUT_DIR / "nositemaps.txt"
ARTICLES_FP = OUTPUT_DIR / "articles.json"
HTML_FP = OUTPUT_DIR / "index.html"
DEDUPED_FP = OUTPUT_DIR / "deduped.json"
POLICE_ARCHIVES_FP = OUTPUT_DIR / "police_archives.json"
POLICE_ARTICLES_FP = OUTPUT_DIR / "police_articles.json"

# Parsing and scraping filters and keywords
EXCLUDE_SITEMAP_KEYWORDS = ['auto', 'moto', 'sport', 'volby', 'fotbal', 'hokej', 'finance', 'ekonomika', 'hry', 'politika']
URL_KEYWORDS = ['graffiti', 'vandal', 'sprejer', 'cmaral', ]
EXCLUDE_URL_KEYWORDS = ['ukrajin', 'israel', 'palestin', 'fyzick', 'utok', 'anti', 'hate', 'rasis']

# Sitemap constants
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
URL_EL = f".//{SITEMAP_NS}url"
LOC_EL = f"{SITEMAP_NS}loc"
LASTMOD_EL = f"{SITEMAP_NS}lastmod"
SITEMAP_INDEX_EL = f".//{SITEMAP_NS}loc"

# Various constants
MAX_RETRIES = 3
TIMEOUT = 10
POPO_TIMEOUT = 40
