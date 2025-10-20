# GET THE URL AND TITLE DIRECTLY IN THE MODULE LIKE THIS
# link = soup.select_one('a[href*="clanek"]')
# url = link['href']
# title = link.get_text(strip=True)
from config import POLICE_ARCHIVES_FP

BASE_POLICE_URL = "https://policie.gov.cz/"
BASE_DENIK_URL_END = "denik.cz/"

ARCHIVE_SITE_CONFIGS = {
    # todo this is *bit* confusing, probably should refactor
    BASE_POLICE_URL: {
        'listing_selectors':{
            # Mostly redundant, we are just getting the URLs
            'article_selector': 'div.article',
            'article_list': 'div#articleList',
            'article_title': 'h3 a',
            'article_link': 'h3 a',
            'article_description': 'div.infobox > p',
            'author': 'p.authorDate',
            'date': 'p.authorDate',
            'last_page': 'span.stranky a:not(.next)'
        },
        'article_selectors': {
            'title': 'div#content > h1',
            'content': 'div#content',
            'description': 'div#content > p:first-of-type',
            'image': 'div#content img',
            'documents': 'div.related',
            'document_links': 'div.related a.dark',
            'pictures': 'div.graybox, div#graybox, div.in',
            'breadcrumbs': 'p.breadcrumbs',
            'drobek': 'div#siteNavigation'
        },
        'archive_selectors': {
            'year_links': 'div#content ul li a',
            'municipality': 'div#subHPtitle img',  # Use this and THEN "municipality = element['alt']"
            'archive_link': 'a[href*="archiv"]',
            'news_link': 'ul.dots a[href*="zpravodaj"]',
            'content_archiv': 'div#content a[href*="archiv"]',
            'zpravodajstvi': 'div#content a[href*="zpravodaj"]',
        },
        'pagination': {
            'next_page': 'a.next',
        },
        'parsing':{
            'author': lambda text: ' '.join(text.split()).split('-')[0],
            'date': lambda text: text.split('-')[1].strip(),
            'description': lambda text: ' '.join(text.split()),
        },
        'rate_limit': 2,
    }
}

DOMAIN_SELECTORS = {
    'Královéhrad' : 'div#content > table a',
    'Jihomor': 'p:nth-of-type(2) a',
    ('Vysočina',
     'Zlk',
     'Zlínsk'
     ): 'table tr td a',
}


TABLE_SELECTORS = [
    'table td a',
    '#content p a',
    'ul li a',
]

POLICE_SELECTOR = ARCHIVE_SITE_CONFIGS[BASE_POLICE_URL]
POLICE_ARCHIVE_SELECTORS = ARCHIVE_SITE_CONFIGS[BASE_POLICE_URL]['archive_selectors']