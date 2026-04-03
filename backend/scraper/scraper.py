"""
Scraper module for platform guidelines.
Provides functions to scrape, clean, and organize content by platform.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Add scraper directory to path for relative imports
sys.path.insert(0, str(Path(__file__).parent))


def load_sources() -> Dict[str, List[str]]:
    """Load and parse sources.json from scraper directory."""
    sources_file = Path(__file__).parent / "sources.json"
    with open(sources_file, "r", encoding="utf-8") as f:
        return json.load(f)


def scrape_platform(platform: str, urls: List[str]) -> Tuple[str, Dict[str, any]]:
    """
    Scrape all URLs for a given platform.
    
    Args:
        platform: Platform name (e.g., 'youtube', 'instagram')
        urls: List of URLs to scrape
    
    Returns:
        Tuple of (combined_text, metadata) where metadata includes failed URLs
    """
    # Lazy imports to avoid requiring selenium/requests at module level
    from crawler import crawl
    from parser import clean_text
    from selenium_scraper import scrape_dynamic
    
    print(f"\n🔍 Scraping {platform}...")
    
    all_pages: List[Tuple[str, str]] = []
    failed_urls: List[Tuple[str, str]] = []
    
    for url in urls:
        base_domain = url.split("/")[2]
        
        try:
            # ✅ Use Selenium for Instagram + X
            if "facebook.com" in url or "twitter.com" in url:
                print(f"  ⚡ {url}")
                text = scrape_dynamic(url)
                all_pages.append((url, text))
            else:
                print(f"  🌐 {url}")
                pages = crawl(url, base_domain)
                all_pages.extend(pages)
        except Exception as e:
            print(f"  ❌ Failed: {url} - {str(e)[:50]}")
            failed_urls.append((url, str(e)))
    
    # Remove duplicate pages
    unique_pages = list(set(all_pages))
    
    all_text = ""
    for page_url, text in unique_pages:
        cleaned = clean_text(text)
        if cleaned:
            all_text += f"\n\n--- {page_url} ---\n\n{cleaned}"
    
    metadata = {
        "platform": platform,
        "source_count": len(urls),
        "scraped_count": len(unique_pages),
        "failed_urls": failed_urls,
        "total_chars": len(all_text),
    }
    
    return all_text, metadata


def scrape_all_platforms() -> Dict[str, Tuple[str, Dict]]:
    """
    Scrape all platforms defined in sources.json.
    
    Returns:
        Dict mapping platform name to (content_text, metadata)
    """
    sources = load_sources()
    results = {}
    
    for platform, urls in sources.items():
        content, metadata = scrape_platform(platform, urls)
        results[platform] = (content, metadata)
    
    return results


if __name__ == "__main__":
    # Legacy script mode for backward compatibility
    BASE_PATH = os.path.dirname(os.path.dirname(__file__))
    OUTPUT_DIR = os.path.join(BASE_PATH, "data", "guidelines")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    results = scrape_all_platforms()
    
    for platform, (content, metadata) in results.items():
        output_file = os.path.join(OUTPUT_DIR, f"{platform}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Saved: {output_file}")
    
    print("\n🎉 Scraping completed!")