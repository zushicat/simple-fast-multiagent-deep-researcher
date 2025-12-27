import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright.sync_api import Error as PlaywrightError
from bs4 import BeautifulSoup
import requests

from markdownify import markdownify as md

def _select_main_content(soup: BeautifulSoup):
    # 1. Strong semantic signals
    for candidate in (
        soup.find("main"),
        soup.find("article"),
        soup.find(attrs={"role": "main"}),
        soup.find(attrs={"itemprop": "articleBody"}),
    ):
        if candidate:
            return candidate

    # 2. Known content class / id patterns
    CONTENT_KEYS = [
        "content",
        "post-content",
        "entry-content",
        "article-content",
        "markdown-body",
        "prose",
        "story-body",
    ]

    def has_content_hint(tag):
        if tag.name != "div":
            return False
        classes = " ".join(tag.get("class", [])).lower()
        tag_id = (tag.get("id") or "").lower()
        return any(key in classes or key in tag_id for key in CONTENT_KEYS)

    hinted = soup.find(has_content_hint)
    if hinted:
        return hinted

    # 3. Text-dense fallback (article-like scoring)
    best_candidate = None
    best_score = 0

    for tag in soup.find_all("div"):
        # Skip obvious non-content containers
        if tag.find(["nav", "aside", "footer", "header"]):
            continue

        paragraphs = len(tag.find_all("p"))
        headings = len(tag.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))
        list_items = len(tag.find_all("li"))
        links = len(tag.find_all("a"))

        text_length = len(tag.get_text(strip=True))
        if text_length < 200:
            continue

        score = (
            paragraphs * 3
            + headings * 5
            + list_items
            - links * 2
        )

        if score > best_score:
            best_score = score
            best_candidate = tag

    if best_candidate:
        return best_candidate

    # 4. Last resort
    return soup.body


def _create_markdown(main_content, soup: BeautifulSoup) -> str | None:
    if not main_content:
        return None

    # Convert main content HTML to Markdown
    try:
        markdown = md(
            str(main_content),
            heading_style="ATX",
            bullets="-",
            strong_em_symbol="**",
        )
    except Exception:
        # Fallback: plain text if markdownify is unavailable
        text = main_content.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        markdown = "\n".join(lines)

    # Prepend page title as H1
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    if title:
        markdown = f"# {title}\n\n{markdown}"

    # Normalize whitespace
    lines = [line.rstrip() for line in markdown.splitlines()]
    markdown = "\n".join(lines)

    # Collapse excessive blank lines
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    # Remove empty headings
    markdown = re.sub(r"^#+\s*$", "", markdown, flags=re.MULTILINE)

    return markdown.strip() or None


def _process_html(html: str, text_only: bool):
    """Parse and extract content from HTML."""
    soup = BeautifulSoup(html, 'html.parser')

    if not text_only:
        if soup.body:
            return str(soup.body)
        return str(soup)
    
    # Remove non-content elements
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
        tag.decompose()
    
    main_content = _select_main_content(soup)
    return _create_markdown(main_content, soup)


def is_likely_download_url(url: str) -> bool:
    """Check if URL is likely to trigger a download."""
    download_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.tar', '.gz']
    url_lower = url.lower()
    return any(url_lower.endswith(ext) or f"{ext}?" in url_lower for ext in download_extensions)


def _simple_scraper(url: str, text_only: bool = True, timeout: int = 10) -> str | None:
    """Fast HTTP-based scraper for static sites."""
    if is_likely_download_url(url):
        return None  # Skip downloads
    
    try:
        resp = requests.get(
            url, 
            timeout=timeout, 
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            allow_redirects=True
        )
        resp.raise_for_status()
        
        # Check content type - skip non-HTML
        content_type = resp.headers.get('Content-Type', '')
        if 'text/html' not in content_type and 'application/xhtml' not in content_type:
            return None
        
        return _process_html(html=resp.text, text_only=text_only)
    except Exception:
        return None


def _scrape_with_playwright(
    url: str, 
    text_only: bool = True, 
    timeout: int = 15000,  # 15 seconds
    wait_after_load: int = 1000  # 1 second
) -> str | None:
    """
    Scrape using Playwright for JavaScript-rendered sites.
    
    Uses domcontentloaded instead of networkidle for reliability.
    """
    if is_likely_download_url(url):
        return None
    
    browser = None
    try:
        with sync_playwright() as p:
            # Launch with minimal resource usage
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-gpu',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-extensions',
                ]
            )
            
            context = browser.new_context(
                # Block unnecessary resources for faster loading
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            
            page = context.new_page()
            
            # Block downloads
            page.on("download", lambda download: download.cancel())
            
            # Block heavy resources to speed up loading
            page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf}", 
                      lambda route: route.abort())
            
            # Navigate with explicit timeout and domcontentloaded (more reliable)
            response = page.goto(
                url, 
                wait_until="domcontentloaded",  # Changed from networkidle
                timeout=timeout
            )
            
            # Check if we got a valid response
            if response and response.status >= 400:
                return None
            
            # Brief wait for JS to execute
            page.wait_for_timeout(wait_after_load)
            
            html = page.content()
            
            context.close()
            browser.close()
            
            return _process_html(html=html, text_only=text_only)
            
    except PlaywrightTimeout:
        return None
    except PlaywrightError as e:
        error_msg = str(e).lower()
        # Handle download attempts gracefully
        if 'download' in error_msg:
            return None
        return None
    except Exception:
        return None
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass


def fetch_url(url: str, text_only: bool = True) -> str | None:
    """
    Smart fetch: try simple scraper first, fall back to Playwright.
    
    This is the main entry point for fetching content.
    """
    # Skip obvious downloads
    if is_likely_download_url(url):
        return None
    
    # Try fast path first
    content = _simple_scraper(url, text_only=text_only)
    
    if content and len(content) > 200:  # Got meaningful content
        return content
    
    # Fall back to Playwright for JS-rendered sites
    return _scrape_with_playwright(url, text_only=text_only)


if __name__ == "__main__":
    url = "https://www.helpguide.org/wellness/pets/mood-boosting-power-of-dogs"
    
    content = fetch_url(url)
    print("-" * 100)
    print(content[:2000] if content else "No content found")