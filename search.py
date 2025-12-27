import logging
import os
import requests
from ddgs import DDGS

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GOOGLE_CX = os.environ["GOOGLE_CX"]
GOOGLE_SEARCH_URL = os.environ["GOOGLE_SEARCH_URL"]


def _google_search(query: str, num_results: int = 10) -> list[dict]:
    """Internal Google search implementation."""
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX,
        "q": query,
        "num": num_results,
    }
    try:
        resp = requests.get(GOOGLE_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # Check for rate limit or errors in response
        if "error" in data:
            logger.warning(f"Google API error: {data['error']}")
            return []
            
    except Exception as e:
        logger.warning(f"Google search failed for '{query}': {e}")
        return []

    return [
        {
            "title": item.get("title"),
            "url": item.get("link"),
            "snippet": item.get("snippet"),
        }
        for item in data.get("items", [])
    ]


def _duckduckgo_search(query: str, num_results: int = 10) -> list[dict]:
    """Internal DuckDuckGo search implementation."""
    try:
        # DDGS().text() returns a list directly, not a dict
        results = DDGS().text(query, max_results=num_results)
        
        return [
            {
                "title": item.get("title"),
                "url": item.get("href"),
                "snippet": item.get("body"),
            }
            for item in results
        ]
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed for '{query}': {e}")
        return []


def search_with_fallback(query: str, num_results: int = 10) -> tuple[list[dict], str]:
    """
    Search with Google first, fall back to DuckDuckGo if needed.
    
    Returns:
        Tuple of (results, source) where source is 'google' or 'duckduckgo'
    """
    # Try Google first
    results = _google_search(query, num_results)
    if results:
        return results, "google"
    
    # Fall back to DuckDuckGo
    print(f"    ⚠️  Google returned no results, trying DuckDuckGo...")
    results = _duckduckgo_search(query, num_results)
    if results:
        return results, "duckduckgo"
    
    return [], "none"
