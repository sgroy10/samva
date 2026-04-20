"""
Hermes-style Background Memory Review.

After every 5th user message, a background LLM call silently reviews
the recent conversation and saves any user preferences, corrections,
habits, or facts to UserMemory — without the user ever asking.

This is what makes Sam actually learn and remember over time.
"""

import asyncio
import json
import logging
import re
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from ..models import UserMemory, Conversation
from ..database import async_session
from .llm import call_gemini

logger = logging.getLogger("samva.memory_review")

# In-memory message counter — resets on service restart (intentional)
_message_counts: dict[str, int] = defaultdict(int)

REVIEW_INTERVAL = 5  # Every 5th user message

REVIEW_PROMPT = """You are a memory extraction system. Review this conversation between a user and their AI assistant Sam.

Extract any NEW user preferences, corrections, habits, relationships, health info, work patterns, dietary choices, or behavioral expectations worth remembering for future conversations.

Return a JSON array of {key, value} pairs. Keys should be short snake_case identifiers.
Examples: {"key": "diet_preference", "value": "vegetarian"}, {"key": "wife_name", "value": "Priya"}

Rules:
- Only include NEW, specific, personal information
- Do NOT include generic facts or things obvious from context
- Do NOT include temporary states like "user is asking about gold"
- Return empty array [] if nothing new worth saving
- Maximum 5 items per review

Return ONLY the JSON array, nothing else."""


def should_trigger_review(user_id: str) -> bool:
    """Increment counter and check if we should trigger a background review."""
    _message_counts[user_id] += 1
    return _message_counts[user_id] % REVIEW_INTERVAL == 0


async def background_memory_review(user_id: str, recent_messages: list[dict]):
    """
    Background task: review recent conversation and save facts to UserMemory.
    Uses its own DB session — never shares the request's session.
    MUST be called via asyncio.create_task() to avoid blocking.
    """
    try:
        # Format messages for the prompt
        conversation_text = "\n".join(
            f"{m['role']}: {m['content'][:300]}" for m in recent_messages
        )

        # Cheap LLM call — short max_tokens
        raw = await call_gemini(
            REVIEW_PROMPT,
            conversation_text,
            max_tokens=300,
            user_id=user_id,
        )

        # Parse the JSON array
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Find the array
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            logger.info(f"[memory-review] No facts extracted for {user_id}")
            return

        items = json.loads(text[start:end + 1])

        if not items or not isinstance(items, list):
            logger.info(f"[memory-review] Empty review for {user_id}")
            return

        # Validate and upsert each fact using a NEW db session
        VALID_KEY_PATTERN = re.compile(r'^[a-z][a-z0-9_]{2,50}$')
        BLOCKED_KEYS = {"user_query", "current_topic", "last_message", "session_id",
                        "temporary", "test", "debug", "unknown"}

        saved = []
        async with async_session() as db:
            try:
                for item in items[:5]:  # Cap at 5
                    key = item.get("key", "").strip().lower().replace(" ", "_")
                    value = item.get("value", "")

                    if not key or not value:
                        continue

                    # Validate key format
                    if not VALID_KEY_PATTERN.match(key):
                        logger.warning(f"[memory-review] Rejected invalid key: {key}")
                        continue

                    # Block temporary/test keys
                    if key in BLOCKED_KEYS or key.startswith("_"):
                        continue

                    # Ensure value is string and not too long
                    if not isinstance(value, str):
                        value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                    value = value[:500]  # Cap value length

                    # Don't save vague/generic values
                    if value.lower() in ("unknown", "not specified", "n/a", "none", "null"):
                        continue

                    stmt = pg_insert(UserMemory).values(
                        user_id=user_id, key=key, value=value
                    ).on_conflict_do_update(
                        constraint="uq_user_memory_user_key",
                        set_={"value": value}
                    )
                    await db.execute(stmt)
                    saved.append(f"{key}={value}")

                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"[memory-review] DB error for {user_id}: {e}")
                return

        if saved:
            logger.info(f"[memory-review] Saved {len(saved)} facts for {user_id}: {', '.join(saved)}")
        else:
            logger.info(f"[memory-review] No new facts for {user_id}")

    except Exception as e:
        logger.error(f"[memory-review] Error for {user_id}: {e}", exc_info=True)


async def get_recent_messages(user_id: str, limit: int = 10) -> list[dict]:
    """Fetch last N messages for a user using a fresh DB session."""
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.created_at.desc())
                .limit(limit)
            )
            messages = result.scalars().all()
            return [
                {"role": m.role, "content": m.content or ""}
                for m in reversed(list(messages))
            ]
        except Exception as e:
            logger.error(f"[memory-review] Failed to fetch messages for {user_id}: {e}")
            return []


async def get_memory_summary(db, user_id: str) -> str:
    """
    Read ALL UserMemory for a user and format as a clean context block
    wrapped in <memory-context> XML tags (Hermes memory context fencing).
    """
    try:
        result = await db.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                ~UserMemory.key.startswith("_"),  # Skip internal keys
            )
        )
        memories = result.scalars().all()

        if not memories:
            return ""

        lines = [f"- {m.key}: {m.value}" for m in memories]
        content = "\n".join(lines)

        return f"<memory-context>\n{content}\n</memory-context>"
    except Exception as e:
        logger.error(f"[memory-review] Failed to build memory summary for {user_id}: {e}")
        return ""
