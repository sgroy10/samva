"""
Web search — dual engine: Perplexity Sonar (primary) + DuckDuckGo HTML (fallback).

Perplexity Sonar via OpenRouter gives real-time web results with citations.
DuckDuckGo HTML search works from datacenter IPs without captcha.
Playwright removed — Google blocks it with captcha on cloud IPs.
"""

import logging
import httpx
from urllib.parse import quote_plus

logger = logging.getLogger("samva.web_search")


async def search(query: str, user_id: str = "") -> str:
    """
    Search the web. Tries Perplexity Sonar first (best results),
    falls back to DuckDuckGo HTML scraping.
    Returns text content for LLM to summarize.
    """
    if not query or len(query.strip()) < 3:
        return ""

    # Try Perplexity Sonar first — real-time web search via OpenRouter
    result = await _search_perplexity(query, user_id)
    if result and len(result) > 50:
        logger.info(f"[{user_id}] Perplexity search: '{query[:40]}' -> {len(result)} chars")
        return result

    # Fallback: DuckDuckGo HTML
    result = await _search_duckduckgo(query, user_id)
    if result and len(result) > 50:
        logger.info(f"[{user_id}] DuckDuckGo search: '{query[:40]}' -> {len(result)} chars")
        return result

    logger.warning(f"[{user_id}] All search engines failed for: '{query[:40]}'")
    return ""


async def _search_perplexity(query: str, user_id: str = "") -> str:
    """Search using Perplexity Sonar via OpenRouter — real-time web results."""
    from ..config import settings

    if not settings.openrouter_api_key:
        return ""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://samva.in",
                    "X-Title": "Samva",
                },
                json={
                    "model": "perplexity/sonar",
                    "messages": [
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": 800,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # Log cost
            try:
                from ..database import async_session
                from .cost_tracker import log_cost
                usage = data.get("usage", {})
                async with async_session() as db:
                    await log_cost(
                        db, "perplexity", "perplexity/sonar",
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                        "web_search", user_id,
                    )
            except Exception:
                pass

            return content

    except Exception as e:
        logger.warning(f"[{user_id}] Perplexity search failed: {e}")
        return ""


async def _search_duckduckgo(query: str, user_id: str = "") -> str:
    """Search DuckDuckGo HTML — no captcha, works from any IP."""
    try:
        encoded = quote_plus(query)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={encoded}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            resp.raise_for_status()
            html = resp.text

            # Extract search results from HTML
            results = []
            import re

            # DuckDuckGo HTML results are in <a class="result__a"> and <a class="result__snippet">
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html)

            for i in range(min(len(titles), len(snippets), 8)):
                # Clean HTML tags
                title = re.sub(r'<[^>]+>', '', titles[i]).strip()
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                if title or snippet:
                    results.append(f"{title}\n{snippet}")

            return "\n\n".join(results) if results else ""

    except Exception as e:
        logger.warning(f"[{user_id}] DuckDuckGo search failed: {e}")
        return ""


async def browse_url(url: str, user_id: str = "") -> str:
    """Browse a specific URL and extract text content via httpx."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            resp.raise_for_status()
            html = resp.text

            # Basic HTML to text
            import re
            # Remove script/style
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            # Remove tags
            text = re.sub(r'<[^>]+>', ' ', text)
            # Clean whitespace
            text = re.sub(r'\s+', ' ', text).strip()

            return text[:5000]

    except Exception as e:
        logger.error(f"[{user_id}] Browse failed for '{url}': {e}")
        return ""
