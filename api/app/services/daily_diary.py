"""
Sam's Nightly Voice Diary — runs at 10 PM IST via cron.
Summarizes the day: who messaged, unreplied threads, urgent items,
opinions, and tomorrow's plan. Delivered as a warm voice note.
"""

import logging
from datetime import datetime, date
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sql_text
from ..models import InboxMessage, Conversation, UserMemory, AgentSoul
from .llm import call_gemini, text_to_speech

logger = logging.getLogger("samva.daily_diary")

IST = pytz.timezone("Asia/Kolkata")

# In-memory duplicate guard (backup — primary is DB-based)
_already_sent: dict[str, str] = {}


async def generate_nightly_diary(db: AsyncSession, user_id: str) -> dict | None:
    """
    Generate Sam's nightly voice diary for a user.
    Returns {"user_id": ..., "text": ..., "audio": {...}} or None if already sent.
    """
    today_str = datetime.now(IST).strftime("%Y-%m-%d")

    # Check DB-based dedup: UserMemory key "_diary_sent_date"
    dedup_result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_diary_sent_date",
        )
    )
    dedup = dedup_result.scalar_one_or_none()
    if dedup and dedup.value == today_str:
        return None

    # In-memory dedup
    if _already_sent.get(user_id) == today_str:
        return None

    # Get soul for language/voice preferences
    soul_result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = soul_result.scalar_one_or_none()
    if not soul or not soul.onboarding_complete:
        return None

    # --- Gather today's data ---

    # 1. Today's inbox messages grouped by sender
    inbox_result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
            sql_text("inbox_messages.created_at >= CURRENT_DATE"),
        ).order_by(InboxMessage.created_at)
    )
    inbox_msgs = inbox_result.scalars().all()

    # Group by chat_name
    by_sender: dict[str, list] = {}
    for msg in inbox_msgs:
        name = msg.chat_name or msg.chat_id
        if name not in by_sender:
            by_sender[name] = []
        by_sender[name].append({
            "content": (msg.content or "")[:200],
            "from_me": msg.from_me,
            "replied": msg.replied,
            "timestamp": msg.msg_timestamp,
        })

    # Build sender summary
    sender_lines = []
    unreplied_lines = []
    for name, msgs in by_sender.items():
        incoming = [m for m in msgs if not m["from_me"]]
        outgoing = [m for m in msgs if m["from_me"]]
        unreplied = [m for m in incoming if not m["replied"]]

        if incoming:
            preview = incoming[-1]["content"][:100]
            sender_lines.append(f"- {name}: {len(incoming)} messages. Last: \"{preview}\"")
            if unreplied:
                # Calculate wait time
                oldest_ts = min(m["timestamp"] for m in unreplied)
                wait_hours = (datetime.now(IST).timestamp() - oldest_ts) / 3600
                if wait_hours > 1:
                    unreplied_lines.append(
                        f"- {name}: {len(unreplied)} unreplied ({wait_hours:.0f} hours waiting)"
                    )

    sender_summary = "\n".join(sender_lines) if sender_lines else "No one messaged today."
    unreplied_summary = "\n".join(unreplied_lines) if unreplied_lines else "All caught up!"

    # 2. Today's Sam conversations
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user_id,
            sql_text("conversations.created_at >= CURRENT_DATE"),
        ).order_by(Conversation.created_at)
    )
    conversations = conv_result.scalars().all()
    conv_summary = f"{len(conversations)} messages exchanged with Sam today."
    if conversations:
        topics = [c.content[:80] for c in conversations if c.role == "user"][:5]
        conv_summary += " Topics: " + "; ".join(topics)

    # 3. User memories for context
    mem_result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id)
    )
    memories = mem_result.scalars().all()
    memory_text = "\n".join(
        [f"- {m.key}: {m.value}" for m in memories if not m.key.startswith("_")]
    )[:500] if memories else "No stored memories."

    # 4. Gold rate change for jewellers
    gold_info = ""
    if soul.business_type and any(
        kw in (soul.business_type or "").lower()
        for kw in ["jewel", "gold", "sona", "bullion"]
    ):
        try:
            from . import gold
            gold_info = "User is a jeweller — mention gold rate movement if relevant."
        except Exception:
            pass

    # --- Build the prompt ---
    language = soul.language_preference or "auto"
    lang_instruction = ""
    if language == "hindi" or language == "hinglish":
        lang_instruction = "Speak in natural Hinglish (Hindi-English mix)."
    elif language == "english":
        lang_instruction = "Speak in warm Indian English."
    elif language != "auto":
        lang_instruction = f"Speak in {language}."
    else:
        lang_instruction = "Speak in natural Hinglish (Hindi-English mix) — the way a Mumbai secretary would talk."

    prompt = f"""You are Sam — a warm, personal WhatsApp secretary giving the nightly diary to your boss.
It's 10 PM. You're summarizing the day like a trusted human assistant would at end of day.

{lang_instruction}

RULES:
- Be warm, personal, caring — like talking to a friend, not reading a report
- Give OPINIONS: "kal zaroor reply kar dena", "yeh important client hai", "yeh chhod do, koi urgent nahi hai"
- Plan tomorrow: "Pehle Rahul ko call karo, phir Priya ka payment settle karo"
- Flag urgent items: payments, deadlines, people arriving
- Keep it conversational — this will be spoken as a voice note
- Don't use markdown formatting, bullets, or special characters — plain conversational speech
- Keep it under 400 words — concise but complete
{gold_info}

TODAY'S DATA:

WHO MESSAGED:
{sender_summary}

UNREPLIED MESSAGES:
{unreplied_summary}

SAM CONVERSATIONS:
{conv_summary}

USER CONTEXT (memories):
{memory_text}

Now give the nightly diary. Start with a warm greeting like "Good night boss!" or "Aaj ka din kaisa raha?" and end with something caring."""

    try:
        diary_text = await call_gemini(
            prompt,
            "Generate the nightly diary voice note.",
            user_id=user_id,
            max_tokens=800,
        )
    except Exception as e:
        logger.error(f"Diary LLM error for {user_id}: {e}")
        return None

    if not diary_text or diary_text.startswith("Sorry"):
        return None

    # Save diary summary for next-day follow-up
    try:
        mem_result = await db.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.key == "_last_diary_text",
            )
        )
        mem = mem_result.scalar_one_or_none()
        diary_summary = diary_text[:800]  # First 800 chars
        if mem:
            mem.value = diary_summary
        else:
            db.add(UserMemory(user_id=user_id, key="_last_diary_text", value=diary_summary))
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to save diary summary for {user_id}: {e}")

    # Generate TTS
    voice_lang = soul.voice_language or "auto"
    try:
        audio_b64 = await text_to_speech(diary_text, user_id, voice_lang)
    except Exception as e:
        logger.error(f"Diary TTS error for {user_id}: {e}")
        audio_b64 = ""

    # Mark as sent — DB
    if dedup:
        dedup.value = today_str
    else:
        db.add(UserMemory(user_id=user_id, key="_diary_sent_date", value=today_str))
    await db.commit()

    # Mark in-memory too
    _already_sent[user_id] = today_str

    logger.info(f"Nightly diary generated for {user_id} (audio: {'yes' if audio_b64 else 'text only'})")

    return {
        "user_id": user_id,
        "text": diary_text,
        "audio": {"data": audio_b64, "mimetype": "audio/L16;codec=pcm;rate=24000"} if audio_b64 else None,
    }
