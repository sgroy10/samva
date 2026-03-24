"""
Web search via Playwright — real browser-based search.
Searches Google, reads actual page content, summarizes with Gemini.
"""

import logging
import asyncio
from typing import Optional

logger = logging.getLogger("samva.web_search")

# Lazy-loaded browser
_playwright = None
_browser = None


async def _get_browser():
    """Lazy-load Playwright browser. Single instance shared across users."""
    global _playwright, _browser
    if _browser:
        return _browser

    try:
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        logger.info("Playwright browser launched")
        return _browser
    except Exception as e:
        logger.error(f"Playwright launch failed: {e}")
        return None


async def search(query: str, user_id: str = "") -> str:
    """
    Search the web using Playwright.
    Returns raw text content from search results for Gemini to summarize.
    """
    browser = await _get_browser()
    if not browser:
        return ""

    page = None
    try:
        page = await browser.new_page(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        # Search Google
        search_url = f"https://www.google.com/search?q={query}&hl=en"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        # Extract search results text
        content = await page.evaluate("""() => {
            // Remove unwanted elements
            const remove = document.querySelectorAll('script, style, nav, footer, header, [role="navigation"], .g-blk, #botstuff');
            remove.forEach(el => el.remove());

            // Get search result snippets
            const results = [];
            const searchResults = document.querySelectorAll('.g, .tF2Cxc, [data-sokoban-container]');
            searchResults.forEach((el, i) => {
                if (i >= 8) return;
                const title = el.querySelector('h3')?.textContent || '';
                const snippet = el.querySelector('.VwiC3b, .IsZvec, .st')?.textContent || '';
                const link = el.querySelector('a')?.href || '';
                if (title || snippet) {
                    results.push(`${title}\\n${snippet}\\n${link}`);
                }
            });

            if (results.length > 0) return results.join('\\n\\n');

            // Fallback: get main text content
            return document.body.innerText.substring(0, 4000);
        }""")

        logger.info(f"[{user_id}] Search: '{query}' -> {len(content)} chars")
        return content[:5000]

    except Exception as e:
        logger.error(f"[{user_id}] Search failed for '{query}': {e}")
        return ""
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def browse_url(url: str, user_id: str = "") -> str:
    """Browse a specific URL and extract text content."""
    browser = await _get_browser()
    if not browser:
        return ""

    page = None
    try:
        page = await browser.new_page(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        content = await page.evaluate("""() => {
            const remove = document.querySelectorAll('script, style, nav, footer, header, aside, [role="navigation"], [role="banner"]');
            remove.forEach(el => el.remove());
            return document.body.innerText.substring(0, 5000);
        }""")

        return content

    except Exception as e:
        logger.error(f"[{user_id}] Browse failed for '{url}': {e}")
        return ""
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
