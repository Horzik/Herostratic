import asyncio
import logging
import os
import tempfile
import os.path
import aiofiles
import json

from bs4 import BeautifulSoup

from config import POLICE_ARTICLES_FP, POLICE_SITES_FP, URL_KEYWORDS, LOG_DIR, ERRORS_LOG_FP
from utils.logger import LogConfig, init_logging, get_logger, destroy
from utils.network_utils import create_session, get_bytes
from scraper.site_configs import POLICE_SELECTOR, BASE_POLICE_URL


config = LogConfig(
        log_level=logging.DEBUG,
        log_file_path=LOG_DIR / 'get_popo_articles.log',
        log_errors_file_path=ERRORS_LOG_FP
    )
init_logging(config)
logger = get_logger('get_popo_articles')


async def get_police_articles(url, domain, session, semaphore, lock):
    current_url = url
    articles = []
    all_articles_count = 0
    pages_scraped = 0
    logger.info(f"Scraping {domain}")
    try:
        while current_url:
            main_content = await get_bytes(url=current_url, session=session, semaphore=semaphore, gov_site=True)
            if main_content is None:
                logging.error(f"Couldn't get the main content from {current_url}")
                return
            main_soup = BeautifulSoup(main_content, 'lxml')

            article_list = main_soup.select(POLICE_SELECTOR['listing_selectors']['article_selector'])
            if not article_list:
                logger.error(f"Failed getting the article list element, check the selector")
                return

            for article in article_list:
                # All of this is redundant, but I don't want to delete it lol
                # title_element = article.select_one(POLICE_SELECTOR['listing_selectors']['article_title'])
                # title = title_element.text.strip()
                # description_element = article.select_one(POLICE_SELECTOR['listing_selectors']['article_description'])
                # description_text = description_element.text
                # description = POLICE_SELECTOR['parsing']['description'](description_text)
                # author_element = article.select_one(POLICE_SELECTOR['listing_selectors']['author'])
                # author_text = author_element.text
                # author = POLICE_SELECTOR['parsing']['author'](author_text)
                # date_element = article.select_one(POLICE_SELECTOR['listing_selectors']['date'])
                # date_text = date_element.text
                # date = POLICE_SELECTOR['parsing']['date'](date_text)
                # # Bundle it all together
                # articles[article_title] = {
                #     'link': article_link,
                #     'date': article_date,
                #     'author': article_author,
                #     'description': article_description,
                # }

                # Get the link to the article and append it to the list
                select_link = article.select_one(POLICE_SELECTOR['listing_selectors']['article_link'])
                article_link = select_link['href']
                all_articles_count += 1
                # Only save the articles that include the keywords
                if any(keyword in article_link for keyword in URL_KEYWORDS):
                    articles.append(BASE_POLICE_URL + article_link)
                    # logger.info(f"Scraped an article: ${article_link}")

            next_page = main_soup.select_one(POLICE_SELECTOR['pagination']['next_page'])
            if next_page:
                # Get the next page link and change 'current_url' to continue the loop
                next_page_link = next_page['href']
                current_url = BASE_POLICE_URL + next_page_link
                pages_scraped += 1
                # print(f"Continuing to the next page in: {domain}")
            else:
                # Else stop the loop and write the collected articles
                logger.info(f"No next page found, saving {len(articles)} articles "
                            f"from {pages_scraped} pages on domain {domain}...")
                current_url = None

        # Write the results
        async with lock:
            try:
                # Read the existing articles
                async with aiofiles.open(POLICE_ARTICLES_FP, 'r', encoding='utf-8') as a:
                    content = await a.read()
                    loop = asyncio.get_event_loop()
                    data = await loop.run_in_executor(None, json.loads, content)
            # If no file, start with empty object
            except (json.JSONDecodeError, FileNotFoundError):
                logger.debug("Failed to open POLICE_ARTICLES_FP, creating empty dict...")
                data = {}

            if domain not in data:
                # Create the domain and push the articles
                data[domain] = articles
            else:
                # Extend the list with the articles
                data[domain].extend(articles)

            try:
                # Write atomically
                tmp_name = None
                with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(POLICE_ARTICLES_FP)) as tmp:
                    json.dump(data, tmp, indent=4, ensure_ascii=False)
                    tmp_name = tmp.name
                os.replace(tmp_name, POLICE_ARTICLES_FP)
                logger.info(f"Success: got {len(articles)} for {domain}")
            # Catch errors for writing the results
            except Exception as r:
                logger.critical(f"!!ERROR WRITING RESULTS!!" "\n" f"{r}")
                if tmp_name and os.path.exists(tmp_name):
                    os.unlink(tmp_name)

    # Catch any generic error
    except Exception as e:
        logger.error(f"Error reading {current_url}:" "\n" f"{e}")


async def scraper():
    # Load the archive sites
    with open(POLICE_SITES_FP, "r") as a:
        content = a.read()
        archives: dict = json.loads(content)

    # Init the async primitives
    semaphore = asyncio.Semaphore(10)
    file_lock = asyncio.Lock()

    async with create_session() as session:
        police_tasks = [
            get_police_articles(url, domain, session, semaphore, file_lock)
            for domain, urls in archives.items()
            for url in urls
        ]
        await asyncio.gather(*police_tasks, return_exceptions=True)

    logger.info(f"Finished scraping {len(archives)} police archives, exiting....")


def main():
    asyncio.run(scraper())
    destroy()


if __name__ == "__main__":
    main()