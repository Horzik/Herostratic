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
FAILED_ARCHIVES_FP = INPUT_DIR / "failed_archives.json"

# Scrape Output
SITEMAPS_FP = OUTPUT_DIR / "sitemaps.json"
NOSITEMAPS_FP = OUTPUT_DIR / "nositemaps.txt"
ARTICLES_FP = OUTPUT_DIR / "articles3.json"
HTML_FP = OUTPUT_DIR / "index.html"
DEDUPED_FP = OUTPUT_DIR / "deduped.json"

# TODO move to "site_configs" ?
POLICE_ARCHIVES_FP = OUTPUT_DIR / "police_archives.json"
POLICE_ARTICLES_FP = OUTPUT_DIR / "police_articles.json"
POLICE_RESULTS_FP = OUTPUT_DIR / "police_results.json"
YEAR_LINKS_FP = OUTPUT_DIR / "year_links1.json"
JIHOMOR_LINKS_FP = OUTPUT_DIR / "jihomor_links.json"

# Site-specific FPs
AKTUALNE_SITES_FP = INPUT_DIR / "aktualne_sites.txt"
AKT_ART_FP = OUTPUT_DIR / "aktualne.txt"
AKT_RESULTS_FP = OUTPUT_DIR / "aktualne_results.json"

# Parsing and scraping filters and keywords
EXCLUDE_SITEMAP_KEYWORDS = ['auto', 'moto', 'sport', 'volby', 'fotbal', 'hokej', 'finance', 'ekonomika', 'hry', 'politika'] # TODO USE?!
URL_KEYWORDS = ['graffiti', 'vandal', 'sprejer', 'cmaral', 'mural', 'street art', 'street-art' ] # todo rename this (also used for article parsing)
EXCLUDE_URL_KEYWORDS = ['ukrajin', 'israel', 'palestin', 'fyzick', 'utok', 'anti', 'hate', 'rasis'] # TODO also use????
ARTICLE_KEYWORDS = ['metro', 'vlak', 'tramvaj', 'bus', 'autobus', 'fix', 'sprej', 'lept']
DECODE_FORMATS = ['utf-8', 'windows-1250', 'iso-8859-2']
EXCLUDE_ARCHIVE_KEYWORDS = ['nehody', 'násil', 'nasil']
EXCLUDE_SOCIAL_KEYWORDS = ['mailto:','twitter.com/share', 'facebook.com/sharer', 'q=cHJuPTE%3d']

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

CZECH_MONTHS = [
        'ledna', 'února', 'března', 'dubna', 'května', 'června',
        'července', 'srpna', 'září', 'října', 'listopadu', 'prosince',
        'leden','únor','březen','duben','květen','červen',
        'červenec', 'srpen', 'září',  'říjen', 'listopad', 'prosinec'
]

PIG_RANKS = ['nprap.', 'plk.', 'por.', 'prap.', 'kpt.', 'mjr.', 'pprap.', 'npor.']

# Regex for getting the date from article content
months_pattern = '|'.join(CZECH_MONTHS)
date_regex_words = rf'\d{{1,2}}\.?\s*({months_pattern})\s*\d{{4}}'
date_regex_numbers = r'\d{1,2}\.\s*\d{1,2}\.\s*\d{4}'
DATE_REGEX = rf'({date_regex_words}|{date_regex_numbers})'