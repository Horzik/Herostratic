from config import CZECH_MONTHS


def parse_czech_date(date_str: str):
    """ Get generic czech date, return the standard 'Date' format."""
    import re
    from datetime import date

    if not date_str:
        return None

    date_str = date_str.strip().rstrip('.')

    # Try numeric first: "6. 10. 2020"
    match = re.match(r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})', date_str)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return date(year, month, day)

    # Try Czech month name: "12. září 2020"
    match = re.match(r'(\d{1,2})\.\s*(\w+)\s+(\d{4})', date_str)
    if match:
        day = int(match.group(1))
        month = CZECH_MONTHS.get(match.group(2).lower())
        year = int(match.group(3))
        return date(year, month, day)

    return None
