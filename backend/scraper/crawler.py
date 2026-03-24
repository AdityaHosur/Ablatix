import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

visited = set()

ALLOWED = ["policy", "guideline", "rules", "safety"]

def crawl(url, base_domain, depth=0, max_depth=2):
    if depth > max_depth or url in visited:
        return []

    visited.add(url)

    try:
        res = requests.get(url, timeout=5)
        soup = BeautifulSoup(res.text, "lxml")
    except:
        return []

    pages = [(url, soup.get_text())]

    for link in soup.find_all("a", href=True):
        full_url = urljoin(url, link["href"])

        if base_domain in full_url and any(k in full_url.lower() for k in ALLOWED):
            pages.extend(crawl(full_url, base_domain, depth + 1, max_depth))

    return pages