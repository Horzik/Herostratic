import json
from data.config import SITES_FP, SITEMAPS_FP, NOSITEMAPS_FP
from urllib.robotparser import RobotFileParser


def main():
    results = {}
    # Read and clean the urls
    with open(SITES_FP, 'r') as s:
        urls = [line.strip() for line in s]
    with open(NOSITEMAPS_FP, "w") as n:
        for url in urls:
            # Add the "robots.txt" parameter
            robots_txt: str = url + "/robots.txt"
            # Init, prepare, and run the RP
            rp = RobotFileParser()
            rp.set_url(robots_txt)
            try:
                rp.read()
            except Exception as e:
                print(f"Error reading {url}::")
                print(e)
                n.write(url + "\n")
                continue
            sitemap: list[str] | None = rp.site_maps()
            # No sitemaps ==> add to the NOSITEMAPS
            if sitemap is None:
                print (url + " has no sitemap")
                n.write(url + "\n")
                continue
            # Sitemap ==> add to results
            results[url] = sitemap
            print(sitemap)

    ## Write the results to SITEMAPS
    if results:
        with open(SITEMAPS_FP, "w") as m:
            json.dump(results, m, indent=2)

if __name__ == "__main__":
    main()