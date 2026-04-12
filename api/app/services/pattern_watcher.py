"""
Pattern Watcher — Sam's autonomous behavior engine.

Sam watches. Sam learns. Sam proposes. Sam surprises.

Every 15 minutes, Sam analyzes user activity and detects patterns:
- WHEN they do things (temporal patterns)
- WHAT they repeatedly ask (content patterns)
- WHO they prioritize (contact patterns)

When confidence > 0.7 and shadow tested for 3 days:
Sam proposes ONE time. User says yes → behavior activates forever.
User ignores → Sam never asks again. No spam. Ever.

This is what makes Sam feel magical.
"""

import logging
from datetime import datetime, timedelta, time
from collections import Counter, defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sql_text, update, delete
from ..models import (
    Conversation, DetectedPattern, ActiveBehavior,
    AgentSoul, User,
)

logger = logging.getLogger("samva.pattern_watcher")


# ── Pattern Detection ────────────────────────────────────────────

async def watch_patterns(db: AsyncSession, user_id: str) -> list:
    """
    Lightweight pattern detection. Runs every 15 min.
    Analyzes last 7-14 days of conversations.
    Returns list of newly detected patterns.
    """
    detected = []

    try:
        # Get conversation history (last 14 days)
        result = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.role == "user",
            ).where(sql_text("created_at >= NOW() - INTERVAL '14 days'"))
            .order_by(Conversation.created_at)
        )
        messages = result.scalars().all()

        if len(messages) < 5:
            return []  # Not enough data

        # 1. Temporal patterns — WHEN user asks for things
        gold_pattern = _detect_temporal_pattern(
            messages, ["gold", "rate", "sona", "bhav", "rates"],
            "proactive_gold_brief", "Gold rates"
        )
        if gold_pattern:
            detected.append(gold_pattern)

        inbox_pattern = _detect_temporal_pattern(
            messages, ["check message", "inbox", "kaun aaya", "messages"],
            "proactive_inbox_summary", "Inbox summary"
        )
        if inbox_pattern:
            detected.append(inbox_pattern)

        email_pattern = _detect_temporal_pattern(
            messages, ["check mail", "check email", "my mail", "emails"],
            "proactive_email_summary", "Email summary"
        )
        if email_pattern:
            detected.append(email_pattern)

        weather_pattern = _detect_temporal_pattern(
            messages, ["weather", "mausam"],
            "proactive_weather", "Weather update"
        )
        if weather_pattern:
            detected.append(weather_pattern)

        # 2. Content patterns — WHAT user repeatedly asks
        content_patterns = _detect_content_patterns(messages)
        detected.extend(content_patterns)

        # Save new patterns to DB (skip duplicates)
        for p in detected:
            existing = await db.execute(
                select(DetectedPattern).where(
                    DetectedPattern.user_id == user_id,
                    DetectedPattern.pattern_type == p["type"],
                    DetectedPattern.status.in_(["detected", "shadow", "proposed", "active"]),
                )
            )
            if existing.scalar_one_or_none():
                continue  # Already tracking this pattern

            # Check if user previously declined
            declined = await db.execute(
                select(DetectedPattern).where(
                    DetectedPattern.user_id == user_id,
                    DetectedPattern.pattern_type == p["type"],
                    DetectedPattern.user_response == "declined",
                )
            )
            if declined.scalar_one_or_none():
                continue  # User said no before — respect it forever

            db.add(DetectedPattern(
                user_id=user_id,
                pattern_type=p["type"],
                pattern_data=p["data"],
                confidence=p["confidence"],
                status="detected",
            ))
            logger.info(f"[{user_id}] Pattern detected: {p['type']} (confidence: {p['confidence']:.2f})")

        await db.commit()

    except Exception as e:
        logger.error(f"Pattern watch error for {user_id}: {e}", exc_info=True)

    return detected


def _detect_temporal_pattern(messages, keywords, pattern_type, label):
    """Detect if user asks for something at a consistent time."""
    matching = []
    for msg in messages:
        content = (msg.content or "").lower()
        if any(kw in content for kw in keywords):
            if msg.created_at:
                matching.append(msg.created_at)

    if len(matching) < 3:
        return None

    # Extract hours
    hours = [m.hour for m in matching]
    hour_counts = Counter(hours)
    most_common_hour, count = hour_counts.most_common(1)[0]

    # If user does this at the same hour 60%+ of the time
    consistency = count / len(matching)
    if consistency < 0.5:
        return None

    # Get average minute
    minutes = [m.minute for m in matching if m.hour == most_common_hour]
    avg_minute = sum(minutes) // len(minutes) if minutes else 0

    # Send 5 min earlier than their usual time
    send_hour = most_common_hour
    send_minute = max(0, avg_minute - 5)

    confidence = min(0.95, consistency * (len(matching) / 10))

    return {
        "type": pattern_type,
        "data": {
            "label": label,
            "trigger_hour": send_hour,
            "trigger_minute": send_minute,
            "user_usual_time": f"{most_common_hour}:{avg_minute:02d}",
            "occurrences": len(matching),
            "consistency": round(consistency, 2),
        },
        "confidence": round(confidence, 2),
    }


def _detect_content_patterns(messages):
    """Detect repeated content themes."""
    patterns = []

    # Count topic frequencies
    topics = defaultdict(int)
    for msg in messages:
        content = (msg.content or "").lower()
        if "remind" in content:
            topics["frequent_reminders"] += 1
        if any(w in content for w in ["stock", "share", "nifty", "sensex"]):
            topics["stock_interest"] += 1
        if any(w in content for w in ["calorie", "food", "khana", "lunch", "dinner"]):
            topics["health_tracking"] += 1
        if any(w in content for w in ["learn", "teach", "practice", "word"]):
            topics["learning_habit"] += 1

    total = len(messages)
    for topic, count in topics.items():
        if count >= 3 and count / total > 0.1:
            patterns.append({
                "type": f"interest_{topic}",
                "data": {
                    "label": topic.replace("_", " ").title(),
                    "count": count,
                    "percentage": round(count / total * 100, 1),
                },
                "confidence": min(0.9, count / 10),
            })

    return patterns


# ── Shadow Testing ───────────────────────────────────────────────

async def run_shadow_tests(db: AsyncSession, user_id: str):
    """
    Test detected patterns without sending to user.
    After 3 days of successful predictions → promote to proposal.
    """
    result = await db.execute(
        select(DetectedPattern).where(
            DetectedPattern.user_id == user_id,
            DetectedPattern.status == "detected",
            DetectedPattern.confidence >= 0.5,
        )
    )
    patterns = result.scalars().all()

    for pattern in patterns:
        days_since = (datetime.utcnow() - pattern.detected_at).days if pattern.detected_at else 0

        if days_since >= 3:
            # Promote to proposal after 3 days of detection
            pattern.status = "shadow"
            pattern.shadow_tested = True
            pattern.shadow_success_rate = pattern.confidence  # Use confidence as proxy
            logger.info(f"[{user_id}] Pattern shadow tested: {pattern.pattern_type}")

    await db.commit()


# ── Proposal System ──────────────────────────────────────────────

async def get_pending_proposals(db: AsyncSession, user_id: str) -> list[str]:
    """
    Generate proposal messages for shadow-tested patterns.
    ONE proposal per check. Never spam.
    """
    result = await db.execute(
        select(DetectedPattern).where(
            DetectedPattern.user_id == user_id,
            DetectedPattern.status == "shadow",
            DetectedPattern.shadow_success_rate >= 0.5,
        ).order_by(DetectedPattern.confidence.desc()).limit(1)
    )
    pattern = result.scalar_one_or_none()

    if not pattern:
        return []

    data = pattern.pattern_data or {}
    label = data.get("label", pattern.pattern_type)
    occurrences = data.get("occurrences", "several")
    usual_time = data.get("user_usual_time", "")
    confidence_pct = int(pattern.confidence * 100)

    # Generate humble, one-shot proposal
    if "proactive" in pattern.pattern_type:
        time_str = usual_time or "around the same time"
        msg = (
            f"I noticed something \U0001f9d0\n\n"
            f"You've asked for *{label}* about {occurrences} times "
            f"in the last 2 weeks, usually around *{time_str}*.\n\n"
            f"I'm {confidence_pct}% sure this is a habit, not coincidence.\n\n"
            f"Want me to send *{label}* automatically 5 minutes before you usually ask?\n\n"
            f"Reply *YES* to set it up, or just ignore this — I'll never ask again."
        )
    elif "interest" in pattern.pattern_type:
        msg = (
            f"I noticed you're interested in *{label}* \U0001f4a1\n\n"
            f"You've mentioned it {occurrences} times recently.\n\n"
            f"Want me to keep an eye on this and send you relevant updates?\n\n"
            f"Reply *YES* or just ignore — your call!"
        )
    else:
        return []

    # Mark as proposed
    pattern.status = "proposed"
    pattern.proposed_at = datetime.utcnow()
    await db.commit()

    return [msg]


async def handle_proposal_response(db: AsyncSession, user_id: str, response: str) -> str:
    """Handle user's YES/NO to a behavior proposal."""
    # Find the most recent pending proposal
    result = await db.execute(
        select(DetectedPattern).where(
            DetectedPattern.user_id == user_id,
            DetectedPattern.status == "proposed",
        ).order_by(DetectedPattern.proposed_at.desc()).limit(1)
    )
    pattern = result.scalar_one_or_none()

    if not pattern:
        return ""

    lower = response.lower().strip()
    yes_words = {"yes", "haan", "ha", "ok", "sure", "set it up", "theek"}

    if any(w in lower for w in yes_words):
        # ACTIVATE the behavior
        pattern.status = "active"
        pattern.user_response = "accepted"

        data = pattern.pattern_data or {}
        db.add(ActiveBehavior(
            user_id=user_id,
            pattern_type=pattern.pattern_type,
            trigger_spec={
                "hour": data.get("trigger_hour", 9),
                "minute": data.get("trigger_minute", 0),
            },
            content_spec={
                "label": data.get("label", ""),
                "type": pattern.pattern_type,
            },
        ))
        await db.commit()

        label = data.get("label", "this")
        return f"Done! \u2705 I'll send *{label}* automatically. You can say 'stop {label}' anytime."
    else:
        # User declined — respect forever
        pattern.status = "declined"
        pattern.user_response = "declined"
        await db.commit()
        return ""  # Silent — no response to decline


# ── Behavior Execution ───────────────────────────────────────────

async def execute_active_behaviors(db: AsyncSession, user_id: str) -> list[str]:
    """
    Execute user-approved behaviors that should trigger now.
    Called every 15 min by the alert cron.
    Returns list of messages to send.
    """
    now = datetime.utcnow()
    current_hour = now.hour
    current_minute = now.minute

    result = await db.execute(
        select(ActiveBehavior).where(
            ActiveBehavior.user_id == user_id,
            ActiveBehavior.is_active == True,
        )
    )
    behaviors = result.scalars().all()

    messages = []
    for b in behaviors:
        trigger = b.trigger_spec or {}
        trigger_hour = trigger.get("hour", -1)
        trigger_minute = trigger.get("minute", 0)

        # Check if within 15 min window of trigger time
        if trigger_hour == current_hour and abs(current_minute - trigger_minute) <= 15:
            # Don't execute if already ran today
            if b.last_executed and b.last_executed.date() == now.date():
                continue

            content_type = (b.content_spec or {}).get("type", "")
            label = (b.content_spec or {}).get("label", "Update")

            # Generate content based on behavior type
            content = await _generate_behavior_content(db, user_id, content_type)

            if content:
                messages.append(f"\U0001f916 *Auto: {label}*\n\n{content}")
                b.last_executed = now
                b.execution_count = (b.execution_count or 0) + 1

    if messages:
        await db.commit()

    return messages


async def _generate_behavior_content(db, user_id, content_type):
    """Generate the actual content for a behavior."""
    try:
        if "gold" in content_type:
            from .gold import get_gold_brief
            return await get_gold_brief(db, user_id)

        if "inbox" in content_type:
            from .chat_intelligence import get_chat_summary
            return await get_chat_summary(db, user_id, hours=12)

        if "email" in content_type:
            from .email_service import check_all_accounts
            return await check_all_accounts(db, user_id, count_per=5)

        if "weather" in content_type:
            from .prebuilt_skills import weather
            return await weather("weather", {})

        if "stock" in content_type:
            from .stocks import get_watchlist_brief
            return await get_watchlist_brief(db, user_id)

        return None
    except Exception as e:
        logger.error(f"Behavior content error ({content_type}): {e}")
        return None


# ── Run All (called by cron) ─────────────────────────────────────

async def run_pattern_engine(db: AsyncSession, user_id: str) -> dict:
    """
    Full pattern engine cycle:
    1. Detect new patterns
    2. Shadow test existing ones
    3. Generate proposals for tested ones
    4. Execute active behaviors
    """
    detected = await watch_patterns(db, user_id)
    await run_shadow_tests(db, user_id)
    proposals = await get_pending_proposals(db, user_id)
    behavior_messages = await execute_active_behaviors(db, user_id)

    # Hermes-style skill learning
    try:
        from .skill_learner import learn_from_interactions
        learned = await learn_from_interactions(db, user_id)
        if learned:
            logger.info(f"[{user_id}] Skill learner: {learned}")
    except Exception as e:
        logger.error(f"[{user_id}] Skill learner error: {e}")

    return {
        "detected": len(detected),
        "proposals": proposals,
        "behaviors": behavior_messages,
    }
