"""
article_cleaner.py

Mostly vibe coded, edited.
Data cleaning module for scraped police articles.
Sits between raw JSON data and the normalizer/DB insertion layer.

Handles:
    - Unicode normalization (NFKC)
    - Whitespace collapsing (\xa0, \t, \n, multiple spaces)
    - Boilerplate removal (social sharing links, print links)
    - Field-specific cleaning (author byline extraction, title caps, content stripping)
    - Length validation with warnings
    - Null/empty coercion

Usage:
    from article_cleaner import clean_article_fields, clean_location_fields

    cleaned = clean_article_fields(raw_result_dict)
    location = clean_location_fields(raw_result_dict)
"""

import base64
import re
import unicodedata
import logging
from datetime import date

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Boilerplate patterns found in policie.cz HTML
# These leak into content/author via get_text()
# ──────────────────────────────────────────────

# Social/print boilerplate that appears at the end of articles
BOILERPLATE_PATTERNS = [
    r'vytisknout\s*',
    r'e-mailem\s*',
    r'X\s+Corp\.\s*',
    r'Facebook\s*',
    r'Sdílet na X Corp\.\s*',
    r'Sdílet na Facebooku\s*',
]

# Compiled once — matches any of the boilerplate fragments
_BOILERPLATE_RE = re.compile(
    '|'.join(BOILERPLATE_PATTERNS),
    re.IGNORECASE
)

# Author line often has trailing metadata: "por. Bc. Jan Novák\nOŘ Plzeň | 25. 5. 2017"
# We want just the name part before the first newline or pipe
_AUTHOR_TRAILING_META_RE = re.compile(
    r'\s*[|\n].*$',  # everything after first pipe or newline
    re.DOTALL
)

# Email addresses that leak into author fields
_EMAIL_RE = re.compile(r'\S+@\S+\.\S+')

# Field length sanity limits (not hard truncation — logs a warning and truncates)
FIELD_LIMITS = {
    'title': 500,
    'author': 200,
    'description': 2000,
    'content': 100_000,  # ~100k chars is generous for an article
    'source': 255,
    'url': 2048,
}


# ──────────────────────────────────────────────
# Core text cleaning
# ──────────────────────────────────────────────

def normalize_unicode(text: str) -> str:
    """ NFKC normalization: decomposes then recomposes characters.
        Converts things like \xa0 (non-breaking space) to regular space,
        fullwidth characters to ASCII equivalents, etc.
    """
    return unicodedata.normalize('NFKC', text)


def collapse_whitespace(text: str) -> str:
    """ Replace all runs of whitespace (including \xa0, \t, \n) with a single space.
    """
    return re.sub(r'\s+', ' ', text)


def clean_text(text: str | None) -> str | None:
    """ General-purpose text cleaning pipeline.

        1. NFKC Unicode normalization
        2. Collapse all whitespace to single spaces
        3. Strip leading/trailing whitespace

        Returns None if input is None or result is empty.
    """
    if not text:
        return None

    text = normalize_unicode(text)
    text = collapse_whitespace(text)
    text = text.strip()

    return text if text else None


def strip_boilerplate(text: str) -> str:
    """ Remove known policie.cz boilerplate fragments from text.
        These are social sharing / print link labels that leak through get_text().
    """
    return _BOILERPLATE_RE.sub('', text)


# TODO if we truncate we maybe get a log but that's it, make a cleaner fallback
def enforce_length(text: str | None, field_name: str, url: str = '') -> str | None:
    """ Check field length against sanity limits. Log warning and truncate if exceeded.
    """
    if text is None:
        return None

    limit = FIELD_LIMITS.get(field_name)
    if limit and len(text) > limit:
        logger.warning(
            f"Field '{field_name}' exceeds {limit} chars ({len(text)} chars) "
            f"for article '{url[:80]}' — truncating"
        )
        text = text[:limit]

    return text


# ──────────────────────────────────────────────
# Field-specific cleaners
# ──────────────────────────────────────────────

def clean_title(raw_title: str | None, url: str = '') -> str | None:
    """ Clean article title.

        - Standard text cleaning (unicode, whitespace)
        - Remove boilerplate fragments
        - Enforce length limit
    """
    title = clean_text(raw_title)
    if not title:
        return None

    title = strip_boilerplate(title)
    title = collapse_whitespace(title).strip()  # re-collapse after boilerplate removal
    title = enforce_length(title, 'title', url)

    return title if title else None


def clean_author(raw_author: str | None, url: str = '') -> str | None:
    """ Clean author field.

        The scraper often pulls in the full byline block:
            "por. Bc. Richard Palát\nSTP Ostrava | 25. 5. 2017\n\nvytisknout ..."

        This extracts just the name portion:
        1. Unicode normalize (but DON'T collapse whitespace yet — need newlines intact)
        2. Cut at first newline or pipe (trailing org/date metadata)
        3. Strip boilerplate
        4. Remove email addresses
        5. Now collapse whitespace
        6. Enforce length
    """
    if not raw_author:
        return None

    # Normalize unicode but keep newlines — we need them for the cut
    author = normalize_unicode(raw_author)

    # Cut at first newline or pipe BEFORE collapsing whitespace
    # This is the key: "por. Bc. Richard Palát\nSTP Ostrava | ..." → "por. Bc. Richard Palát"
    author = re.split(r'[\n|]', author)[0]

    author = strip_boilerplate(author)
    author = _EMAIL_RE.sub('', author)
    author = re.sub(r'[,;]\s*$', '', author)  # trailing comma/semicolon after email removal
    author = collapse_whitespace(author).strip()
    author = enforce_length(author, 'author', url)

    # If after all cleaning we have basically nothing, return None
    if not author or len(author) < 2:
        return None

    return author


def clean_content(raw_content: str | None, url: str = '') -> str | None:
    """ Clean article content (the big one).

        1. Standard text cleaning (unicode, whitespace)
        2. Strip boilerplate (social links, print links)
        3. Re-collapse whitespace
        4. Enforce length

        Note: This does NOT strip HTML tags — that should be done in the scraper
        via get_text(). If HTML is somehow still present, the content will be
        oversized and the length check will warn about it.
    """
    content = clean_text(raw_content)
    if not content:
        return None

    content = strip_boilerplate(content)
    content = collapse_whitespace(content).strip()
    content = enforce_length(content, 'content', url)

    return content if content else None


def clean_description(raw_desc: str | None, url: str = '') -> str | None:
    """ Clean article description/subtitle.
    """
    desc = clean_text(raw_desc)
    if not desc:
        return None

    desc = strip_boilerplate(desc)
    desc = collapse_whitespace(desc).strip()
    desc = enforce_length(desc, 'description', url)

    return desc if desc else None


def clean_url(raw_url: str | None) -> str | None:
    """ Clean and validate URL.
    """
    url = clean_text(raw_url)
    if not url:
        return None
    return enforce_length(url, 'url', url)


def clean_source(raw_source: str | None) -> str | None:
    """ Clean source identifier.
    """
    source = clean_text(raw_source)
    if not source:
        return None
    return enforce_length(source, 'source')


# ──────────────────────────────────────────────
# Location cleaning
# ──────────────────────────────────────────────<

def clean_location_field(raw_value: str | None) -> str | None:
    """ Clean a location field (region, district, municipality).
        Just standard text cleaning — these are short strings.
    """
    return clean_text(raw_value)


# ──────────────────────────────────────────────
# Date
# ──────────────────────────────────────────────<

def parse_date_fix(date_str: str) -> date | None:
    """ Hotfix for some dates being corrupted (either invalid isostring or bad format all together).
        Upstream cause should be fixed, keep this as a safety net.
    """
    if not date_str:
        return None
    try:
        year, month, day = date_str.split('-')
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


# ──────────────────────────────────────────────
# HTML
# ──────────────────────────────────────────────<

def is_base64(s):
    pattern = re.compile(r'^[A-Za-z0-9+/]*={0,2}$')
    if not pattern.match(s) or len(s) % 4 != 0:
        return False
    try:
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False


def clean_html(html: str) -> str:
    if is_base64(html):
        return base64.b64decode(html).decode("utf-8", errors="replace")
    return html


# ──────────────────────────────────────────────
# High-level API for the normalizer
# ──────────────────────────────────────────────

def clean_article_fields(result: dict) -> dict:
    """ Clean all article fields from a raw scraped result dict.

        Takes the raw result dict from JSON and returns a cleaned dict
        with the same keys, ready for DbArticleTable construction.

        This is the main entry point — call this from police_normalizer
        instead of passing raw values through.
    """
    url = (result.get("url") or "").strip()
    html = result.get("html") or result.get("html_base64")
    return {
        "source": clean_source(result.get("source")),
        "url": clean_url(url),
        "year": result.get("year"),  # int | str | None
        "date": parse_date_fix(result.get("date")),
        "author": clean_author(result.get("author"), url),
        "title": clean_title(result.get("title"), url),
        "description": clean_description(result.get("description"), url),
        "content": clean_content(result.get("content"), url),
        "html": clean_html(html), # DO NOT REMOVE!!! Legacy
    }


def clean_location_fields(result: dict) -> dict:
    """ Clean all location fields from a raw scraped result dict.
    """
    return {
        "region": clean_location_field(result.get("region")),
        "district": clean_location_field(result.get("district")),
        "municipality": clean_location_field(result.get("municipality")),
    }
