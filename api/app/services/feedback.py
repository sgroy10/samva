"""
Feedback Engine — Sam learns what you like.

After every proactive message (gold brief, FutureEcho, nudge, pattern proposal),
track user's reaction:
- POSITIVE: user responds with thanks, emoji, follow-up question
- NEGATIVE: user says "stop", "band karo", "don't send"
- IGNORED: no response within 30 minutes

Sam adjusts frequency: more of what works, less of what doesn't.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ..models import FeedbackSignal, Conversation

logger = logging.getLogger("samva.feedback")

# Positive signals
POSITIVE_WORDS = [
    "thanks", "thank", "shukriya", "dhanyavaad", "nice", "great", "awesome",
    "mast", "badhiya", "achha", "👍", "🙏", "❤️", "💪", "👏",
    "haan", "yes", "ok", "perfect", "love it", "pasand aaya",
]

# Negative signals
NEGATIVE_WORDS = [
    "stop", "band karo", "mat bhejo", "don't send", "not needed",
    "nahi chahiye", "annoying", "spam", "hatao", "unsubscribe",
    "irritating", "pareshan",
]


async def log_feedback(db: AsyncSession, user_id: str, feature: str, signal: str, context: str = ""):
    """Log a feedback signal."""
    fb = FeedbackSignal(
        user_id=user_id,
        feature=feature,
        signal=signal,
        context=context[:500] if context else "",
    )
    db.add(fb)
    await db.commit()
    logger.info(f"Feedback: {user_id} → {feature} = {signal}")


async def detect_feedback_from_reply(db: AsyncSession, user_id: str, reply_text: str, last_feature: str = ""):
    """Analyze user's reply to detect positive/negative feedback."""
    text_lower = reply_text.lower().strip()

    if any(w in text_lower for w in NEGATIVE_WORDS):
        await log_feedback(db, user_id, last_feature or "proactive", "negative", reply_text)
        return "negative"
    elif any(w in text_lower for w in POSITIVE_WORDS):
        await log_feedback(db, user_id, last_feature or "proactive", "positive", reply_text)
        return "positive"
    return None


async def should_send_feature(db: AsyncSession, user_id: str, feature: str) -> bool:
    """Check if Sam should send this feature based on past feedback.
    If user gave 3+ negative signals → stop sending.
    If user gave 5+ ignores in a row → reduce frequency."""
    result = await db.execute(
        select(FeedbackSignal)
        .where(
            FeedbackSignal.user_id == user_id,
            FeedbackSignal.feature == feature,
        )
        .order_by(FeedbackSignal.created_at.desc())
        .limit(10)
    )
    signals = result.scalars().all()

    if not signals:
        return True  # No history, send it

    # Count recent negatives
    negatives = sum(1 for s in signals if s.signal == "negative")
    if negatives >= 3:
        logger.info(f"Suppressing {feature} for {user_id}: {negatives} negative signals")
        return False

    # Count consecutive ignores
    consecutive_ignores = 0
    for s in signals:
        if s.signal == "ignored":
            consecutive_ignores += 1
        else:
            break
    if consecutive_ignores >= 5:
        logger.info(f"Reducing {feature} for {user_id}: {consecutive_ignores} consecutive ignores")
        return False

    return True


async def get_feature_stats(db: AsyncSession, user_id: str) -> dict:
    """Get feedback stats for all features — used by soul evolution."""
    result = await db.execute(
        select(
            FeedbackSignal.feature,
            FeedbackSignal.signal,
            func.count(FeedbackSignal.id),
        )
        .where(FeedbackSignal.user_id == user_id)
        .group_by(FeedbackSignal.feature, FeedbackSignal.signal)
    )
    stats = {}
    for feature, signal, count in result.all():
        if feature not in stats:
            stats[feature] = {"positive": 0, "negative": 0, "ignored": 0}
        stats[feature][signal] = count
    return stats
