import json

from config import POLICE_RESULTS_FP


""" Look how many scraped police articles have file as 'unknown' 

"""
if __name__ == "__main__":
    with open(POLICE_RESULTS_FP, "r") as f:
        print(f"Reading {POLICE_RESULTS_FP}...")
        res = json.load(f)
    unknown_files = set()
    for muni, categories in res.items():
        for cat, articles in categories.items() :
            for article in articles:
                files = article.get("files")
                url = article.get("url")
                for file in files:
                    if not file:
                        continue
                    for n in file:
                        if n == "unknown":
                            print(f"Got a file")
                            unknown_files.add(url)
    print(f"Found {len(unknown_files)} files")
    for f in unknown_files:
        print(f)
