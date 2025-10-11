from config import ARTICLES_FP
import json


def dedupe_articles():
    with open(ARTICLES_FP, "r") as f:
        data = json.load(f)

    de_art = {}
    for domain, urls in data.items():
        de_art[domain] = list(set(urls))

    with open("deduped.json", "w") as d:
        json.dump(de_art, d, indent=2)


def get_article_slug(url):
    # Extract just the topic keyword, ignore dates
    import re
    match = re.search(r'pi_?\d*_?([a-z]+)\.html', url)
    return match.group(1) if match else url
