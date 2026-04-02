"""
Business Mood Detection — notices when user's message style changes.
Gentle check-in when messages get unusually short or terse.
"""

import logging
from datetime import datetime
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import Conversation

logger = logging.getLogger("samva.mood")

IST = pytz.timezone("Asia/Kolkata")

# In-memory dedup: {user_id: "YYYY-MM-DD"}
_already_sent: dict[str, str] = {}


async def check_mood(db: AsyncSession, user_id: str) -> str:
    """
    Check if user's recent messages are unusually short/terse.
    Returns a gentle check-in message or empty string.
    Only triggers once per day.
    """
    today_str = datetime.now(IST).strftime("%Y-%m-%d")

    # Dedup — once per day
    if _already_sent.get(user_id) == today_str:
        return ""

    try:
        # Get last 30 user messages (for historical baseline)
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.role == "user",
            ).order_by(Conversation.created_at.desc()).limit(30)
        )
        all_msgs = conv_result.scalars().all()

        if len(all_msgs) < 15:
            # Not enough data
            return ""

        # Recent 10 vs historical 10-30
        recent = all_msgs[:10]
        historical = all_msgs[10:30]

        if not historical:
            return ""

        # Calculate average message length
        recent_lengths = [len((m.content or "").split()) for m in recent]
        hist_lengths = [len((m.content or "").split()) for m in historical]

        recent_avg = sum(recent_lengths) / len(recent_lengths) if recent_lengths else 0
        hist_avg = sum(hist_lengths) / len(hist_lengths) if hist_lengths else 0

        if hist_avg == 0:
            return ""

        # Check for short/terse patterns
        terse_words = {"ok", "okay", "hmm", "theek", "fine", "thik", "haan", "ha",
                       "nahi", "no", "achha", "accha", "k", "kk", "ji"}

        recent_terse_count = 0
        for msg in recent:
            content = (msg.content or "").strip().lower()
            words = content.split()
            if len(words) <= 2 and any(w in terse_words for w in words):
                recent_terse_count += 1

        # Trigger conditions:
        # 1. Recent avg is < 50% of historical avg
        # 2. AND at least 4 out of 10 recent messages are terse
        is_shorter = recent_avg < (hist_avg * 0.5)
        is_terse = recent_terse_count >= 4

        if is_shorter and is_terse:
            _already_sent[user_id] = today_str
            return (
                "Aaj aapke messages thode chhote the. Sab theek hai? "
                "Main hoon agar kuch share karna ho 🤗"
            )

        return ""

    except Exception as e:
        logger.error(f"Mood check error for {user_id}: {e}", exc_info=True)
        return ""
