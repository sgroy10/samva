"""
Session Search — PostgreSQL full-text search across Sam's conversation history.

Provides two capabilities:
1. search_past_sessions() — FTS search with ILIKE fallback
2. smart_session_recall() — LLM-summarized recall for "remember when" queries

Used by Memory Beast for deeper recall and by context compressor for
targeted history retrieval.
"""

import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sql_text

logger = logging.getLogger("samva.session_search")


async def search_past_sessions(
    db: AsyncSession, user_id: str, query: str, limit: int = 5
) -> str:
    """
    Search past conversation sessions using PostgreSQL full-text search.
    Falls back to ILIKE if FTS fails (e.g., no GIN index).

    Args:
        db: Database session
        user_id: User identifier
        query: Search query text
        limit: Maximum results to return

    Returns:
        Formatted string of matching past messages, or empty string.
    """
    if not query or len(query.strip()) < 3:
        return ""

    results = []

    # Try full-text search first
    try:
        fts_query = sql_text(
            "SELECT role, content, created_at FROM conversations "
            "WHERE user_id = :uid "
            "AND to_tsvector('english', content) @@ plainto_tsquery('english', :q) "
            "ORDER BY created_at DESC LIMIT :lim"
        )
        fts_result = await db.execute(
            fts_query, {"uid": user_id, "q": query, "lim": limit}
        )
        rows = fts_result.fetchall()

        if rows:
            for row in rows:
                role, content, created_at = row
                date_str = _format_date(created_at)
                snippet = (content or "")[:200]
                results.append(f"From {date_str}: [{role}] {snippet}")

            logger.info(
                f"[{user_id}] FTS search for '{query[:30]}' found {len(results)} results"
            )
            return "\n".join(results)

    except Exception as e:
        logger.warning(f"[{user_id}] FTS search failed, falling back to ILIKE: {e}")
        try:
            await db.rollback()
        except Exception:
            pass

    # Fallback: ILIKE search
    try:
        # Split query into words and search for each
        words = [w.strip() for w in query.split() if len(w.strip()) > 2]
        if not words:
            return ""

        # Build ILIKE conditions for each word
        like_conditions = " OR ".join(
            f"content ILIKE :w{i}" for i in range(len(words))
        )
        params = {"uid": user_id, "lim": limit}
        for i, word in enumerate(words):
            params[f"w{i}"] = f"%{word}%"

        ilike_query = sql_text(
            f"SELECT role, content, created_at FROM conversations "
            f"WHERE user_id = :uid AND ({like_conditions}) "
            f"ORDER BY created_at DESC LIMIT :lim"
        )
        ilike_result = await db.execute(ilike_query, params)
        rows = ilike_result.fetchall()

        for row in rows:
            role, content, created_at = row
            date_str = _format_date(created_at)
            snippet = (content or "")[:200]
            results.append(f"From {date_str}: [{role}] {snippet}")

        logger.info(
            f"[{user_id}] ILIKE search for '{query[:30]}' found {len(results)} results"
        )
        return "\n".join(results)

    except Exception as e:
        logger.error(f"[{user_id}] Session search failed completely: {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        return ""


async def smart_session_recall(
    db: AsyncSession, user_id: str, query: str
) -> str:
    """
    LLM-powered recall for "remember when" type queries.

    Searches past sessions, then summarizes relevant matches into
    a concise 2-3 sentence response.

    Args:
        db: Database session
        user_id: User identifier
        query: The user's recall query

    Returns:
        Summarized recall string, or empty string if nothing found.
    """
    try:
        raw_results = await search_past_sessions(db, user_id, query, limit=5)

        if not raw_results or len(raw_results.strip()) < 10:
            return ""

        # Summarize via cheap LLM
        from .orchestrator import call_llm
        summary = await call_llm(
            model_key="flash",
            system_prompt=(
                "The user is asking about something from past conversations. "
                "Summarize the relevant past context in 2-3 sentences. "
                "Be specific about dates, people, and details mentioned."
            ),
            user_message=(
                f"User's question: {query}\n\n"
                f"Matching past conversations:\n{raw_results}"
            ),
            max_tokens=300,
            user_id=user_id,
        )

        if summary and len(summary.strip()) > 10:
            logger.info(
                f"[{user_id}] Smart recall for '{query[:30]}' produced "
                f"{len(summary)} chars"
            )
            return summary.strip()

        return ""

    except Exception as e:
        logger.error(f"[{user_id}] Smart session recall error: {e}")
        return ""


def _format_date(created_at) -> str:
    """Format a datetime for display."""
    if not created_at:
        return "unknown date"
    try:
        if isinstance(created_at, datetime):
            return created_at.strftime("%d %b %Y, %I:%M %p")
        return str(created_at)
    except Exception:
        return "unknown date"
