import asyncio
import json
import logging
import re
import time
from datetime import timedelta
from bs4 import BeautifulSoup

from config import POLICE_ARTICLES_FP, LOG_DIR, ERRORS_LOG_FP, POLICE_RESULTS_FP, CZECH_MONTHS, PIG_RANKS, DATE_REGEX, \
    URL_KEYWORDS, ARTICLE_KEYWORDS
from scraper.site_configs import POLICE_SELECTOR
from utils.io_utils import async_json_read, atomic_json_write
from utils.logger import LogConfig, init_logging, get_logger, destroy
from utils.network_utils import get_bytes, create_session


article_result: dict = {
    "title": str,
    "url": str,
    "year": str,
    "date": str,
    "municipality": str,
    "keywords": str,
    "author": str,
    "description": str,
    "content": str,
    "has_pictures": bool,
    "has_documents": bool,
}

logConfig = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'scrape_police_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
)
init_logging(logConfig)
logger = get_logger('scrape_popo_articles')


# todo write failed articles?
async def scrape_article(url, domain, year, session, semaphore, file_lock):
    result = {}
    keywords = [key for key in URL_KEYWORDS + ARTICLE_KEYWORDS if key in url]
    has_pictures = False
    has_documents = False

    try:
        page_bytes = await get_bytes(url, session, semaphore, gov_site=True)
        if page_bytes is None:
            logger.error(f"Failed scraping '{url}' from '{domain}'::'{year}")
            return None

        soup = BeautifulSoup(page_bytes, 'lxml')
        # Prepare the elements
        p_tags = soup.select('div#content p')
        title_ref = soup.select(POLICE_SELECTOR['article_selectors']['title'])
        if not title_ref:
            logger.error(f"BS error getting the 'title_ref' from '{url}', '{domain}'::'{year}")
            return None
        description_ref = soup.select(POLICE_SELECTOR['article_selectors']['description'])
        if not description_ref:
            logger.error(f"BS error getting the 'description_ref' from '{url}', '{domain}'::'{year}")
            return None
        content_ref = soup.select(POLICE_SELECTOR['article_selectors']['content'])
        if not content_ref:
            logger.error(f"BS error getting the 'content_ref' from '{url}', '{domain}'::'{year}")
            return None
        pictures_ref = soup.select(POLICE_SELECTOR['article_selectors']['pictures'])

        if not pictures_ref:
            pass
            # logger.debug(f"No pictures found in '{url}', '{domain}'::'{year}")
        else:
            has_pictures = True

        documents_ref = soup.select(POLICE_SELECTOR['article_selectors']['documents'])
        if not documents_ref:
            pass
#             logger.debug(f"No documents found in '{url}', '{domain}'::'{year}")
        else:
            has_documents = True


        # DATE - look through the content, save the last one,
        date_text = None
        for p in content_ref:
            text = p.get_text()
            match = re.search(DATE_REGEX, text)
            if match:
                if date_text is not None:
                    logger.debug(f"Found multiple dates in '{url}'....")
                date_text = match.group(0)
        if date_text is None:
            logger.error(f"Failed getting the date from '{url}', '{domain}'::'{year}'")

        # AUTHOR
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

        # CONTENT
        # First make a list of elements we don't care about
        non_text_elements = [
            title_ref[0],
            description_ref[0],
            soup.find('div#graybox'),  # Pictures
            soup.find('div#related'),  # Attachments
            p_tags[-2],  # Author and date?
            p_tags[-1],  # Social media link?
        ]

        # Loop through the remaining elements and get all their texts
        content_text = ''
        for tag in content_ref:
            if tag in non_text_elements:
                continue
            tag_text = tag.get_text().strip()
            if len(tag_text) > 10:
                content_text += tag_text + '\n'


        # Year hack for 'null'
        if year == "null" and date_text is not None:
            year = date_text[-5:].strip('\n')
        elif year == "null" and date_text is None:
            drobek_ref = soup.select_one(POLICE_SELECTOR['article_selectors']['drobek'])
            if drobek_ref:
                drobek_text = drobek_ref.get_text()
                year = drobek_text[-4:]
            else:
                logger.error(f"No drobek found for '{url}', '{domain}'::'{year}....'")

        # Domain hack for 'null'
        if domain == "null":
            # Try getting the domain/municipality link
            domain_ref = soup.find('a', **{'string': 'Krajská ředitelství policie'})
            if not domain_ref:
                logger.error(f"Domain is null and no domain link found found in '{url}', '{domain}'::'{year}'")
            else:
                next_element = domain_ref.find_next_sibling('a')
                domain = next_element.get_text()

        article_result['title'] = title_ref[0].get_text()
        article_result['url'] = url
        # Add 'scraped_at'
        article_result['year'] = year
        article_result['date'] = date_text
        article_result['municipality'] = domain
        article_result['keywords'] = keywords
        article_result['author'] = author_text
        article_result['description'] = description_ref[0].get_text().strip()
        article_result['content'] = content_text
        # Get and add thumbnails?
        # Probably change the below to direct FPs and deduce the boolean in DB
        article_result['has_pictures'] = has_pictures
        article_result['has_documents'] = has_documents

        async with file_lock:
            # Read the existing results
            data = await async_json_read(POLICE_RESULTS_FP)

            if domain not in data:
                data[domain] = {}
            if year not in data[domain]:
                data[domain][year] = []
            data[domain][year].append(result)

            # Write the results
            atomic_json_write(data, POLICE_RESULTS_FP)

        return result

    except Exception as e:
        logger.exception(f"Failed scraping '{url}' from '{domain}'::'{year}. Error message ==>")
        logger.exception(e)
        return None


async def scraper():
    with open(POLICE_ARTICLES_FP, 'r') as pa:
        articles_links = json.load(pa)

    timer_start = time.time()
    semaphore = asyncio.Semaphore(30)
    file_lock = asyncio.Lock()

    async with create_session() as session:
        article_jobs = [
            ((domain, year, url), scrape_article(url, domain, year, session, semaphore, file_lock))
            for domain, years_dict in articles_links.items()
            for year, urls_list in years_dict.items()
            for url in urls_list
        ]

        article_results = await asyncio.gather(*[coro for _, coro in article_jobs],
         return_exceptions=True
        )

        # todo make a dataclass
        saved_articles = 0
        failed_articles = 0
        articles_processed = 0
        missing_date = 0
        missing_author = 0
        has_pictures = 0
        has_documents = 0

        for job_info, result in zip([job[0] for job in article_jobs], article_results):
            domain, year, url = job_info
            articles_processed += 1
            if isinstance(result, Exception):
                logger.error(f"Error scraping police article: '{domain}'/'{year}', url: '{url}' failed with exception: {result}")
                failed_articles += 1
                continue
            if result is None:
                logger.error(f"Error: domain '{domain}'/'{year}', url: '{url}' returns None....")
                failed_articles += 1
                continue
            if not isinstance(result, dict):
                continue

            saved_articles += 1

            if not result['date']:  # Use bracket notation instead of .get()
                missing_date += 1
            if not result['author']:
                missing_author += 1
            if result['has_pictures']:
                has_pictures += 1
            if result['has_documents']:
                has_documents += 1


    timer_end = time.time()
    elapsed_seconds = timer_end - timer_start
    formatted_time = str(timedelta(seconds=elapsed_seconds))
    logger.info(f"Finished scraping in {formatted_time}")
    logger.info(f"Processed {articles_processed} articles, saved {saved_articles}, failed {failed_articles}")
    logger.info(f"{missing_date} missing date, {missing_author} missing author, {has_pictures} have pictures and {has_documents} have documents")
    logger.info(f"Exiting...")


def main():
    asyncio.run(scraper())
    destroy()


if __name__ == "__main__":
    main()