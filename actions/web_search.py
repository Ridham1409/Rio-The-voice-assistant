"""
RIO v1 — actions/web_search.py
Opens the default browser and searches Google.
"""

import webbrowser
import urllib.parse
from core.logger import get_logger

log = get_logger(__name__)


def search_web(query: str, cfg: dict) -> str:
    """
    Google `query` in the default browser.
    Returns a status string.
    """
    query = query.strip()
    if not query:
        return "No search query provided."

    base = cfg.get("actions", {}).get("search_engine", "https://www.google.com/search?q=")
    url  = base + urllib.parse.quote_plus(query)

    log.info(f"Searching: {url}")
    try:
        webbrowser.open(url)
        return f"Searched Google for: {query}"
    except Exception as e:
        log.error(f"Web search failed: {e}")
        return f"Search failed: {e}"
