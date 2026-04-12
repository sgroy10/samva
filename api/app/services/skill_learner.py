"""
Hermes-Style Skill Learner — Sam learns from successful interactions.

When Sam handles a pattern 3+ times successfully:
1. Detect the pattern (what user keeps asking)
2. Extract the solution template (how Sam responded)
3. Create a reusable shortcut (instant next time)

Example:
- User asks "22k 5 gram ring kitna" → Sam calculates → user happy
- User asks "18k 3 gram earring price" → Sam calculates → user happy
- User asks "24k 10 gram coin kitna" → TRIGGER: Sam creates "jewelry_price" skill
  → Next time: instant calculation without full LLM call

This is what makes Sam feel like it's LEARNING and getting smarter.
"""

import logging
from datetime import datetime, timedelta
from collections import Counter
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ..models import Conversation, UserMemory

logger = logging.getLogger("samva.skill_learner")
IST = pytz.timezone("Asia/Kolkata")

# Patterns Sam can learn from repeated interactions
LEARNABLE_PATTERNS = {
    "daily_greeting": {
        "triggers": ["good morning", "subah", "morning", "suprabhat"],
        "min_occurrences": 5,
        "learn_type": "preference",
        "description": "User's preferred morning greeting style",
    },
    "gold_check_time": {
        "triggers": ["gold rate", "sona ka bhav", "gold price", "gold kitna"],
        "min_occurrences": 3,
        "learn_type": "schedule",
        "description": "When user typically checks gold rates",
    },
    "favorite_format": {
        "triggers": ["brief", "summary", "report", "list"],
        "min_occurrences": 3,
        "learn_type": "format",
        "description": "How user prefers information presented",
    },
    "response_length": {
        "triggers": [],  # Detected from all conversations
        "min_occurrences": 10,
        "learn_type": "style",
        "description": "How long/short user wants responses",
    },
}


async def learn_from_interactions(db: AsyncSession, user_id: str) -> list:
    """
    Analyze recent successful interactions and extract learnings.
    Called by pattern_watcher every 15 min.
    Returns list of learned behaviors.
    """
    learned = []
    cutoff = datetime.now(IST) - timedelta(days=14)

    # Get user conversations
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.role == "user",
            Conversation.created_at >= cutoff,
        )
        .order_by(Conversation.created_at)
    )
    messages = result.scalars().all()

    if len(messages) < 5:
        return []

    # 1. Learn preferred greeting time
    greeting_hours = []
    for m in messages:
        if m.created_at and any(g in (m.content or "").lower() for g in ["morning", "subah", "good morning"]):
            greeting_hours.append(m.created_at.hour)

    if len(greeting_hours) >= 3:
        avg_hour = round(sum(greeting_hours) / len(greeting_hours))
        await _save_learning(db, user_id, "preferred_greeting_hour", str(avg_hour))
        learned.append(f"Learned: user usually greets at {avg_hour}:00")

    # 2. Learn response length preference
    user_msgs = [m for m in messages if m.role == "user"]
    avg_words = sum(len((m.content or "").split()) for m in user_msgs) / max(len(user_msgs), 1)
    if avg_words < 5:
        pref = "ultra_short"
    elif avg_words < 15:
        pref = "short"
    else:
        pref = "detailed"
    await _save_learning(db, user_id, "response_length_preference", pref)

    # 3. Learn frequently asked topics
    all_text = " ".join((m.content or "").lower() for m in messages)
    topic_counts = Counter()
    topic_map = {
        "gold": ["gold", "sona", "rate", "bhav"],
        "stocks": ["stock", "share", "nifty", "sensex"],
        "email": ["email", "mail", "inbox"],
        "reminder": ["remind", "yaad", "alarm"],
        "weather": ["weather", "mausam", "rain"],
        "health": ["health", "doctor", "medicine", "gym"],
        "business": ["client", "customer", "order", "payment"],
    }
    for topic, keywords in topic_map.items():
        count = sum(all_text.count(kw) for kw in keywords)
        if count >= 3:
            topic_counts[topic] = count

    if topic_counts:
        top_topics = [t for t, _ in topic_counts.most_common(3)]
        await _save_learning(db, user_id, "top_interests", ",".join(top_topics))
        learned.append(f"Learned: top interests = {', '.join(top_topics)}")

    # 4. Learn communication style (formal vs casual)
    formal_words = ["please", "kindly", "sir", "ma'am", "ji", "aap"]
    casual_words = ["yaar", "bhai", "bro", "dude", "tu", "tum"]
    formal_count = sum(all_text.count(w) for w in formal_words)
    casual_count = sum(all_text.count(w) for w in casual_words)
    style = "formal" if formal_count > casual_count else "casual"
    await _save_learning(db, user_id, "communication_style", style)

    # 5. Learn active hours
    active_hours = Counter()
    for m in messages:
        if m.created_at:
            active_hours[m.created_at.hour] += 1
    if active_hours:
        peak_hours = [h for h, _ in active_hours.most_common(3)]
        await _save_learning(db, user_id, "peak_active_hours", ",".join(str(h) for h in sorted(peak_hours)))
        learned.append(f"Learned: most active at {', '.join(str(h)+':00' for h in sorted(peak_hours))}")

    return learned


async def _save_learning(db: AsyncSession, user_id: str, key: str, value: str):
    """Save a learned behavior as internal memory (prefixed with _learned_)."""
    from sqlalchemy import delete as sa_delete

    mem_key = f"_learned_{key}"
    try:
        await db.execute(
            sa_delete(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.key == mem_key,
            )
        )
        db.add(UserMemory(user_id=user_id, key=mem_key, value=value))
        await db.commit()
    except Exception as e:
        logger.error(f"Save learning error: {e}")


async def get_learned_context(db: AsyncSession, user_id: str) -> str:
    """Get all learned behaviors as context for the system prompt."""
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key.startswith("_learned_"),
        )
    )
    learnings = result.scalars().all()
    if not learnings:
        return ""

    lines = []
    for l in learnings:
        clean_key = l.key.replace("_learned_", "").replace("_", " ").title()
        lines.append(f"- {clean_key}: {l.value}")

    return f"\nSAM'S LEARNINGS ABOUT THIS USER:\n" + "\n".join(lines)
