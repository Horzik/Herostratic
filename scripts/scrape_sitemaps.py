import json
import logging

from config import SITES_FP, SITEMAPS_FP, NOSITEMAPS_FP, LOG_DIR, ERRORS_LOG_FP
from urllib.robotparser import RobotFileParser

from utils.logger import LogConfig, init_logging, get_logger, destroy

config = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_popo_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )
init_logging(config)
logger = get_logger()

# Check if a target sites have a sitemap/index => save and write to "SITEMAPS" and rest to "NOSITEMAPS"
def main():
    results = {}
    # Read and clean the urls
    with open(SITES_FP, 'r') as s:
        urls = [line.strip() for line in s]
    with open(NOSITEMAPS_FP, "w") as n:
        for url in urls:
            robots_txt: str = url + "/robots.txt"
            rp = RobotFileParser()
            rp.set_url(robots_txt)
            try:
                rp.read()
            except Exception as e:
                logger.error(f"Error reading {url}::")
                logger.error(e)
                n.write(url + "\n")
                continue

            sitemap: list[str] | None = rp.site_maps()
            # No sitemaps ==> add to the NOSITEMAPS
            if sitemap is None:
                logger.info(url + " has no sitemap")
                n.write(url + "\n")
                continue
            # Sitemap ==> add to results
            results[url] = sitemap
            logger.info(f"Found a sitemap:'{sitemap}' for url: '{url}'")

    ## Write the results to SITEMAPS
    if results:
        with open(SITEMAPS_FP, "w") as m:
            json.dump(results, m, indent=2)
            logger.info(f"Found {len(results)} sitemaps, exiting...")

    destroy() # Kill the log handlers


if __name__ == "__main__":
    main()