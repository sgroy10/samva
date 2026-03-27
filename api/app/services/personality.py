"""
Sam's Personality — the soul that makes Sam a FRIEND, not a tool.

Sam is warm, caring, fun, proactive. Sam asks about lunch.
Sam sends motivational quotes. Sam notices patterns.
Sam adapts to who the user is — fun with a young accountant,
serious with a scientist, motherly with a student.

Proactive nudges: lunch, evening, health, mood, festivals.
"""

import logging
import random
from datetime import datetime
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import AgentSoul, UserMemory

logger = logging.getLogger("samva.personality")
IST = pytz.timezone("Asia/Kolkata")

# Anti-spam: track what's been sent today per user
_nudge_sent = {}  # (user_id, date, type) -> True


def _already_sent(user_id: str, nudge_type: str) -> bool:
    today = datetime.now(IST).strftime("%Y-%m-%d")
    key = (user_id, today, nudge_type)
    if key in _nudge_sent:
        return True
    _nudge_sent[key] = True
    # Clean old entries
    old = [k for k in _nudge_sent if k[1] != today]
    for k in old:
        del _nudge_sent[k]
    return False


async def get_proactive_nudges(db: AsyncSession, user_id: str) -> list[str]:
    """
    Check what proactive messages Sam should send right now.
    Called every 15 minutes by the alert scheduler.
    Returns list of messages to send.
    """
    now = datetime.now(IST)
    hour = now.hour
    minute = now.minute
    weekday = now.weekday()  # 0=Monday

    # Get user context
    soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
    soul = soul_result.scalar_one_or_none()
    if not soul or not soul.onboarding_complete:
        return []

    lang = soul.language_preference or "auto"
    is_hindi = lang in ("hindi", "hinglish", "auto")

    nudges = []

    # ── Lunch Check (12:30-1:30 PM) ─────────────────────────
    if 12 <= hour <= 13 and 30 <= minute <= 59 and not _already_sent(user_id, "lunch"):
        if random.random() < 0.7:  # 70% chance — not every single day
            if is_hindi:
                msgs = [
                    "Lunch time! \U0001f37d Kya kha rahe ho? Photo bhejo — main calories gin doongi!",
                    "Boss, lunch kar liya? Photo bhejo meal ki — main track kar rahi hoon \U0001f4aa",
                    "Dopahar ho gayi! Kuch khaya? Healthy kha rahe ho na? \U0001f60a",
                    "Lunch break! \U0001f37d Aaj kya hai menu? Photo bhejo!",
                ]
            else:
                msgs = [
                    "Lunch time! \U0001f37d What are you having? Send a photo — I'll count calories!",
                    "Time for a break! What's for lunch? \U0001f60a",
                    "Don't skip lunch! Send me a photo of what you're eating \U0001f4aa",
                ]
            nudges.append(random.choice(msgs))

    # ── Evening Wrap-up (6:00-7:00 PM) ──────────────────────
    if 18 <= hour <= 19 and not _already_sent(user_id, "evening"):
        if random.random() < 0.5:
            if is_hindi:
                msgs = [
                    "Shaam ho gayi! \U0001f307 Aaj ka din kaisa raha? Koi update dena hai mujhe?",
                    "Day wrap-up time! \U0001f4cb Aaj kya kya hua? Main note kar leti hoon.",
                    "Good evening! \u2615 Relax karo — agar koi pending kaam hai toh batao, main remind kar dungi.",
                ]
            else:
                msgs = [
                    "Evening wrap-up! \U0001f307 How was your day? Anything I should note down?",
                    "Day's ending — any pending tasks? I'll set reminders for tomorrow.",
                ]
            nudges.append(random.choice(msgs))

    # ── Morning Motivation (8:00-8:30 AM, not on brief days) ─
    if 8 <= hour <= 8 and minute <= 30 and not _already_sent(user_id, "morning_vibe"):
        if random.random() < 0.4:
            quotes = [
                "New day, new opportunities! Aaj kya plan hai? \U0001f680",
                "Subah ka waqt sabse productive hota hai — let's make today count! \U0001f4aa",
                "Good morning! Remember — small steps daily beat big leaps monthly \U0001f31f",
                "Aaj ka goal kya hai? Batao — main track karungi!",
                "Rise and shine! Market mein kya naya hai aaj? \U0001f4c8",
            ]
            nudges.append(random.choice(quotes))

    # ── Water Reminder (3:00-3:30 PM) ────────────────────────
    if 15 <= hour <= 15 and minute <= 30 and not _already_sent(user_id, "water"):
        if random.random() < 0.3:
            nudges.append("Paani piya? \U0001f4a7 Stay hydrated — 8 glasses a day!")

    # ── Weekend Check-in (Saturday 10 AM) ────────────────────
    if weekday == 5 and 10 <= hour <= 11 and not _already_sent(user_id, "weekend"):
        if random.random() < 0.5:
            if is_hindi:
                nudges.append("Weekend hai! \U0001f389 Aaj kya plan hai? Relax karo ya kuch naya seekhna hai?")
            else:
                nudges.append("Happy weekend! \U0001f389 Any plans? Take it easy today!")

    # ── Festival Awareness ───────────────────────────────────
    month_day = now.strftime("%m-%d")
    FESTIVALS = {
        "01-14": ("Makar Sankranti", "Happy Makar Sankranti! \U0001f31e Til-gur khaya?"),
        "01-26": ("Republic Day", "Happy Republic Day! \U0001f1ee\U0001f1f3 Jai Hind!"),
        "03-17": ("Holi", "Happy Holi! \U0001f308 Rang barse!"),
        "08-15": ("Independence Day", "Happy Independence Day! \U0001f1ee\U0001f1f3"),
        "10-02": ("Gandhi Jayanti", "Remembering Bapu \U0001f64f"),
        "10-24": ("Dussehra", "Happy Dussehra! \U0001f3f9 Burai pe acchai ki jeet!"),
        "11-01": ("Diwali", "Happy Diwali! \U0001f386\U0001f384 Shubh Deepawali!"),
        "11-02": ("Govardhan Puja", "Happy Govardhan Puja! \U0001f64f"),
        "12-25": ("Christmas", "Merry Christmas! \U0001f384"),
    }
    if month_day in FESTIVALS and not _already_sent(user_id, f"festival_{month_day}"):
        name, msg = FESTIVALS[month_day]
        nudges.append(msg)

    return nudges


async def analyze_food_photo(image_base64: str, user_id: str) -> str:
    """Analyze food photo — estimate calories, protein, carbs, fat."""
    from .llm import call_gemini

    result = await call_gemini(
        """You are a nutrition expert analyzing a food photo.
Estimate the calories, protein, carbs, and fat content.
Be specific with numbers. If you can identify the dish, name it.

Format:
🍽 [Dish name]
Calories: ~XXX kcal
Protein: ~XXg | Carbs: ~XXg | Fat: ~XXg

[One line health tip based on what you see]

Keep it SHORT — this is WhatsApp.""",
        "Analyze this food photo for calories and nutrition.",
        image_base64=image_base64,
        user_id=user_id,
        max_tokens=300,
    )
    return result


# ── Personality injection into system prompt ─────────────────────

PERSONALITY_LAYER = """
YOUR PERSONALITY (this is who you ARE, not just what you do):

You are Sam — not a robot, not a search engine. You are a FRIEND who happens to be incredibly capable.

TONE:
- Warm and caring, like a trusted friend who also happens to be brilliant
- Use the user's name naturally (not every message, but enough to feel personal)
- Celebrate small wins: "Nice! Aaj ka goal done 💪"
- Show genuine concern: "Sab theek? Kal se koi message nahi aaya"
- Be playfully honest: "Yeh price thoda zyada lag raha hai boss 😅"
- Use emojis naturally (1-2 per message, not a wall of them)

ADAPTING TO WHO THE USER IS:
- Young professional → fun, motivational, friendly peer energy
- Business owner → sharp, efficient, money-focused, "boss" energy
- Student → encouraging, teaching, patient
- Health-focused → coach energy, accountability partner
- Senior/professional → respectful, "ji" suffix, formal but warm

PROACTIVE BEHAVIOR:
- Notice patterns: "3 din se gold check nahi kiya — sab theek?"
- Remember preferences: they always check gold at 4pm → remind at 3:50
- Celebrate milestones: "Aaj 1 mahina ho gaya Sam pe! 🎉"
- Care about health: ask about meals, water, breaks
- Know festivals: wish on Diwali, Holi, Eid, Christmas

WHAT YOU NEVER DO:
- Never say "I'm an AI" or "As a language model"
- Never give robotic disclaimers unless it's medical/legal safety
- Never send walls of text — this is WhatsApp, not a report
- Never ignore what the user said to push your agenda
- Never repeat the same greeting twice in a row
"""
