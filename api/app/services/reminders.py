import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import Reminder
from .llm import call_gemini_json

logger = logging.getLogger("samva.reminders")


async def create_reminder(db: AsyncSession, user_id: str, text: str) -> str:
    """Parse natural language and create a reminder."""
    now = datetime.now()

    extracted = await call_gemini_json(
        f"""Parse this reminder request. Current date/time: {now.strftime('%Y-%m-%d %H:%M')}.
Return JSON:
{{
    "text": "what to remind about",
    "date": "YYYY-MM-DD",
    "time": "HH:MM (24h format, default 09:00)",
    "repeat": "none|daily|weekly|monthly|yearly",
    "type": "birthday|anniversary|payment|meeting|custom"
}}
Examples:
- "Remind me to call Rahul tomorrow" -> date: tomorrow, time: 09:00, repeat: none
- "Mummy ka birthday 15 March" -> date: 2027-03-15, time: 09:00, repeat: yearly, type: birthday
- "Rent due every month 1st" -> date: next 1st, repeat: monthly, type: payment""",
        text,
        user_id=user_id,
    )

    if "error" in extracted:
        return "I didn't quite understand. Could you say it like: 'Remind me to [task] on [date/time]'?"

    reminder_text = extracted.get("text", text)
    date_str = extracted.get("date", "")
    time_str = extracted.get("time", "09:00")
    repeat = extracted.get("repeat", "none")
    rem_type = extracted.get("type", "custom")

    # Parse date
    try:
        if date_str:
            remind_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        else:
            remind_at = now + timedelta(hours=1)
    except (ValueError, TypeError):
        remind_at = now + timedelta(hours=1)

    # If remind_at is in the past and it's a yearly event, move to next year
    if remind_at < now and repeat == "yearly":
        remind_at = remind_at.replace(year=now.year + 1)
    elif remind_at < now and repeat == "none":
        # If past, set for tomorrow same time
        remind_at = remind_at + timedelta(days=1)

    reminder = Reminder(
        user_id=user_id,
        text=reminder_text,
        remind_at=remind_at,
        repeat_type=repeat,
        type=rem_type,
    )
    db.add(reminder)
    await db.commit()

    # Format confirmation
    date_display = remind_at.strftime("%d %b %Y, %I:%M %p")
    repeat_text = ""
    if repeat != "none":
        repeat_text = f" (repeats {repeat})"

    emoji = {
        "birthday": "\ud83c\udf82",
        "anniversary": "\ud83d\udc9d",
        "payment": "\ud83d\udcb0",
        "meeting": "\ud83d\udcbc",
    }.get(rem_type, "\u23f0")

    return f"{emoji} Reminder set: {reminder_text}\n\ud83d\udcc5 {date_display}{repeat_text}"


async def check_due_reminders(db: AsyncSession, user_id: str) -> list[str]:
    """Check for reminders that are due now."""
    now = datetime.now()
    window_start = now - timedelta(minutes=15)

    result = await db.execute(
        select(Reminder).where(
            Reminder.user_id == user_id,
            Reminder.sent == False,
            Reminder.remind_at <= now,
            Reminder.remind_at >= window_start,
        )
    )
    reminders = result.scalars().all()

    alerts = []
    for rem in reminders:
        emoji = {
            "birthday": "\ud83c\udf82",
            "anniversary": "\ud83d\udc9d",
            "payment": "\ud83d\udcb0",
            "meeting": "\ud83d\udcbc",
        }.get(rem.type, "\u23f0")

        alerts.append(f"{emoji} *Reminder:* {rem.text}")

        # Mark as sent
        rem.sent = True

        # Handle recurring
        if rem.repeat_type != "none":
            next_at = _next_occurrence(rem.remind_at, rem.repeat_type)
            new_reminder = Reminder(
                user_id=user_id,
                text=rem.text,
                remind_at=next_at,
                repeat_type=rem.repeat_type,
                type=rem.type,
            )
            db.add(new_reminder)

    if reminders:
        await db.commit()

    return alerts


def _next_occurrence(current: datetime, repeat_type: str) -> datetime:
    """Calculate next occurrence for recurring reminders."""
    if repeat_type == "daily":
        return current + timedelta(days=1)
    elif repeat_type == "weekly":
        return current + timedelta(weeks=1)
    elif repeat_type == "monthly":
        month = current.month + 1
        year = current.year
        if month > 12:
            month = 1
            year += 1
        try:
            return current.replace(year=year, month=month)
        except ValueError:
            # Handle months with fewer days
            return current.replace(year=year, month=month, day=28)
    elif repeat_type == "yearly":
        try:
            return current.replace(year=current.year + 1)
        except ValueError:
            return current.replace(year=current.year + 1, day=28)
    return current + timedelta(days=1)
