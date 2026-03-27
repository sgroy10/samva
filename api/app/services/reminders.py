import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import Reminder, User
from .llm import call_gemini_json

logger = logging.getLogger("samva.reminders")


async def create_reminder(db: AsyncSession, user_id: str, text: str) -> str:
    """Parse natural language and create a reminder. Detects urgency."""
    now = datetime.now()

    extracted = await call_gemini_json(
        f"""Parse this reminder request. Current date/time: {now.strftime('%Y-%m-%d %H:%M')}.
Return JSON:
{{
    "text": "what to remind about",
    "date": "YYYY-MM-DD",
    "time": "HH:MM (24h format, default 09:00)",
    "repeat": "none|daily|weekly|monthly|yearly",
    "type": "birthday|anniversary|payment|meeting|custom",
    "is_urgent": true/false
}}
Mark is_urgent=true if: words like "urgent", "zaruri", "important", "critical", "ASAP",
"jaldi", "turant", "emergency" appear. Or if it's a payment/meeting due today.
Examples:
- "Remind me to call Rahul tomorrow" -> repeat: none, is_urgent: false
- "URGENT: call bank about loan before 5pm" -> is_urgent: true
- "Mummy ka birthday 15 March" -> repeat: yearly, type: birthday""",
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
    is_urgent = extracted.get("is_urgent", False)

    try:
        if date_str:
            remind_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        else:
            remind_at = now + timedelta(hours=1)
    except (ValueError, TypeError):
        remind_at = now + timedelta(hours=1)

    if remind_at < now and repeat == "yearly":
        remind_at = remind_at.replace(year=now.year + 1)
    elif remind_at < now and repeat == "none":
        remind_at = remind_at + timedelta(days=1)

    reminder = Reminder(
        user_id=user_id,
        text=reminder_text,
        remind_at=remind_at,
        repeat_type=repeat,
        type=rem_type,
        is_urgent=is_urgent,
    )
    db.add(reminder)
    await db.commit()

    date_display = remind_at.strftime("%d %b %Y, %I:%M %p")
    repeat_text = f" (repeats {repeat})" if repeat != "none" else ""
    urgent_text = "\n\U0001f6a8 *URGENT* — agar 30 min mein respond nahi kiya toh Sam call karegi!" if is_urgent else ""

    emoji = {
        "birthday": "\U0001f382", "anniversary": "\U0001f49d",
        "payment": "\U0001f4b0", "meeting": "\U0001f4bc",
    }.get(rem_type, "\u23f0")

    return f"{emoji} Reminder set: {reminder_text}\n\U0001f4c5 {date_display}{repeat_text}{urgent_text}"


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
            "birthday": "\U0001f382", "anniversary": "\U0001f49d",
            "payment": "\U0001f4b0", "meeting": "\U0001f4bc",
        }.get(rem.type, "\u23f0")

        urgent_tag = " \U0001f6a8 *URGENT*" if rem.is_urgent else ""
        alerts.append(f"{emoji} *Reminder:*{urgent_tag} {rem.text}")

        rem.sent = True

        if rem.repeat_type != "none":
            next_at = _next_occurrence(rem.remind_at, rem.repeat_type)
            db.add(Reminder(
                user_id=user_id, text=rem.text, remind_at=next_at,
                repeat_type=rem.repeat_type, type=rem.type, is_urgent=rem.is_urgent,
            ))

    if reminders:
        await db.commit()

    return alerts


async def check_urgent_escalations(db: AsyncSession) -> list[dict]:
    """
    Check for urgent reminders sent 30+ minutes ago with no user response.
    Returns list of {user_id, phone, message} for outbound calls.
    Called by cron every 15 minutes.
    """
    now = datetime.now()
    thirty_min_ago = now - timedelta(minutes=30)

    # Find urgent reminders that were sent but user hasn't responded
    result = await db.execute(
        select(Reminder).where(
            Reminder.is_urgent == True,
            Reminder.sent == True,
            Reminder.call_attempted == False,
            Reminder.remind_at <= thirty_min_ago,
        )
    )
    urgent_reminders = result.scalars().all()

    calls = []
    for rem in urgent_reminders:
        # Get user phone
        user_result = await db.execute(select(User).where(User.id == rem.user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.phone:
            continue

        # Check if user responded after reminder (any conversation in last 30 min)
        from ..models import Conversation
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.user_id == rem.user_id,
                Conversation.role == "user",
                Conversation.created_at >= rem.remind_at,
            ).limit(1)
        )
        if conv_result.scalar_one_or_none():
            # User responded — no need to call
            rem.call_attempted = True
            continue

        # No response — escalate to phone call
        phone = user.phone if user.phone.startswith("+") else f"+{user.phone}"
        calls.append({
            "user_id": rem.user_id,
            "phone": phone,
            "message": f"Urgent reminder from Sam: {rem.text}. Aapne 30 minute se respond nahi kiya. Please check your WhatsApp.",
        })
        rem.call_attempted = True

    await db.commit()
    return calls


def _next_occurrence(current: datetime, repeat_type: str) -> datetime:
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
            return current.replace(year=year, month=month, day=28)
    elif repeat_type == "yearly":
        try:
            return current.replace(year=current.year + 1)
        except ValueError:
            return current.replace(year=current.year + 1, day=28)
    return current + timedelta(days=1)
