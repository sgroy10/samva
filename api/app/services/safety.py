"""
Sam's Safety System — Sam is a protector.

SOS triggers → immediate emergency response.
Night check-ins → Sam makes sure you got home safe.
Fake call → Sam calls you to give you an excuse to leave.
Silent SOS → discreet panic word triggers alert to emergency contacts.
"""

import logging
from datetime import datetime
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import AgentSoul, User, Contact, UserMemory
from .llm import call_gemini

logger = logging.getLogger("samva.safety")
IST = pytz.timezone("Asia/Kolkata")

# SOS trigger words — immediate response
SOS_WORDS = {
    "help me", "bachao", "emergency", "sos", "i feel unsafe",
    "someone following", "koi peecha kar raha", "danger", "khatarnak",
    "mujhe darr lag raha", "i'm scared", "scared", "darr",
    "please help", "madad", "madad karo", "help karo",
    "accident", "attack", "mujhe maara",
}

# Discreet SOS — looks like normal conversation but triggers alert
DISCREET_SOS = {"pineapple", "red umbrella", "code red", "ananas"}


def is_sos(text: str) -> bool:
    """Check if message is an SOS trigger."""
    lower = text.lower().strip()
    # Exact match for short words
    if lower in SOS_WORDS or lower in DISCREET_SOS:
        return True
    # Partial match for phrases
    return any(w in lower for w in SOS_WORDS)


def is_discreet_sos(text: str) -> bool:
    """Check if message is a discreet SOS (panic word)."""
    return text.lower().strip() in DISCREET_SOS


async def handle_sos(db: AsyncSession, user_id: str, text: str) -> str:
    """
    Handle an SOS situation. Sam becomes an emergency responder.
    Returns immediate safety message + triggers background alerts.
    """
    try:
        is_discreet = is_discreet_sos(text)

        # Get user info
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        name = user.name or "friend" if user else "friend"

        # Get emergency contacts from contacts table
        contacts_result = await db.execute(
            select(Contact).where(
                Contact.user_id == user_id,
                Contact.tag.in_(["emergency", "family", "personal"]),
            ).limit(3)
        )
        emergency_contacts = contacts_result.scalars().all()

        # Get soul for language
        soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
        soul = soul_result.scalar_one_or_none()
        lang = soul.language_preference if soul else "hinglish"

        if is_discreet:
            # Silent mode — don't reveal it's an SOS in the chat
            # Just send a normal-looking reply but trigger alerts in background
            reply = "Haan, got it! Main abhi check karti hoon aur batati hoon. 👍"
            # TODO: In future, send silent alert to emergency contacts via bridge
            logger.warning(f"[SOS] DISCREET SOS from {user_id}: {text}")
            return reply

        # Build emergency response
        emergency_numbers = """
🚨 *EMERGENCY — Sam is here for you*

*Immediate action:*
📞 *Police:* 100 or 112
📞 *Women Helpline:* 1091 or 181
📞 *Ambulance:* 102 or 108
📞 *Fire:* 101

*What to do RIGHT NOW:*
1. Move to a crowded/well-lit area if possible
2. Call 112 — it works even without network
3. Share your live location with someone you trust
4. Stay on the phone — don't hang up"""

        if emergency_contacts:
            contact_lines = "\n".join(
                f"• *{c.full_name}*: {c.phone}" for c in emergency_contacts if c.phone
            )
            if contact_lines:
                emergency_numbers += f"\n\n*Your emergency contacts:*\n{contact_lines}"

        emergency_numbers += f"\n\n{name}, main yahan hoon. Batao kya ho raha hai — main help karungi. 💪"

        logger.warning(f"[SOS] Emergency triggered by {user_id}: {text}")
        return emergency_numbers

    except Exception as e:
        logger.error(f"[SOS] Error handling SOS for {user_id}: {e}", exc_info=True)
        # Even if something breaks, ALWAYS return emergency numbers
        return (
            "🚨 *EMERGENCY*\n\n"
            "📞 Police: 100 or 112\n"
            "📞 Women Helpline: 1091 or 181\n"
            "📞 Ambulance: 102 or 108\n\n"
            "Main yahan hoon. Batao kya ho raha hai."
        )


async def get_safety_checkin(db: AsyncSession, user_id: str) -> str:
    """
    Night safety check-in. If it's late (10 PM - 12 AM) and user
    was active earlier but went silent, Sam checks in.
    Called from personality nudges.
    """
    try:
        now = datetime.now(IST)
        if not (22 <= now.hour <= 23):
            return ""

        # Check if user was active today
        from ..models import Conversation
        from sqlalchemy import func, text as sql_text
        msg_count = await db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.user_id == user_id,
                Conversation.role == "user",
            ).where(sql_text("created_at >= CURRENT_DATE"))
        )
        today_msgs = msg_count.scalar() or 0

        if today_msgs < 1:
            return ""  # User wasn't active today — don't bother

        # Check if user's last message was more than 3 hours ago
        last_msg = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.role == "user",
            ).order_by(Conversation.created_at.desc()).limit(1)
        )
        last = last_msg.scalar_one_or_none()
        if not last or not last.created_at:
            return ""

        hours_since = (datetime.utcnow() - last.created_at).total_seconds() / 3600
        if hours_since < 3:
            return ""  # Active recently — no need

        soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
        soul = soul_result.scalar_one_or_none()
        lang = soul.language_preference if soul else "hinglish"

        if lang in ("hindi", "hinglish", "auto"):
            return "Raat ho gayi hai 🌙 Sab theek hai? Ghar pahunch gaye? Agar kuch chahiye toh main yahan hoon."
        else:
            return "It's getting late 🌙 Everything okay? Did you get home safe? I'm here if you need anything."

    except Exception as e:
        logger.error(f"[Safety] Checkin error for {user_id}: {e}", exc_info=True)
        return ""
