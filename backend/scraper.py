import cloudscraper
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

def extract_site_blueprint(url):
    """
    Scrapes a reference website and extracts its structural layout blueprint,
    headings, color themes, and section architecture.
    """
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )
    
    try:
        response = scraper.get(url, timeout=10)
        if response.status_code != 200:
            return {"error": f"Failed to fetch site, status code: {response.status_code}"}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        domain = urlparse(url).netloc

        # Extract basic site identity
        title = soup.title.string.strip() if soup.title and soup.title.string else domain
        meta_desc = soup.find("meta", attrs={"name": "description"})
        description = meta_desc.get("content", "").strip() if meta_desc else "N/A"

        # Extract layout section structure
        sections = []
        for tag in soup.find_all(['header', 'section', 'main', 'footer']):
            tag_name = tag.name
            tag_id = tag.get('id', '')
            tag_class = " ".join(tag.get('class', []))
            
            # Find headings inside this section
            headings = [h.get_text(strip=True) for h in tag.find_all(['h1', 'h2', 'h3']) if h.get_text(strip=True)]
            
            # Find primary buttons or calls to action
            ctas = [a.get_text(strip=True) for a in tag.find_all(['a', 'button']) 
                    if a.get_text(strip=True) and len(a.get_text(strip=True)) < 30]
            
            if headings or ctas:
                sections.append({
                    "type": tag_name,
                    "id": tag_id,
                    "class": tag_class,
                    "headings": headings[:3],
                    "sample_ctas": ctas[:2]
                })

        # Extract inline colors / hex codes from style tags
        colors = set()
        style_tags = soup.find_all('style')
        for style in style_tags:
            found_colors = re.findall(r'#(?:[0-9a-fA-F]{3}){1,2}\b', style.text)
            colors.update(found_colors)

        return {
            "url": url,
            "domain": domain,
            "title": title,
            "description": description,
            "sections_found": len(sections),
            "layout_blueprint": sections[:6],  # Top 6 major structural blocks
            "extracted_colors": list(colors)[:8]
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # Test with a quick example site
    test_url = "https://www.wikipedia.org"
    print("Testing Scraper Engine...")
    result = extract_site_blueprint(test_url)
    print("\n--- Extracted Blueprint Output ---")
    print(result)