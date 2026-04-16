"""
Context Compressor — Hermes-style conversation compression for Sam.

When conversation history grows long, compress older turns into a bullet-point
summary via a cheap LLM call. This keeps the system prompt + context within
the ~8K token budget while preserving important context.

Architecture:
  - Last 5 messages: kept verbatim (recent thread)
  - Messages 6-20: compressed into a summary via LLM
  - Older than 20: handled by Memory Beast / session search
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import Conversation

logger = logging.getLogger("samva.context_compressor")

COMPRESSION_PROMPT = (
    "Summarize this conversation history. Focus on: decisions made, tasks completed, "
    "pending items, user preferences revealed, and any context needed for the current question. "
    "Format as bullet points. Max 200 words."
)


async def compress_context(db: AsyncSession, user_id: str, current_text: str) -> str:
    """
    Compress older conversation turns into a summary.

    Fetches last 20 messages, splits into old (6-20) and recent (last 5).
    If there are fewer than 8 old messages, returns empty string.
    Otherwise sends old messages to a cheap LLM for summarization.

    Args:
        db: Database session
        user_id: User identifier
        current_text: The current user message (for context awareness)

    Returns:
        Compressed summary string, or empty string if compression not needed.
    """
    try:
        # Fetch last 20 messages
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(20)
        )
        messages = list(result.scalars().all())

        if len(messages) <= 5:
            return ""  # Only recent messages, no compression needed

        # Split: recent = last 5 (indices 0-4 in desc order), old = rest
        # Messages are in desc order, so reverse for chronological
        messages.reverse()
        recent_start = max(0, len(messages) - 5)
        old_messages = messages[:recent_start]

        if len(old_messages) < 8:
            return ""  # Not enough old messages to justify compression

        # Build conversation text for compression
        conv_lines = []
        for msg in old_messages:
            timestamp = ""
            if msg.created_at:
                timestamp = msg.created_at.strftime("%d %b %I:%M %p")
            content_snippet = (msg.content or "")[:300]
            conv_lines.append(f"[{timestamp}] {msg.role}: {content_snippet}")

        conversation_text = "\n".join(conv_lines)

        # Call cheap LLM for compression
        from .orchestrator import call_llm
        summary = await call_llm(
            model_key="flash",
            system_prompt=COMPRESSION_PROMPT,
            user_message=f"Conversation to summarize:\n{conversation_text}\n\nCurrent user question: {current_text}",
            max_tokens=300,
            user_id=user_id,
        )

        if summary and len(summary.strip()) > 10:
            logger.info(
                f"[{user_id}] Compressed {len(old_messages)} old messages into "
                f"{len(summary)} chars"
            )
            return summary.strip()

        return ""

    except Exception as e:
        logger.error(f"[{user_id}] Context compression error: {e}")
        return ""
