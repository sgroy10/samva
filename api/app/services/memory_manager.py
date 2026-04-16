"""
Hierarchical Memory Manager — Letta/MemGPT-inspired.

Sam's memory has 3 tiers:
1. CORE MEMORY (always in prompt):
   - User facts (name, business, preferences)
   - Last 5 messages (immediate context)
   - Active reminders/tasks
   - Current image in context

2. WORKING MEMORY (summarized, in prompt):
   - Compressed summary of last 48 hours
   - Key events/decisions from recent days
   - Pending follow-ups from diary

3. ARCHIVAL MEMORY (searched on demand):
   - Full conversation history (via Memory Beast)
   - Old inbox messages
   - Past diary entries
   - Old evolution records

This replaces the raw "dump 20 conversations" approach.
Reduces prompt from ~5000 tokens to ~1500 tokens while keeping Sam smart.
"""

import logging
from datetime import datetime, timedelta
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ..models import Conversation, UserMemory, Reminder, AgentSoul

logger = logging.getLogger("samva.memory_manager")
IST = pytz.timezone("Asia/Kolkata")


async def build_core_memory(db: AsyncSession, user_id: str) -> str:
    """Tier 1: Always in prompt. User facts + immediate context."""

    # User memories (facts) — wrapped in context fence
    mem_result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            ~UserMemory.key.startswith("_"),  # Skip internal keys
        )
    )
    memories = mem_result.scalars().all()
    if memories:
        mem_lines = "\n".join(f"- {m.key}: {m.value}" for m in memories[:30])
        facts = f"<memory-context>\n{mem_lines}\n</memory-context>"
    else:
        facts = "None saved yet."

    # Last 5 messages (immediate thread)
    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .limit(5)
    )
    recent = conv_result.scalars().all()
    thread = "\n".join(
        f"{c.role}: {c.content[:200]}" for c in reversed(list(recent))
    ) if recent else "First conversation."

    # Active reminders
    now_utc = datetime.utcnow()
    rem_result = await db.execute(
        select(Reminder).where(
            Reminder.user_id == user_id,
            Reminder.sent == False,
            Reminder.remind_at >= now_utc - timedelta(hours=24),
        ).order_by(Reminder.remind_at).limit(5)
    )
    reminders = rem_result.scalars().all()
    if reminders:
        rem_text = "\n".join(
            f"- {r.text} (at {r.remind_at.strftime('%d %b %I:%M %p')})"
            for r in reminders
        )
    else:
        rem_text = "None pending."

    return f"""CORE MEMORY (always available):

User's saved facts:
{facts}

Last messages (immediate thread):
{thread}

Pending reminders:
{rem_text}"""


async def build_working_memory(db: AsyncSession, user_id: str) -> str:
    """Tier 2: Compressed summary of last 48 hours."""

    cutoff = datetime.utcnow() - timedelta(hours=48)  # Use naive UTC to match DB

    # Get conversations from last 48h
    conv_result = await db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.created_at >= cutoff,
        )
        .order_by(Conversation.created_at.desc())
        .limit(30)  # Last 30 messages from 48h
    )
    conversations = conv_result.scalars().all()

    if len(conversations) < 3:
        return ""  # Not enough for a summary

    # Build a compressed summary instead of raw dump
    topics = set()
    people_mentioned = set()
    key_events = []

    for c in conversations:
        content = (c.content or "").lower()

        # Extract topics
        if any(w in content for w in ["gold", "rate", "sona"]):
            topics.add("gold rates")
        if any(w in content for w in ["payment", "pending", "paisa"]):
            topics.add("payments")
        if any(w in content for w in ["meeting", "call", "milna"]):
            topics.add("meetings")
        if any(w in content for w in ["email", "mail"]):
            topics.add("emails")
        if any(w in content for w in ["order", "client", "customer"]):
            topics.add("business")
        if any(w in content for w in ["health", "doctor", "medicine", "gym"]):
            topics.add("health")
        if any(w in content for w in ["family", "wife", "husband", "mummy", "papa"]):
            topics.add("family")

        # Extract names mentioned (simple heuristic — capitalized words)
        words = (c.content or "").split()
        for w in words:
            if w[0:1].isupper() and len(w) > 2 and w.lower() not in {
                "the", "and", "for", "but", "not", "you", "sam", "hey", "yes",
                "main", "kya", "aaj", "kal", "good", "morning",
            }:
                people_mentioned.add(w)

        # Key events (assistant messages with actions)
        if c.role == "assistant" and any(w in content for w in [
            "done!", "noted!", "reminder set", "saved", "sent", "booked",
        ]):
            key_events.append(c.content[:100])

    summary_parts = []
    if topics:
        summary_parts.append(f"Topics discussed: {', '.join(sorted(topics))}")
    if people_mentioned:
        summary_parts.append(f"People mentioned: {', '.join(sorted(people_mentioned)[:10])}")
    if key_events:
        summary_parts.append(f"Recent actions: {'; '.join(key_events[:5])}")

    if not summary_parts:
        return ""

    return f"""WORKING MEMORY (last 48 hours summary):
{chr(10).join(summary_parts)}
{len(conversations)} messages exchanged in last 48 hours."""


async def build_full_context(db: AsyncSession, user_id: str, user, soul) -> str:
    """Build the complete memory context for the system prompt.
    Replaces the old raw conversation dump."""

    core = await build_core_memory(db, user_id)
    working = await build_working_memory(db, user_id)

    # Diary context (from last night)
    diary_text = ""
    try:
        diary_result = await db.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.key == "_last_diary_text",
            )
        )
        diary_mem = diary_result.scalar_one_or_none()
        if diary_mem:
            diary_text = f"\nLAST DIARY ENTRY:\n{diary_mem.value[:300]}"
    except Exception:
        pass

    # Feedback stats (what user likes/dislikes)
    feedback_text = ""
    try:
        from .feedback import get_feature_stats
        stats = await get_feature_stats(db, user_id)
        if stats:
            liked = [f for f, s in stats.items() if s.get("positive", 0) > s.get("negative", 0)]
            disliked = [f for f, s in stats.items() if s.get("negative", 0) >= 3]
            if liked:
                feedback_text += f"\nUser LIKES: {', '.join(liked)}"
            if disliked:
                feedback_text += f"\nUser DISLIKES (don't send): {', '.join(disliked)}"
    except Exception:
        pass

    # Learned behaviors from Hermes-style skill learner
    learned_text = ""
    try:
        from .skill_learner import get_learned_context
        learned_text = await get_learned_context(db, user_id)
    except Exception:
        pass

    return f"""{core}

{working}
{diary_text}
{feedback_text}
{learned_text}"""
