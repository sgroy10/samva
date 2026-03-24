"""
INVENTION 1 — Soul Evolution.
Every Sunday 11pm IST, Sam analyzes the past week and evolves
each user's Soul automatically. No user action needed.
"""

import logging
from datetime import datetime, timedelta, date
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import (
    AgentSoul, User, Conversation, Reminder,
    Contact, MeetingNote, SoulEvolution, UserMemory,
)
from .llm import call_gemini_json

logger = logging.getLogger("samva.soul_evolution")
IST = pytz.timezone("Asia/Kolkata")

EVOLUTION_PROMPT = """You are analysing a week of interactions for a personal assistant called Sam.

Based on this data, identify:
1. PATTERNS — what does this person repeatedly ask, forget, or struggle with?
2. IMPROVEMENTS — what should Sam start doing proactively that it currently doesn't?
3. SOUL UPDATES — what specific lines should be added or changed in Sam's system prompt?

CRITICAL RULES:
- NEVER remove or replace existing soul content — only ADD new lines
- Be specific — "remind user about invoices every Friday" not "be more helpful"
- Only suggest changes justified by actual data patterns
- If no meaningful evolution needed this week, return empty arrays

Current Soul:
{soul}

This week's data:
{data}

Return JSON:
{{
  "patterns_found": ["pattern 1", "pattern 2"],
  "new_proactive_behaviors": ["behavior 1", "behavior 2"],
  "soul_additions": ["add this line to soul", "add this line too"],
  "evolution_summary": "one sentence of what changed and why"
}}"""


async def evolve_user_soul(db: AsyncSession, user_id: str) -> dict:
    """
    Analyze last 7 days and evolve this user's Soul.
    Returns the evolution result dict.
    """
    # Get soul
    result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = result.scalar_one_or_none()
    if not soul or not soul.onboarding_complete:
        return {}

    # Check if already evolved this week
    now_utc = datetime.utcnow()
    week_start = (now_utc - timedelta(days=7)).date()

    existing = await db.execute(
        select(SoulEvolution).where(
            SoulEvolution.user_id == user_id,
            SoulEvolution.week_date >= week_start,
        )
    )
    if existing.scalar_one_or_none():
        logger.info(f"[{user_id}] Already evolved this week, skipping")
        return {}

    # Gather last 7 days of data using raw SQL interval to avoid timezone issues
    from sqlalchemy import text as sql_text

    # Conversations
    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .where(sql_text("created_at >= NOW() - INTERVAL '7 days'"))
        .order_by(Conversation.created_at)
        .limit(200)
    )
    conversations = conv_result.scalars().all()
    conv_summary = "\n".join(
        f"{c.role}: {c.content[:150]}" for c in conversations
    ) if conversations else "No conversations this week."

    # Reminders created
    rem_result = await db.execute(
        select(Reminder)
        .where(Reminder.user_id == user_id)
        .where(sql_text("created_at >= NOW() - INTERVAL '7 days'"))
    )
    reminders_list = rem_result.scalars().all()
    rem_summary = "\n".join(
        f"- Reminder: {r.text} (type: {r.type})" for r in reminders_list
    ) if reminders_list else "No reminders created."

    # Contacts saved
    cont_result = await db.execute(
        select(Contact)
        .where(Contact.user_id == user_id)
        .where(sql_text("created_at >= NOW() - INTERVAL '7 days'"))
    )
    contacts_list = cont_result.scalars().all()
    cont_summary = "\n".join(
        f"- Contact: {c.full_name} ({c.company or 'no company'}) via {c.source}" for c in contacts_list
    ) if contacts_list else "No contacts saved."

    # Meeting notes
    meet_result = await db.execute(
        select(MeetingNote)
        .where(MeetingNote.user_id == user_id)
        .where(sql_text("created_at >= NOW() - INTERVAL '7 days'"))
    )
    meetings_list = meet_result.scalars().all()
    meet_summary = "\n".join(
        f"- Meeting at {m.location or '?'}: {(m.raw_transcript or '')[:100]}" for m in meetings_list
    ) if meetings_list else "No meeting notes."

    # Memories updated
    mem_result = await db.execute(
        select(UserMemory)
        .where(UserMemory.user_id == user_id)
        .where(sql_text("updated_at >= NOW() - INTERVAL '7 days'"))
    )
    memories_list = mem_result.scalars().all()
    mem_summary = "\n".join(
        f"- Memory: {m.key} = {m.value}" for m in memories_list
    ) if memories_list else "No memory updates."

    # Build the full data block
    week_data = f"""CONVERSATIONS ({len(conversations)} messages):
{conv_summary[:3000]}

REMINDERS CREATED ({len(reminders_list)}):
{rem_summary}

CONTACTS SAVED ({len(contacts_list)}):
{cont_summary}

MEETING NOTES ({len(meetings_list)}):
{meet_summary}

MEMORY UPDATES ({len(memories_list)}):
{mem_summary}"""

    # If no activity at all, skip evolution
    total_activity = len(conversations) + len(reminders_list) + len(contacts_list) + len(meetings_list)
    if total_activity == 0:
        logger.info(f"[{user_id}] No activity this week, skipping evolution")
        return {}

    # Call Gemini for analysis
    prompt = EVOLUTION_PROMPT.replace("{soul}", soul.system_prompt[:2000]).replace("{data}", week_data[:4000])

    try:
        evolution = await call_gemini_json(prompt, "Analyze and evolve.", user_id=user_id)
    except Exception as e:
        logger.error(f"[{user_id}] Evolution Gemini call failed: {e}")
        return {}

    patterns = evolution.get("patterns_found", [])
    new_behaviors = evolution.get("new_proactive_behaviors", [])
    soul_additions = evolution.get("soul_additions", [])
    summary = evolution.get("evolution_summary", "")

    # APPEND soul additions (NEVER delete existing content)
    if soul_additions:
        additions_text = "\n\n--- EVOLVED (week of " + week_start.isoformat() + ") ---\n"
        additions_text += "\n".join(f"- {line}" for line in soul_additions)

        new_prompt = soul.system_prompt + additions_text
        await db.execute(
            update(AgentSoul)
            .where(AgentSoul.user_id == user_id)
            .values(system_prompt=new_prompt)
        )

    # Save evolution record
    evo = SoulEvolution(
        user_id=user_id,
        week_date=now_utc.date(),
        patterns_found=patterns,
        new_behaviors=new_behaviors,
        evolution_summary=summary,
    )
    db.add(evo)
    await db.commit()

    logger.info(f"[{user_id}] Soul evolved: {summary[:100]}")
    return {
        "patterns": patterns,
        "behaviors": new_behaviors,
        "additions": soul_additions,
        "summary": summary,
    }


async def run_soul_evolution_for_all(db: AsyncSession) -> list[dict]:
    """
    Run soul evolution for ALL active users.
    Called by cron every Sunday 11pm IST.
    Returns list of {user_id, summary} for users who evolved.
    """
    result = await db.execute(
        select(User).where(User.status == "active")
    )
    users = result.scalars().all()

    evolved = []
    for user in users:
        try:
            evo = await evolve_user_soul(db, user.id)
            if evo and evo.get("summary"):
                evolved.append({
                    "user_id": user.id,
                    "summary": evo["summary"],
                })
        except Exception as e:
            logger.error(f"[{user.id}] Soul evolution failed: {e}", exc_info=True)

    logger.info(f"Soul evolution complete: {len(evolved)}/{len(users)} users evolved")
    return evolved


async def get_evolution_message(db: AsyncSession, user_id: str) -> str:
    """
    Get the Monday 9am evolution notification message.
    Returns empty string if no evolution happened this week.
    """
    now = datetime.now(IST)
    week_start = (now - timedelta(days=7)).date()

    result = await db.execute(
        select(SoulEvolution)
        .where(
            SoulEvolution.user_id == user_id,
            SoulEvolution.week_date >= week_start,
        )
        .order_by(SoulEvolution.created_at.desc())
        .limit(1)
    )
    evo = result.scalar_one_or_none()

    if not evo or not evo.evolution_summary:
        return ""

    # Get user's language preference
    soul_result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = soul_result.scalar_one_or_none()
    lang = soul.language_preference if soul else "auto"

    if lang in ("hindi", "hinglish"):
        return f"Sam ne apne aap ko aapke liye aur better bana liya \U0001f9e0 -- {evo.evolution_summary}"
    else:
        return f"Sam upgraded itself for you \U0001f9e0 -- {evo.evolution_summary}"
