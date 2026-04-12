"""
Goal Tracker — Sam helps you achieve your goals.

"Main is month 50K save karna chahta hoon"
→ Sam creates goal, tracks daily, reminds progress, celebrates milestones.

"Lose 5 kg in 2 months"
→ Sam checks in weekly, asks about exercise, diet, celebrates progress.

"Read 2 books this month"
→ Sam asks which book, reminds to read, celebrates completion.
"""

import logging
from datetime import datetime, timedelta
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sa_delete
from ..models import UserMemory

logger = logging.getLogger("samva.goals")
IST = pytz.timezone("Asia/Kolkata")

# Goal triggers
GOAL_TRIGGERS = [
    "goal", "target", "achieve", "want to save", "save karna",
    "lose weight", "weight loss", "gain", "earn", "kamana",
    "complete", "finish", "read", "learn", "sikhna",
    "is month", "this month", "this week", "is hafte",
]


def detect_goal(text: str) -> bool:
    """Detect if user is setting a goal."""
    text_lower = text.lower()
    return any(t in text_lower for t in GOAL_TRIGGERS)


async def create_goal(db: AsyncSession, user_id: str, text: str) -> str:
    """Extract and save a goal from user's message."""
    from .llm import call_gemini_json

    data = await call_gemini_json(
        """Extract a goal from this message. Return JSON:
{
    "goal": "clear description of the goal",
    "metric": "what to measure (amount, kg, books, etc.)",
    "target_value": "target number",
    "current_value": "starting value if mentioned, else 0",
    "deadline": "deadline if mentioned, else '30 days'",
    "check_frequency": "daily or weekly"
}""",
        text, user_id=user_id, max_tokens=200,
    )

    if not data or "error" in data:
        return ""

    goal_key = f"_goal_{datetime.now(IST).strftime('%Y%m%d_%H%M')}"

    # Save goal as structured memory
    import json
    db.add(UserMemory(
        user_id=user_id,
        key=goal_key,
        value=json.dumps(data),
    ))

    # Also save as active goal pointer
    await db.execute(
        sa_delete(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_active_goal",
        )
    )
    db.add(UserMemory(
        user_id=user_id,
        key="_active_goal",
        value=json.dumps({**data, "goal_key": goal_key, "created": datetime.now(IST).isoformat()}),
    ))
    await db.commit()

    goal = data.get("goal", "")
    target = data.get("target_value", "")
    deadline = data.get("deadline", "30 days")
    freq = data.get("check_frequency", "daily")

    return (
        f"🎯 *Goal Set!*\n\n"
        f"Goal: {goal}\n"
        f"Target: {target}\n"
        f"Deadline: {deadline}\n"
        f"Check-in: {freq}\n\n"
        f"Main track karungi! {freq.title()} update puchungi. Let's do this! 💪"
    )


async def check_goal_progress(db: AsyncSession, user_id: str) -> str:
    """Check if user has an active goal and generate a check-in nudge."""
    import json

    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_active_goal",
        )
    )
    goal_mem = result.scalar_one_or_none()
    if not goal_mem:
        return ""

    try:
        goal_data = json.loads(goal_mem.value)
    except Exception:
        return ""

    goal = goal_data.get("goal", "")
    target = goal_data.get("target_value", "")
    created = goal_data.get("created", "")

    if not goal:
        return ""

    # Check last check-in
    last_checkin_result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_goal_last_checkin",
        )
    )
    last_checkin = last_checkin_result.scalar_one_or_none()

    if last_checkin:
        try:
            last_date = datetime.fromisoformat(last_checkin.value)
            freq = goal_data.get("check_frequency", "daily")
            if freq == "daily" and (datetime.now(IST) - last_date).days < 1:
                return ""  # Already checked in today
            if freq == "weekly" and (datetime.now(IST) - last_date).days < 7:
                return ""  # Already checked in this week
        except Exception:
            pass

    # Update last check-in time
    await db.execute(
        sa_delete(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_goal_last_checkin",
        )
    )
    db.add(UserMemory(
        user_id=user_id,
        key="_goal_last_checkin",
        value=datetime.now(IST).isoformat(),
    ))
    await db.commit()

    return (
        f"🎯 *Goal Check-in:*\n"
        f"Goal: {goal}\n"
        f"Target: {target}\n\n"
        f"Kaise chal raha hai? Update do — main track kar rahi hoon! 💪"
    )


async def update_goal_progress(db: AsyncSession, user_id: str, text: str) -> str:
    """Update goal progress from user's message."""
    import json
    from .llm import call_gemini_json

    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_active_goal",
        )
    )
    goal_mem = result.scalar_one_or_none()
    if not goal_mem:
        return ""

    try:
        goal_data = json.loads(goal_mem.value)
    except Exception:
        return ""

    # Extract progress from message
    progress = await call_gemini_json(
        f"""The user has a goal: {goal_data.get('goal', '')}, target: {goal_data.get('target_value', '')}.
Extract progress from their message. Return JSON:
{{
    "current_value": "current progress value",
    "percentage": "estimated % complete",
    "on_track": true/false,
    "encouragement": "one line of encouragement in Hinglish"
}}""",
        text, user_id=user_id, max_tokens=150,
    )

    if not progress or "error" in progress:
        return ""

    pct = progress.get("percentage", "?")
    on_track = progress.get("on_track", True)
    encourage = progress.get("encouragement", "Keep going! 💪")

    # Update goal data
    goal_data["current_value"] = progress.get("current_value", goal_data.get("current_value", "0"))
    goal_data["last_update"] = datetime.now(IST).isoformat()

    await db.execute(
        sa_delete(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_active_goal",
        )
    )
    db.add(UserMemory(
        user_id=user_id,
        key="_active_goal",
        value=json.dumps(goal_data),
    ))
    await db.commit()

    status = "🟢 On track!" if on_track else "🟡 Push harder!"
    return (
        f"📊 *Goal Progress:*\n"
        f"{goal_data.get('goal', '')}\n"
        f"Progress: {pct}% {status}\n\n"
        f"{encourage}"
    )
