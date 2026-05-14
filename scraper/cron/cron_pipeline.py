import logging
from asyncio import gather, run

from config import LOG_DIR, ERRORS_LOG_FP
from scraper.args import ScraperArguments
from scraper.police_tools.get_police_articles import get_police_articles
from scraper.police_tools.scrape_police_articles import scrape_police_articles
from utils.logger import LogConfig, init_logging, destroy, get_logger


log_config = LogConfig(
    log_level=logging.DEBUG,
    log_std_level=logging.DEBUG,
    log_file_path=LOG_DIR / 'cron_pipeline.log',
    log_errors_file_path=ERRORS_LOG_FP
)


async def run_police_pipeline(cron_max_pages: int | None):
    found_new_articles = await get_police_articles(cron_max_pages)
    if found_new_articles:
        await scrape_police_articles()


async def run_orchestrator(cron_max_pages: int | None):
    """Make a list of all the scrapers and run them in async."""
    scrapers = [
        run_police_pipeline(cron_max_pages),
    ]
    await gather(*scrapers)


if __name__ == "__main__":
    init_logging(log_config)
    logger = get_logger(__name__)
    logger.info("Starting cron pipeline...")
    args = ScraperArguments().init_argparse().parse_args()
    max_pages = args.max_pages if args.max_pages else 5
    try:
        run(run_orchestrator(cron_max_pages=max_pages))
    finally:
        logger.info("Stopping cron pipeline...")
        destroy()
