"""
FutureEcho — Sam simulates a wiser, future version of YOU.

Every 3-5 days (or on-demand), your future self sends a voice note.
Uses real data: diary entries, relationship patterns, inbox activity,
goals, health data, business patterns.

Not generic motivation — deeply personal, referencing real events.
"""

import logging
import random
from datetime import datetime, date
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sql_text
from ..models import AgentSoul, User, UserMemory, Conversation, InboxMessage
from .llm import call_gemini, text_to_speech

logger = logging.getLogger("samva.future_echo")
IST = pytz.timezone("Asia/Kolkata")


async def generate_future_echo(db: AsyncSession, user_id: str, time_horizon: str = "10 years") -> dict:
    """
    Generate a voice note from the user's future self.
    Returns {"user_id", "text", "audio": {"data", "mimetype"}} or None.
    """
    # Check if already sent recently (every 3 days minimum)
    mem_result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_last_echo_date",
        )
    )
    mem = mem_result.scalar_one_or_none()
    today = date.today()
    if mem:
        try:
            last_date = date.fromisoformat(mem.value)
            if (today - last_date).days < 3:
                return None  # Too soon
        except Exception:
            pass

    # Gather user data for personalization
    soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
    soul = soul_result.scalar_one_or_none()
    if not soul or not soul.onboarding_complete:
        return None

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    name = user.name or "friend"

    # Get recent diary
    diary_mem = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.key == "_last_diary_text")
    )
    diary = diary_mem.scalar_one_or_none()
    diary_text = diary.value[:500] if diary else ""

    # Get memories
    mem_all = await db.execute(select(UserMemory).where(
        UserMemory.user_id == user_id,
        ~UserMemory.key.startswith("_"),  # Skip internal keys
    ))
    memories = mem_all.scalars().all()
    memory_text = "\n".join(f"- {m.key}: {m.value}" for m in memories[:15]) if memories else "No memories yet."

    # Get recent conversation themes
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.role == "user",
        ).order_by(Conversation.created_at.desc()).limit(20)
    )
    recent_msgs = [c.content for c in conv_result.scalars().all()]
    recent_themes = "\n".join(f"- {m[:80]}" for m in recent_msgs[:10]) if recent_msgs else "Not much conversation yet."

    # Memory Beast — search for memorable moments
    from .memory_beast import search_conversations
    memorable = await search_conversations(db, user_id, "memorable important decision trip travel family celebration achievement problem solved", limit=5)
    memorable_text = "\n".join(f"- [{m['date']}] {m['role']}: {m['content']}" for m in memorable) if memorable else "No specific memorable moments found yet."

    # Get inbox stats
    inbox_count = await db.execute(
        select(func.count(InboxMessage.id)).where(
            InboxMessage.user_id == user_id,
            InboxMessage.from_me == False,
        ).where(sql_text("created_at >= NOW() - INTERVAL '7 days'"))
    )
    total_msgs_week = inbox_count.scalar() or 0

    unreplied = await db.execute(
        select(func.count(InboxMessage.id)).where(
            InboxMessage.user_id == user_id,
            InboxMessage.from_me == False,
            InboxMessage.replied == False,
        ).where(sql_text("created_at >= NOW() - INTERVAL '7 days'"))
    )
    unreplied_count = unreplied.scalar() or 0

    # Parse time horizon
    year_offset = 10
    if "5" in time_horizon: year_offset = 5
    elif "20" in time_horizon: year_offset = 20
    elif "15" in time_horizon: year_offset = 15
    future_year = today.year + year_offset

    # Pick a theme for this echo
    themes = [
        "career and business growth",
        "relationships and family",
        "health and habits",
        "financial decisions",
        "personal growth and wisdom",
    ]
    theme = random.choice(themes)

    lang = soul.language_preference or "hinglish"
    voice_lang = soul.voice_language or lang

    prompt = f"""You are {name} from the year {future_year}. You are the FUTURE version of this person, {year_offset} years older and wiser.

You are sending a WhatsApp voice note to your past self in {today.year}.

ABOUT YOUR PAST SELF (who you're talking to):
Name: {name}
Profile: {soul.system_prompt[:400] if soul.system_prompt else 'Building a life.'}

THEIR RECENT LIFE DATA (real, use this):
Recent diary: {diary_text or 'No diary entries yet.'}
Things they remember: {memory_text}
Recent topics: {recent_themes}
Memorable moments from their past: {memorable_text}
This week: {total_msgs_week} messages from contacts, {unreplied_count} unreplied.
Business type: {soul.business_type or 'unknown'}

TODAY'S THEME: Focus on {theme}

RULES FOR YOUR VOICE NOTE:
1. Speak as YOURSELF from the future — use "main", "hum", "mere saath", first person
2. Reference REAL events from their data — specific people, specific situations
3. Give ONE specific piece of advice based on their current situation
4. Share ONE "regret" or "lesson" that connects to what they're going through now
5. End with ONE micro-action they should take TODAY (not vague — specific)
6. Be warm, honest, emotional — like writing a letter to your younger self
7. Keep it under 45 seconds of speaking (roughly 120-150 words)
8. Speak in {lang}. Be natural, conversational.
9. Start with something like "Hey {name}, main hoon tu, {future_year} se..."
10. NEVER break character — you ARE this person, just older
11. Add the disclaimer naturally at the end: "Yeh AI-generated simulation hai — but the feeling is real"

DO NOT be generic. DO NOT give motivational poster quotes. Be SPECIFIC to their life."""

    try:
        echo_text = await call_gemini(prompt, f"Generate a voice note from {name}'s future self, theme: {theme}", user_id=user_id, max_tokens=400)

        if not echo_text or len(echo_text) < 50:
            return None

        # Generate voice note
        audio_b64 = await text_to_speech(echo_text, user_id, voice_lang)

        # Mark as sent
        if mem:
            mem.value = today.isoformat()
        else:
            db.add(UserMemory(user_id=user_id, key="_last_echo_date", value=today.isoformat()))
        await db.commit()

        logger.info(f"[{user_id}] FutureEcho generated ({future_year}, theme: {theme})")

        return {
            "user_id": user_id,
            "text": f"\U0001f52e *Echo from {future_year}*\n\n{echo_text}\n\n_AI-generated Future You simulation_",
            "audio": {"data": audio_b64, "mimetype": "audio/L16;codec=pcm;rate=24000"} if audio_b64 else None,
        }

    except Exception as e:
        logger.error(f"FutureEcho error for {user_id}: {e}", exc_info=True)
        return None


async def on_demand_echo(db: AsyncSession, user_id: str, topic: str = "", time_horizon: str = "10 years") -> str:
    """User asked for a FutureEcho on-demand: 'talk to future me about career'"""
    soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
    soul = soul_result.scalar_one_or_none()
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    name = user.name or "friend"

    # Get memories for context
    mem_all = await db.execute(select(UserMemory).where(
        UserMemory.user_id == user_id, ~UserMemory.key.startswith("_")
    ))
    memories = mem_all.scalars().all()
    memory_text = "\n".join(f"- {m.key}: {m.value}" for m in memories[:10]) if memories else ""

    year_offset = 10
    if "5" in time_horizon: year_offset = 5
    elif "20" in time_horizon: year_offset = 20
    future_year = date.today().year + year_offset

    lang = soul.language_preference or "hinglish" if soul else "hinglish"

    prompt = f"""You are {name} from {future_year}. Send a voice note to your {date.today().year} self about: {topic or 'life in general'}.

About you: {soul.system_prompt[:300] if soul and soul.system_prompt else ''}
Things you remember: {memory_text}

Be deeply personal, specific, warm. Reference their real life. Under 150 words. Speak in {lang}.
Start with "Hey {name}..." and end with one specific action for today.
Add: "Yeh AI simulation hai — but the feeling is real" at end."""

    try:
        return await call_gemini(prompt, f"FutureEcho on-demand about {topic}", user_id=user_id, max_tokens=400)
    except Exception as e:
        logger.error(f"On-demand echo error: {e}")
        return f"Future {name} is thinking... try again in a moment."
