import logging

from config import LOG_DIR, ERRORS_LOG_FP, ARTICLES_FP, SITEMAPS_FP
from scraper.oop_police import BaseScraper
from utils.logger import LogConfig


class ScrapeSitemapArticles(BaseScraper):
    SITE_NAME = 'SITEMAP_ARTICLES'
    BASE_URL = None
    INPUT_FILE = SITEMAPS_FP
    OUTPUT_FILE = ARTICLES_FP
    SEMAPHORE_COUNT = 30
    GOV_SITE = False
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_oop_archives.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

