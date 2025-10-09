import os
import tempfile

import requests
import json
import time
import xml.etree.ElementTree as ET

from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, Timeout, HTTPError, RequestException
from urllib3.util import Retry
from config import (
    SITEMAPS_FP,
    ARTICLES_FP,
    EXCLUDE_SITEMAP_KEYWORDS,
    URL_KEYWORDS,
    MAX_RETRIES,
    TIMEOUT,
    URL_EL,
    LOC_EL,
    LASTMOD_EL,
    SITEMAP_INDEX_EL
)


def create_session() -> requests.Session:
    session = requests.Session()
    # Play nice
    session.headers.update({
        'User-Agent': 'SitemapParser/1.0 (learning project)',
        'Accept': 'application/xml, text/xml, */*',
    })
    # Define the adapter
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,  # 2, 4, 8 seconds
        status_forcelist=tuple(range(400, 600)),
        allowed_methods=["GET", "HEAD", "OPTIONS"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=20,
        pool_maxsize=50
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_xml_tag(response: requests.Response, url: str) -> ET.Element | None:
    for encoding in ['utf-8', 'windows-1250', 'iso-8859-2']:
        try:
            content = response.content.decode(encoding)
            # Return if no content
            if len(content) <= 10:
                print(f"No content for {url}, skipping")
                return None
            root = ET.fromstring(content)
            return root

        except UnicodeDecodeError as e:
            print(f"UnicodeDecodeError with {encoding}: {e}")
            continue
        except ET.ParseError as e:
            print(f"ParseError with {encoding}: {e}")
            print(f"First 500 chars with {encoding}:")
            print(content[:500] if 'content' in locals() else "Could not decode")
            continue

    print(f"Could not parse {url} with any encoding")
    return None


def extract_sitemap_urls(root: ET.Element, session: requests.Session):
    sitemap_urls = root.findall(SITEMAP_INDEX_EL)
    all_urls = []
    for loc in sitemap_urls:
        # todo we want to check everything for the archive
        # Skip a sitemap if it's older than 2024
        # year_match = re.search(r'20\d{2}', loc.text)
        # if year_match and int(year_match.group()) < 2024:
        #     continue
        # Skip sitemap if it includes excluded keyword
        if any(keyword in loc.text for keyword in EXCLUDE_SITEMAP_KEYWORDS):
            continue
        # Give the server a break and parse the sitemap
        time.sleep(0.5)
        sub_urls = parse_single_map(url=loc.text, session=session)
        all_urls.extend(sub_urls)
    return all_urls


def extract_article_urls(root: ET.Element):
    urls = []
    url_elements = root.findall(URL_EL)
    for url_elem in url_elements:
        loc = url_elem.find(LOC_EL)
        lastmod = url_elem.find(LASTMOD_EL)
        # Check the timestamp
        # todo again, for archive we want everything
        # if lastmod is not None:
        #     year = int(lastmod.text[:4])
        # if year < 2024:
        #     print("This is some old shit")
        #     continue
        if loc is not None:
            # DEV print the keywords
            if any(keyword in loc.text for keyword in URL_KEYWORDS):
                print(loc.text)
                urls.append(loc.text)
    return urls


def get_response(url: str, session: requests.Session) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        # Incrementally increase the wait time
        wait_time = 2 ** attempt
        try:
            response = session.get(url, timeout=TIMEOUT)
            # Not 200 => retry
            if response.status_code != 200:
                print(f"HTTP {response.status_code} for {url}, attempt {attempt + 1}/{MAX_RETRIES}")
                if attempt < MAX_RETRIES - 1:
                    print(f"Retrying {url}...")
                    time.sleep(wait_time)
                    continue
                # Max retries => timeout
                else:
                    print(f"Timed out for {url}, skipping...")
                    return None
            # 200 => continue to the parsing
            else:
                print(f"Success for {url}, attempt {attempt + 1}")
                return response

        # Catch exceptions
        # todo create an error log (and other logs)
        except ConnectionError as e:
            print(f"Connection error for {url}, (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
        except Timeout as e:
            print(f"Timeout for {url}, (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
        except HTTPError as e:
            print(f"HTTPError for {url}, (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")
        except RequestException as e:
            print(f"Request error for {url}, (attempt {attempt + 1}/{MAX_RETRIES}):: {e}")

        if attempt < MAX_RETRIES - 1:
            print(f"Retrying in...")
            time.sleep(wait_time)
        else:
            print(f"Failed parsing {url}, skipping")
            return None

    print(f"No response for {url}")
    return None


def parse_single_map(url: str, session: requests.Session) -> list[str]:
    response: requests.Response | None = get_response(url, session)
    if response is None:
        print(f"No response for {url}")
        return []

    root: ET.Element = parse_xml_tag(response, url)
    if root is None:
        print(f"No root for {url}")
        return []

    # Parse the sitemapindex
    if "sitemapindex" in root.tag:
        sitemap_urls = extract_sitemap_urls(root, session)
        return sitemap_urls

    # Parse the url set
    elif "urlset" in root.tag:
        article_urls = extract_article_urls(root)
        return article_urls

    else:
        print(f"Unknown root tag: {root.tag}")
        return []


def parse_all_sitemaps() -> None:
    all_articles: dict = {}
    # Load the sitemaps
    with open(SITEMAPS_FP) as f:
        sitemaps_data: dict = json.load(f)

    # Open the session with the context manager
    with create_session() as current_session:
        # Check each domain
        for domain, sitemaps in sitemaps_data.items():
            all_articles[domain] = []  # Add the key (as domain) for these articles
            print(f"Processing {domain}")
            # Check each sitemap
            for sitemap_url in sitemaps:
                print(f"  Processing {sitemap_url}")
                # Find and store the articles
                matching_articles = parse_single_map(url=sitemap_url, session=current_session)
                all_articles[domain].extend(matching_articles)
                print(f"Found {len(matching_articles)} URLs from {sitemap_url}")

            # Write after each domain
            tmp_name = None
            try:
                with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(ARTICLES_FP) or '.') as tmp:
                    json.dump(all_articles, tmp, indent=2)
                    tmp_name = tmp.name
                os.replace(tmp_name, ARTICLES_FP)
            # todo something on error (retry strategy or log)
            except Exception as e:
                print(f"Error saving to {ARTICLES_FP}: {e}")
                if tmp_name and os.path.exists(tmp_name):
                    os.unlink(tmp_name)  # Clean up temp file
                raise


def main():
    parse_all_sitemaps()


if __name__ == "__main__":
    main()