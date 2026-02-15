from datetime import date

from config import CZECH_MONTHS


def parse_czech_date(date_str: str) -> str | None:
    """Get czech date from various formats.
       Returns an iso string as 'YEAR-MONTH-DAY'.
    """
    import re

    if not date_str:
        return None

    date_str = date_str.strip().rstrip('.')

    # Try numeric first: "6. 10. 2020"
    match = re.match(r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})', date_str)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        iso_date = date(year, month, day).isoformat()
        return iso_date

    # Try Czech month name: "12. září 2020"
    match = re.match(r'(\d{1,2})\.\s*(\w+)\s+(\d{4})', date_str)
    if match:
        day = int(match.group(1))
        month = int(CZECH_MONTHS.get(match.group(2).lower()))
        year = int(match.group(3))
        iso_date = date(year, month, day).isoformat()
        return iso_date

    return None
