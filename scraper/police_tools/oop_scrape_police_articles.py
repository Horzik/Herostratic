import asyncio
import base64
import logging
import re
import time
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import timedelta, datetime, timezone
from typing import TypedDict

from config import (POLICE_ARTICLES_FP, LOG_DIR, ERRORS_LOG_FP, POLICE_RESULTS_FP,
                    PIG_RANKS, DATE_REGEX, ALL_KEYWORDS, FAILED_POLICE_RESULTS_FP)
from scraper.core import BaseScraper
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL
from utils.io_utils import async_json_read, atomic_json_write
from utils.logger import LogConfig, destroy


class ArticleResult(TypedDict):
    source: str
    archive_category: str  # Can be either the year or district/city
    url: str
    title: str
    date: str | None
    municipality: str
    author: str | None
    description: str
    content: str
    has_pictures: bool
    has_documents: bool
    keywords: list[str]
    scraped_at: str
    html_base64: str

@dataclass
class ScrapingStats:
    saved_articles: int = 0
    failed_articles: int = 0
    articles_processed: int = 0
    missing_date: int = 0
    missing_author: int = 0
    with_pictures: int = 0
    with_documents: int = 0

type Domain = str
type Year = str
type ResBuffer = list[tuple[Domain, Year, ArticleResult]]

# TODO add type hints, make it work as the cron pipeline
class PoliceArticlesScraper(BaseScraper):
    MODULE_NAME = 'scrape_police_articles'
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_ARTICLES_FP
    OUTPUT_FILE = POLICE_RESULTS_FP
    FAILED_FILE = FAILED_POLICE_RESULTS_FP
    GOV_SITE = True
    SEMAPHORE_COUNT = 10
    LOG_CONFIG = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.INFO,
        log_file_path=LOG_DIR / 'scrape_police_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )

    def __init__(self):
        super().__init__()
        self.stats = ScrapingStats()
        self.initial_results: set[str] = set()
        self.results_buffer: ResBuffer = []
        self.results_buffer_threshold = 50


    async def write_failed_article(self, res_url):
        async with self.lock:
            with open(FAILED_POLICE_RESULTS_FP, 'a') as f:
                f.write(res_url + '\n')


    async def validate_result(self, result, domain, year, url) -> bool:
        if result is None:
            # todo unify these error logs
            self.logger.error(f"Error: result is None. Domain '{domain}'/'{year}', url: '{url}'...")
            self.errors.append(f"Error: result is None. Domain '{domain}'/'{year}', url: '{url}'...")
            self.stats.failed_articles += 1
            await self.write_failed_article(url)
            return False
        if isinstance(result, Exception):
            self.logger.error(
                f"Error scraping police article: '{domain}'/'{year}', url: '{url}' failed with exception: {result}")
            self.stats.failed_articles += 1
            await self.write_failed_article(url)
            return False
        if not isinstance(result, dict):
            self.logger.error(f"Error: result not a dict. Domain '{domain}'/'{year}', url: '{url}'...")
            self.stats.failed_articles += 1
            await self.write_failed_article(url)
            return False

        return True


    async def process_results(self, article_jobs, article_results):
        for job_data, result in zip([job[0] for job in article_jobs], article_results):
            self.stats.articles_processed += 1
            domain, year, url = job_data

            if not await self.validate_result(result, domain, year, url):
                continue

            if not result['date']:
                self.stats.missing_date += 1
            if not result['author']:
                self.stats.missing_author += 1
            if result['has_pictures']:
                self.stats.with_pictures += 1
            if result['has_documents']:
                self.stats.with_documents += 1
            self.stats.saved_articles += 1
        return


    def get_date(self, content_ref, url, domain, year) -> str | None:
        date_text = None
        for p in content_ref:
            text = p.get_text()
            match = re.search(DATE_REGEX, text)
            if match:
                if date_text is not None:
                    self.logger.debug(f"Found multiple dates in '{url}'....")
                date_text = match.group(0).strip()
        if date_text is None:
            self.logger.debug(f"Failed getting the date from '{url}', '{domain}'::'{year}'")

        return date_text


    @staticmethod
    def get_author(content_ref):
        author_text = None
        for p in content_ref:
            text = p.get_text()
            if any(rank in text for rank in PIG_RANKS):
                lines = text.split('\n')
                # Find which line has the rank
                for line in lines:
                    if any(rank in line for rank in PIG_RANKS):
                        author_text = line.strip()
                        break
                break

        return author_text


    def get_archive_category(self, year, date_text, soup, url, domain):
        if year == "non_years" and date_text is not None:
            year = date_text[-5:].strip('\n')
        elif year == "non_years" and date_text is None:
            drobek_ref = soup.select_one(POLICE_SELECTOR['article_selectors']['drobek'])
            if drobek_ref:
                drobek_text = drobek_ref.get_text()
                year = drobek_text[-4:]
            else:
                self.logger.error(f"No drobek found for '{url}', '{domain}'::'{year}....'")

        return year


    @staticmethod
    def get_content_text(content_ref, non_text_elements):
        content_text = ''
        for tag in content_ref:
            if tag in non_text_elements:
                continue
            tag_text = tag.get_text().strip()
            if len(tag_text) > 10:
                content_text += tag_text + '\n'

        return content_text


    @staticmethod
    def get_non_text_elements(title_ref, description_ref, pictures_ref, documents_ref):
        non_text_elements = set()
        if title_ref:
            non_text_elements.update(title_ref[0])
        if description_ref:
            non_text_elements.update(description_ref[0])
        if pictures_ref:
            non_text_elements.update(pictures_ref)
        if documents_ref:
            non_text_elements.update(documents_ref)

        return non_text_elements


    def get_elements(self, soup: BeautifulSoup, url: str, domain: str, year: str):
        title_ref = soup.select(POLICE_SELECTOR['article_selectors']['title'])
        description_ref = soup.select(POLICE_SELECTOR['article_selectors']['description'])
        content_ref = soup.select(POLICE_SELECTOR['article_selectors']['content'])
        pictures_ref = soup.select(POLICE_SELECTOR['article_selectors']['pictures'])
        documents_ref = soup.select(POLICE_SELECTOR['article_selectors']['documents'])
        p_tags = soup.select('div#content p')

        # All articles need to have these elements
        required = {
            'title': title_ref,
            'description': description_ref,
            'content': content_ref
        }

        for name, element in required.items():
            if not element:
                self.logger.error(f"Missing '{name}' from '{url}', '{domain}'/'{year}'")
                return None

        return p_tags, title_ref, description_ref, content_ref, pictures_ref, documents_ref


    async def flush_buffer(self):
        """ Writes only after we accumulate 50 articles.
        """
        async with self.lock:
            # Read what we already saved
            current_results = await async_json_read(self.OUTPUT_FILE)

            # Append all the buffered results to the 'current_results'
            for domain, year, content in self.results_buffer:
                if domain not in current_results:
                    current_results[domain] = {}
                if year not in current_results[domain]:
                    current_results[domain][year] = []
                current_results[domain][year].append(content)

            # Write the results back and clean the buffer
            atomic_json_write(current_results, self.OUTPUT_FILE)
            self.results_buffer: ResBuffer = []
        return


    async def fetch_page(self, url: str, domain: str, year: str):
        soup = await self.get_soup(url)
        if soup is None:
            self.logger.error(f"Failed fetching soup for '{url}' from '{domain}'::'{year}")
            return None

        elements = self.get_elements(soup, url, domain, year)
        if elements is None:
            self.logger.error(f"Failed parsing elements for '{url}' from '{domain}'::'{year}")
            return None

        return soup, elements


    async def parse_html(self, url: str, domain: str, year: str):
        soup, elements = await self.fetch_page(url, domain, year)
        p_tags, title_ref, description_ref, content_ref, pictures_ref, documents_ref = elements

        has_pictures = bool(pictures_ref)
        has_documents = bool(documents_ref)
        date_text = self.get_date(content_ref, url, domain, year)
        author_text = self.get_author(content_ref)
        arch_cat = self.get_archive_category(year, date_text, soup, url, domain)
        page_bytes = await self.fetch(url)  # For 'html_base64'

        # To get content_text, first define elements without the text
        non_text_elements = self.get_non_text_elements(
            title_ref, description_ref, pictures_ref, documents_ref
        )
        # Then add the text from all the other elements
        content_text = self.get_content_text(content_ref, non_text_elements, )

        # Get keywords based on url AND the content
        keywords = list(set(key for key in ALL_KEYWORDS
                            if key in url or key in content_text)
        )

        article_result: ArticleResult = {
            'source': f'policie_{domain.replace(' ', '_').lower()}',
            'archive_category': arch_cat,
            'url': url,
            'title': title_ref[0].get_text(),
            'date': date_text,
            'municipality': domain,
            'author': author_text,
            'description': description_ref[0].get_text().strip(),
            'content': content_text,
            'has_pictures': has_pictures,
            'has_documents': has_documents,
            'keywords': keywords,
            'scraped_at': datetime.now(timezone.utc).isoformat(),
            "html_base64": base64.b64encode(page_bytes).decode("ascii"),
        }

        return article_result


    async def scrape_article(self, url: str, domain: str, year: str):
        try:
            article_result = await self.parse_html(url, domain, year)

            # Append the result to the buffer
            self.logger.info(f"Got an article from '{url}', '{domain}'/'{year}'")
            self.results_buffer.append((domain, year, article_result))

            # If the buffer is large enough ==> write it
            if len(self.results_buffer) > self.results_buffer_threshold:
                self.logger.info(f"Writing from a buffer...")
                await self.flush_buffer()

            return article_result

        except Exception as e:
            self.logger.error(f"Error: failed with exception while scraping '{url}' from '{domain}'::'{year}...\n {e}")
            return None


    async def get_existing_urls(self) -> set[str]:
        """ Used for deduping results, ie to not re-add a result which we already have.
        """
        initial_results_urls = set()
        results_dict = await async_json_read(self.OUTPUT_FILE)
        for domain, years in results_dict.items():
            for year, articles in years.items():
                for article in articles:
                    initial_results_urls.add(article['url'])

        self.logger.info(f"Initial results urls: {initial_results_urls}")
        return initial_results_urls


    async def mk_tasks(self):
        # Get a set of urls of already scraped articles, so we don't re-scrape what we already have
        self.initial_results = await self.get_existing_urls()

        articles_links = await async_json_read(self.INPUT_FILE)
        article_jobs = [
            ((domain, year, url), self.scrape_article(url, domain, year))  # ((metadata), coroutine)
            for domain, years_dict in articles_links.items()
            for year, urls_list in years_dict.items()
            for url in urls_list if url not in self.initial_results
        ]

        return article_jobs

    async def scraper(self):
        timer_start = time.time()

        article_jobs = await self.mk_tasks()
        article_results = await asyncio.gather(*[coro for _, coro in article_jobs], return_exceptions=True)
        await self.process_results(article_jobs, article_results)

        if len(self.results_buffer) > 0: # Write any remaining results
            await self.flush_buffer()

        timer_end = time.time()
        formatted_time = str(timedelta(seconds=timer_end - timer_start))

        self.logger.info(f"Finished scraping in {formatted_time}")
        self.logger.info(f"Processed {self.stats.articles_processed} articles, saved {self.stats.saved_articles}.")
        self.logger.info(f"{self.stats.failed_articles} articles failed.")
        self.logger.info(f"{self.stats.missing_date} are missing date, {self.stats.missing_author} are missing author.")
        self.logger.info(f"{self.stats.with_pictures} have pictures and {self.stats.with_documents} have documents.")
        self.logger.info(f"Exiting...")


async def scrape_police_articles():
    async with PoliceArticlesScraper() as ps:
        try:
            await ps.scraper()
        finally:
            destroy()


if __name__ == "__main__":
    asyncio.run(scrape_police_articles())