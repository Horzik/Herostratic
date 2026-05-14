import argparse
import asyncio
import logging

from config import LOG_DIR, ERRORS_LOG_FP
from scraper.police_tools.get_police_articles import get_police_articles
from utils.logger import init_logging, get_logger, LogConfig
from utils.network_utils import create_session


logConfig = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'scrape_urls.log',
        log_errors_file_path=ERRORS_LOG_FP)
init_logging(logConfig)
logger = get_logger('scrape_urls')


""" This can be used to feed a list of police urls to scrape directly from the terminal
    
"""
# TODO add as functionality to the scrapers
async def parse_urls(urls_list: list[str]):
    semaphore = asyncio.Semaphore(10)
    file_lock = asyncio.Lock()

    async with create_session() as session:
        ulr_tasks = [
            get_police_articles(url, None, None, session, semaphore, file_lock)
            for url in urls_list
        ]

        results = await asyncio.gather(*[task for task in ulr_tasks], return_exceptions=True)
        failed_tasks = 0
        sucess_tasks = 0
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error for article task for url: '{result}'...")
                failed_tasks += 1
            if result is None:
                logger.error(f"Error for article task for url: '{result}'...")
                failed_tasks += 1
            sucess_tasks += 1

        logger.info(f"Successfully parsed {sucess_tasks}/{failed_tasks} articles")

def main():
    parser = argparse.ArgumentParser(description='Scrape police_tools articles')
    parser.add_argument('urls_file', help='Scrape articles from list of police urls')
    args = parser.parse_args()

    try:
        with open(args.urls_file, 'r') as f:
            urls_list = f.read().splitlines()
            asyncio.run(parse_urls(urls_list))

    except FileNotFoundError:
        logger.exception(f"File not found: {args.urls_file}")
    except Exception as e:
        logger.exception(f"Error reading file: {e}")


if __name__ == '__main__':
    main()