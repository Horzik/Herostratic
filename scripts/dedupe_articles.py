from config import ARTICLES_FP
import json


# Attempt to get rid of duplicate items from a target dictionary (ie "ARTICLES_FP")
def dedupe_articles():
    with open(ARTICLES_FP, "r") as f:
        data = json.load(f)

    de_art = {}
    for domain, urls in data.items():
        de_art[domain] = list(set(urls))

    original_len = len(data)
    new_len = len(de_art)
    print(f"Found {original_len - new_len} duplicate articles")

    with open("deduped.json", "w") as d:
        json.dump(de_art, d, indent=2)


def main():
    dedupe_articles()

if __name__ == "__main__":
    main()