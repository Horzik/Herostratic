from config import ARTICLES_FP, POLICE_ARTICLES_FP, DEDUPED_FP, POLICE_RESULTS_FP
import json


def dedupe_all_articles():
    with open(POLICE_ARTICLES_FP, "r", encoding="utf-8") as f:
        data = json.load(f)

    de_art = {}
    seen_urls = set()

    for domain, urls in data.items():
        unique_urls = []
        for url in urls:
            if url not in seen_urls:
                seen_urls.add(url)
                unique_urls.append(url)
        de_art[domain] = unique_urls

    original_count = sum(len(urls) for urls in data.values())
    new_count = sum(len(urls) for urls in de_art.values())
    print(f"Removed {original_count - new_count} duplicate articles")

    with open(DEDUPED_FP, "w") as d:
        json.dump(de_art, d, indent=2)

# Log the difference in deduplication
def dedupe_articles():
    with open(ARTICLES_FP, "r") as f:
        data = json.load(f)

    de_art = {}
    for domain, urls in data.items():
        de_art[domain] = list(set(urls))

    original_len = len(data)
    new_len = len(de_art)
    print(f"Found {original_len - new_len} duplicate articles")

    with open(DEDUPED_FP, "w") as d:
        json.dump(de_art, d, indent=2)

def count_duplicate():
    with open(POLICE_RESULTS_FP, "r") as f:
        data = json.load(f)

    de_art = {}
    for domain, urls in data.items():
        de_art[domain] = list(set(urls))

    original_len = len(data)
    new_len = len(de_art)
    all_urls = []
    for region, region_data in data.items():
        for district, articles in region_data.items():
            for article in articles:
                all_urls.append(article["url"])

    print(f"Total: {len(all_urls)}, Unique: {len(set(all_urls))}")
    print(f"Found {original_len - new_len} duplicate articles")

def main():
    # dedupe_articles()
    count_duplicate()
    # dedupe_all_articles()

if __name__ == "__main__":
    main()