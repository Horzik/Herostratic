import json

from config import YEAR_LINKS_FP, YEAR_LINKS2_FP


# This shit was mostly vibe fucking coded in like 30s lmao. Not fucking bad tbh
# todo git gut

def count_urls_in_dict(d):
    """Recursively count all URLs in a nested dictionary structure"""
    total = 0
    if isinstance(d, dict):
        for key, value in d.items():
            total += count_urls_in_dict(value)
    elif isinstance(d, list):
        for item in d:
            if isinstance(item, str):
                total += 1
            else:
                total += count_urls_in_dict(item)
    elif isinstance(d, str):
        total += 1
    return total


def count_urls_per_region(data):
    """Count URLs for each region"""
    region_counts = {}
    for region, content in data.items():
        region_counts[region] = count_urls_in_dict(content)
    return region_counts


def compare_dicts(doc1, doc2):
    """Compare two dictionaries and show differences"""

    # Count totals
    total1 = count_urls_in_dict(doc1)
    total2 = count_urls_in_dict(doc2)

    print(f"Document 1: {len(doc1)} regions, {total1} total URLs")
    print(f"Document 2: {len(doc2)} regions, {total2} total URLs")
    print(f"Difference: {total2 - total1} URLs\n")

    # Get per-region counts
    counts1 = count_urls_per_region(doc1)
    counts2 = count_urls_per_region(doc2)

    # Find regions only in doc1
    only_in_1 = set(counts1.keys()) - set(counts2.keys())
    if only_in_1:
        print("Regions ONLY in Document 1:")
        for region in only_in_1:
            print(f"  - {region}: {counts1[region]} URLs")
        print()

    # Find regions only in doc2
    only_in_2 = set(counts2.keys()) - set(counts1.keys())
    if only_in_2:
        print("Regions ONLY in Document 2:")
        for region in only_in_2:
            print(f"  + {region}: {counts2[region]} URLs")
        print()

    # Find regions with different counts
    common_regions = set(counts1.keys()) & set(counts2.keys())
    differences = []
    for region in common_regions:
        if counts1[region] != counts2[region]:
            diff = counts2[region] - counts1[region]
            differences.append((region, counts1[region], counts2[region], diff))

    if differences:
        print("Regions with DIFFERENT URL counts:")
        for region, count1, count2, diff in differences:
            sign = "+" if diff > 0 else ""
            print(f"  {region}: {count1} → {count2} ({sign}{diff})")
        print()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    added = sum(counts2[r] for r in only_in_2)
    removed = sum(counts1[r] for r in only_in_1)
    changed = sum(d[3] for d in differences)

    print(f"  New regions added: {len(only_in_2)} ({added} URLs)")
    print(f"  Regions removed: {len(only_in_1)} ({removed} URLs)")
    print(f"  Changed regions: {len(differences)} (net {changed:+d} URLs)")
    print(f"  Total net change: {total2 - total1:+d} URLs")


def main():
    with open(YEAR_LINKS_FP, 'r') as d:
        doc1 = json.load(d)

    with open(YEAR_LINKS2_FP, 'r') as d:
        doc2 = json.load(d)

    compare_dicts(doc1, doc2)

if __name__ == "__main__":
    main()