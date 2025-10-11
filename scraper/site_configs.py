# GET THE URL AND TITLE DIRECTLY IN THE MODULE LIKE THIS
# link = soup.select_one('a[href*="clanek"]')
# url = link['href']
# title = link.get_text(strip=True)

ARCHIVE_SITE_CONFIGS = {
    "https://policie.gov.cz/": {
        'listing_selectors':{
            'article_title': 'a[href*="clanek"]',
            'article_link': 'a[href*="clanek"]',
            'article_description': 'div.infobox > p',
            'author': 'p.authorDate',
            'date': 'p.authorDate',
        },
        'article_selectors': {
            'title': 'div#content > h1',
            'content': 'div#content',
            'description': 'div#content p:first-of-type',
            'image': 'div#content img',
            'has_documents': 'div.related',
            'document_links': 'div.related a.dark',
        },
        'pagination': {
            'next_button': 'a.next',
        },
        'parsing':{
            'author': lambda text: text.split('-')[0].strip(),
            'date': lambda text: text.split('-')[1].strip(),
        },
        'rate_limit': 2,
    }
}


GET_ARCHIVE_SITE_CONFIGS = {
    'archive_link': 'a[href*="archiv"]',
    'news_link': 'ul.dots a[href*="zpravodaj"]',
    'content_archiv': 'div#content a[href*="archiv"]',
    'zpravodajstvi': 'div#content a[href*="zpravodaj"]',
}
