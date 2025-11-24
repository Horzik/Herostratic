import re
import time
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TypedDict

from scraper.core import BaseScraper
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL
from utils.io_utils import async_json_read, atomic_json_write
from utils.logger import LogConfig, destroy
from config import POLICE_ARTICLES_FP, LOG_DIR, ERRORS_LOG_FP, POLICE_RESULTS_FP, \
                    PIG_RANKS, DATE_REGEX, URL_KEYWORDS, ARTICLE_KEYWORDS


class ArticleResult(TypedDict):
    title: str
    url: str
    year: str
    date: str | None
    municipality: str
    keywords: list
    author: str
    description: str
    content: str
    has_pictures: bool
    has_documents: bool

@dataclass
class ScrapingResults:
    saved_articles: int = 0
    failed_articles: int = 0
    articles_processed: int = 0
    missing_date: int = 0
    missing_author: int = 0
    with_pictures: int = 0
    with_documents: int = 0

type Domain = str
type Year = str

class PoliceArticlesScraper(BaseScraper):
    MODULE_NAME = 'scrape_police_articles'
    BASE_URL = BASE_POLICE_URL
    INPUT_FILE = POLICE_ARTICLES_FP
    OUTPUT_FILE = POLICE_RESULTS_FP
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
        self.stats = ScrapingResults()
        self.results_buffer: list[tuple[Domain, Year, ArticleResult]] = []
        self.results_buffer_threshold = 50


    def process_results(self, article_jobs, article_results):
        for job_info, result in zip([job[0] for job in article_jobs], article_results):
            domain, year, url = job_info
            self.stats.articles_processed += 1
            if isinstance(result, Exception):
                self.logger.error(
                    f"Error scraping police article: '{domain}'/'{year}', url: '{url}' failed with exception: {result}")
                self.stats.failed_articles += 1
                continue
            if result is None:
                self.logger.error(f"Error: domain '{domain}'/'{year}', url: '{url}' returns None....")
                self.errors.append(f"Error: domain '{domain}'/'{year}', url: '{url}' returns None")
                self.stats.failed_articles += 1
                continue
            if not isinstance(result, dict):
                continue

            if not result['date']:  # Use bracket notation instead of .get() (?)
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
                date_text = match.group(0)
        if date_text is None:
            self.logger.debug(f"Failed getting the date from '{url}', '{domain}'::'{year}'")
        return date_text


    @staticmethod
    def get_author(content_ref):
        author_text = ''
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


    def assert_year(self, year, date_text, soup, url, domain):
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


    def assert_element(self, element, url, domain, year):
        if not element:
            self.logger.error(f"BS getting '{element(__name__)}' from '{url}', '{domain}'/'{year}'")
            self.errors.append(f"Failed getting element '{element(__name__)}' from '{url}', '{domain}'/'{year}'")
            return False
        return True


    def get_elements(self, soup, url, domain, year):
        title_ref = soup.select(POLICE_SELECTOR['article_selectors']['title'])
        description_ref = soup.select(POLICE_SELECTOR['article_selectors']['description'])
        content_ref = soup.select(POLICE_SELECTOR['article_selectors']['content'])
        pictures_ref = soup.select(POLICE_SELECTOR['article_selectors']['pictures'])
        documents_ref = soup.select(POLICE_SELECTOR['article_selectors']['documents'])
        p_tags = soup.select('div#content p')

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


    async def write_buffer(self):
        # Write only if we accumulated 30 articles
        async with self.lock:
            current_results = await async_json_read(self.OUTPUT_FILE)
            for domain, year, content in self.results_buffer:
                if domain not in current_results:
                    current_results[domain] = {}
                if year not in current_results[domain]:
                    current_results[domain][year] = []
                current_results[domain][year].append(content)

        # Write the results back and clean the buffer
        atomic_json_write(current_results, self.OUTPUT_FILE)
        self.results_buffer: list[tuple[Domain, Year, ArticleResult]] = []
        return


    # todo write failed articles?
    async def scrape_article(self,url, domain, year):
        keywords = [key for key in URL_KEYWORDS + ARTICLE_KEYWORDS if key in url]
        try:
            soup = await self.get_soup(url)
            if soup is None:
                self.logger.error(f"Failed scraping '{url}' from '{domain}'::'{year}")
                return None

            elements = self.get_elements(soup, url, domain, year)
            if elements is None:
                return None
            p_tags, title_ref, description_ref, content_ref, pictures_ref, documents_ref = elements

            has_pictures = True if pictures_ref else False
            has_documents = True if documents_ref else False
            date_text = self.get_date(content_ref, url, domain, year)
            author_text = self.get_author(content_ref)
            year = self.assert_year(year, date_text, soup, url, domain)

            # To get content_text, first define elements without the text
            non_text_elements = self.get_non_text_elements(
                title_ref, description_ref, pictures_ref, documents_ref
            )
            # Then add the text from all the other elements
            content_text = self.get_content_text(content_ref, non_text_elements,)

            article_result: ArticleResult = {
                'title': title_ref[0].get_text(),
                'url': url,
                'year': year,
                'date': date_text,
                'municipality': domain,
                'keywords': keywords,
                'author': author_text,
                'description': description_ref[0].get_text().strip(),
                'content': content_text,
                'has_pictures': has_pictures,
                'has_documents': has_documents,
            }

            # Append the result to the buffer
            self.logger.info(f"Got an article from '{url}', '{domain}'/'{year}'")
            self.results_buffer.append((domain, year, article_result))
            # If the buffer is large enough ==> write it
            if len(self.results_buffer) > self.results_buffer_threshold:
                self.logger.info(f"Writing from a buffer...")
                await self.write_buffer()
            return article_result

        except Exception as e:
            self.logger.exception(f"Failed scraping '{url}' from '{domain}'::'{year}. Error message ==>")
            self.logger.exception(e)
            return None


    async def scraper(self):
        timer_start = time.time()

        articles_links = await async_json_read(self.INPUT_FILE)
        article_jobs = [
            ((domain, year, url), self.scrape_article(url, domain, year)) # ((metadata), coroutine)
            for domain, years_dict in articles_links.items()
            for year, urls_list in years_dict.items()
            for url in urls_list
        ]
        article_results = await asyncio.gather(*[coro for _, coro in article_jobs],
         return_exceptions=True
        )

        self.process_results(article_jobs, article_results)
        await self.write_buffer() # Write the remaining results

        timer_end = time.time()
        elapsed_seconds = timer_end - timer_start
        formatted_time = str(timedelta(seconds=elapsed_seconds))

        self.logger.info(f"Finished scraping in {formatted_time}")
        self.logger.info(f"Processed {self.stats.articles_processed} articles, saved {self.stats.saved_articles}, "
                         f"failed {self.stats.failed_articles}")
        self.logger.info(f"{self.stats.missing_date} missing date, {self.stats.missing_author} missing author,"
                         f" {self.stats.with_pictures} have pictures and {self.stats.with_documents} have documents")
        self.logger.info(f"Exiting...")


async def main():
    async with PoliceArticlesScraper() as ps:
        try:
            await ps.scraper()
        finally:
            destroy()


if __name__ == "__main__":
    asyncio.run(main())