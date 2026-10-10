"""
Web search tools.

Deliberately independent of tools/windows.py: `search_web` returns
structured results over HTTP and never touches window automation. Opening a
browser to *show* a search is a separate, optional tool (`browser_search`)
built on the standard library `webbrowser` module rather than pywinauto, so
it works the same way whether or not UI automation is available.
"""
from __future__ import annotations

import urllib.parse
import webbrowser

import requests
from bs4 import BeautifulSoup

from config import Config


def search_web(query: str, max_results: int | None = None) -> dict:
    """Structured web search. Uses DuckDuckGo's HTML endpoint by default
    (no API key required). Swap this out for Bing/Google/Serper/etc. by
    replacing the implementation — callers only see success/results."""
    max_results = max_results or Config.WEB_SEARCH_MAX_RESULTS
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (WindowsAIAgent/1.0)"},
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        for result in soup.select(".result__body")[:max_results]:
            title_el = result.select_one(".result__a")
            snippet_el = result.select_one(".result__snippet")
            if not title_el:
                continue
            results.append(
                {
                    "title": title_el.get_text(strip=True),
                    "url": title_el.get("href", ""),
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                }
            )

        return {"success": True, "results": results}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"Web search failed: {exc}"}


def browser_search(query: str, browser: str = "chrome") -> dict:
    """Open the given browser (best-effort) to a search results page. Uses
    the standard `webbrowser` module rather than UI automation."""
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    try:
        controller = webbrowser.get(browser) if browser else webbrowser.get()
        opened = controller.open(url)
        if not opened:
            return {"success": False, "error": f"webbrowser could not open '{browser}'"}
        return {"success": True, "message": f"Opened {browser} to search for '{query}'", "url": url}
    except webbrowser.Error as exc:
        return {"success": False, "error": f"Browser '{browser}' not available: {exc}"}
