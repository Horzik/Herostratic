from pathlib import Path

# Define the file paths
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
INPUT_DIR = DATA_DIR / "input"
LOG_DIR = DATA_DIR / "logs"
FILES_DIR = DATA_DIR / "files"

# Create these dirs if they don't exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

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
REGIONS_FP = OUTPUT_DIR / "regions.json"
DISTRICTS_FP = OUTPUT_DIR / "districts.txt"
MUNICIPALITIES_FP = OUTPUT_DIR / "municipalities.txt"
ALL_MUNIS_FP = OUTPUT_DIR / "all_munis.txt"
ALL_DISTRICTS_FP = OUTPUT_DIR / "all_districts.txt"

# Sites FPs
# policie.cz
POLICE_ARCHIVES_FP = OUTPUT_DIR / "police_archives.json"
POLICE_ARTICLES_FP = OUTPUT_DIR / "police_articles.json"
POLICE_RESULTS_FP = OUTPUT_DIR / "police_results.json"
POLICE_RESULTS_WITH_FILES = OUTPUT_DIR / "police_res_w_files.json"
FAILED_POLICE_RESULTS_FP = OUTPUT_DIR / "failed_police_results.txt"
YEAR_LINKS_FP = OUTPUT_DIR / "year_links.json"
JIHOMOR_LINKS_FP = OUTPUT_DIR / "jihomor_links.json"

# aktualne.cz
AKTUALNE_SITES_FP = INPUT_DIR / "aktualne_sites.txt"
AKT_ART_FP = OUTPUT_DIR / "aktualne.txt"
AKT_RESULTS_FP = OUTPUT_DIR / "aktualne_results.json"
FAILED_AKT_RESULTS_FP = OUTPUT_DIR / "failed_aktualne_results.txt"

# metro.cz
METRO_SITE_FP = INPUT_DIR / "metro_site.txt"
METRO_PATHS_FP = OUTPUT_DIR / "metro_paths.txt"
METRO_ARTICLES_FP = OUTPUT_DIR / "metro_articles.json"
METRO_RESULTS_FP = OUTPUT_DIR / "metro_results.json"
FAILED_METRO_RESULTS_FP = OUTPUT_DIR / "failed_metro_results.txt"
METRO_IMG_FP = OUTPUT_DIR / ""

# Parsing and scraping filters and keywords
URL_KEYWORDS = ['spray', 'sprey', 'sprej', 'graffiti', 'grafiti', 'grafity',
                'vandal', 'cmaral', 'mural', 'street art', 'street-art']  # todo rename this variable (its used when *parsing for urls*)
ARTICLE_KEYWORDS = ['metro', 'vlak', 'tramvaj', 'bus', 'autobus', 'fix', 'lept']
ALL_KEYWORDS = URL_KEYWORDS + ARTICLE_KEYWORDS
DECODE_FORMATS = ['utf-8', 'windows-1250', 'iso-8859-2']
EXCLUDE_ARCHIVE_KEYWORDS = ['nehody', 'násil', 'nasil']
EXCLUDE_SOCIAL_KEYWORDS = ['mailto:','twitter.com/share', 'facebook.com/sharer', 'q=cHJuPTE%3d']
# EXCLUDE_SITEMAP_KEYWORDS = ['auto', 'moto', 'sport', 'volby', 'fotbal', 'hokej', 'finance', 'ekonomika', 'hry', 'politika']
# EXCLUDE_URL_KEYWORDS = ['ukrajin', 'israel', 'palestin', 'fyzick', 'utok', 'anti', 'hate', 'rasis']

# Sitemap
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
URL_EL = f".//{SITEMAP_NS}url"
LOC_EL = f"{SITEMAP_NS}loc"
LASTMOD_EL = f"{SITEMAP_NS}lastmod"
SITEMAP_INDEX_EL = f".//{SITEMAP_NS}loc"

# I/O
MAX_RETRIES = 3
TIMEOUT = 10
POPO_TIMEOUT = 40

# Various
PIG_RANKS = ['nprap.', 'plk.', 'por.', 'prap.', 'kpt.', 'mjr.', 'pprap.', 'npor.']
CZECH_MONTHS = {
    'ledna': 1, 'února': 2, 'března': 3, 'dubna': 4,
    'května': 5, 'června': 6, 'července': 7, 'srpna': 8,
    'září': 9, 'října': 10, 'listopadu': 11, 'prosince': 12,
    'leden': 1, 'únor': 2, 'březen': 3, 'duben': 4,
    'květen': 5, 'červen': 6, 'červenec': 7, 'srpen': 8,
    'říjen': 10, 'listopad': 11, 'prosinec': 12,
}

# Regex for getting the date from article content
months_pattern = '|'.join(CZECH_MONTHS)
date_regex_words = rf'\d{{1,2}}\.?\s*({months_pattern})\s*\d{{4}}'
date_regex_numbers = r'\d{1,2}\.\s*\d{1,2}\.\s*\d{4}'
DATE_REGEX = rf'({date_regex_words}|{date_regex_numbers})'