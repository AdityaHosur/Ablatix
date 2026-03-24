import json
import os
from crawler import crawl
from parser import clean_text
from selenium_scraper import scrape_dynamic

BASE_PATH = os.path.dirname(os.path.dirname(__file__))
OUTPUT_DIR = os.path.join(BASE_PATH, "data", "guidelines")

os.makedirs(OUTPUT_DIR, exist_ok=True)

with open("sources.json") as f:
    sources = json.load(f)

for platform, urls in sources.items():
    print(f"\n🔍 Scraping {platform}...\n")

    all_text = ""
    all_pages = []

    for url in urls:
        base_domain = url.split("/")[2]

        # ✅ Use Selenium for Instagram + X
        if "facebook.com" in url or "twitter.com" in url:
            print("⚡ Using Selenium...")
            text = scrape_dynamic(url)
            all_pages.append((url, text))

        else:
            print("🌐 Using crawler...")
            pages = crawl(url, base_domain)
            all_pages.extend(pages)

    # remove duplicate pages
    unique_pages = list(set(all_pages))

    for page_url, text in unique_pages:
        cleaned = clean_text(text)

        if cleaned:
            all_text += f"\n\n--- {page_url} ---\n\n{cleaned}"

    output_file = os.path.join(OUTPUT_DIR, f"{platform}.txt")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(all_text)

    print(f"✅ Saved: {output_file}")

print("\n🎉 Scraping completed!")