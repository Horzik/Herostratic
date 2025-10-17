# Extract just the topic keywords from a url, ignore dates
def get_article_slug(url):
    import re
    match = re.search(r'pi_?\d*_?([a-z]+)\.html', url)
    return match.group(1) if match else url

