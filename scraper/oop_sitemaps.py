import asyncio
import logging
import xml.etree.ElementTree as ET
from os import close

from scraper.oop_police import BaseScraper
from utils.io_utils import async_json_read, parse_xml_tree
from utils.logger import LogConfig, destroy
from config import (
    LOG_DIR, ERRORS_LOG_FP, ARTICLES_FP, SITEMAPS_FP,
    SITEMAP_INDEX_EL, URL_EL, LOC_EL, URL_KEYWORDS)

# Unlike the original this writes all results at the end (not for each domain)
class ScrapeSitemapArticles(BaseScraper):
    SITE_NAME = 'SITEMAP_ARTICLES'
    BASE_URL = None
    INPUT_FILE = SITEMAPS_FP
    OUTPUT_FILE = ARTICLES_FP
    SEMAPHORE_COUNT = 30
    GOV_SITE = False
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'sitemap_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    async def extract_sitemap_urls(self, root: ET.Element) -> list[str]:
        sitemap_urls = root.findall(SITEMAP_INDEX_EL)
        tasks = [self.parser(url=loc.text) for loc in sitemap_urls]
        result = await self.scrape(tasks)
        all_urls = [url for sublist in result for url in sublist]
        return all_urls

    def extract_article_urls(self, root: ET.Element):
        urls = []
        url_elements = root.findall(URL_EL)
        for url_elem in url_elements:
            url = url_elem.find(LOC_EL)
            if url is not None:
                # Filter the URLs based on keywords
                # todo: Dedupe by article key | slug ?
                if any(keyword in url.text for keyword in URL_KEYWORDS):
                    urls.append(url.text)
        self.logger.info(f"Found {len(urls)} urls")
        return urls

    async def parser(self, url: str) -> list[str]:
        """ Main parsing function for parsing the robots.txt file.
            Simply returns all links in the sitemap we find.
        """
        content_bytes = await self.fetch(url)
        root: ET.Element = await parse_xml_tree(content_bytes, url)
        if root is None:
            return self.logger.warning(f"No root for {url}")
        elif "sitemapindex" in root.tag:
            return await self.extract_sitemap_urls(root)
        elif "urlset" in root.tag:
            return self.extract_article_urls(root)
        else:
            self.logger.warning(f"Unknown root tag: {root.tag}")
            return []

    async def scrape_domain(self, domain: str, sitemaps: list[str]):
        self.logger.info(f"Processing {domain}")
        tasks = [self.parser(url=sitemap) for sitemap in sitemaps]
        results = await self.scrape(tasks)
        self.logger.info(f"Finished processing {domain}, results: {results}")
        all_articles = []
        for matching_articles in results:
            all_articles.extend(matching_articles)
        self.logger.info(f"Found this {all_articles}")
        return domain, all_articles

    def process_results(self, results):
        articles_by_domain = {}
        for result in results:
            # todo why does this fail?
            if isinstance(result, Exception):
                self.logger.error(f"Task failed: {result}")
                continue
            domain, articles = result
            if articles:
                articles_by_domain[domain] = articles
        return articles_by_domain

    async def prepare_domains(self, data_fp) -> list:
        sitemaps_data: dict = await async_json_read(data_fp)
        return [self.scrape_domain(domain, sitemaps)
                for domain, sitemaps in sitemaps_data.items()]

    async def run(self):
        tasks = await self.prepare_domains(self.INPUT_FILE)
        article_urls = await self.scrape(tasks)
        results = self.process_results(article_urls)
        await self.write_results(results)

async def main():
    async with ScrapeSitemapArticles() as scr:
        try:
            await scr.run()
        finally:
            destroy()

if __name__ == "__main__":
    asyncio.run(main())
