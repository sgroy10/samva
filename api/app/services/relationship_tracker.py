"""
Relationship Intelligence — tracks response patterns per contact.
Detects decay, cross-contact intelligence, and weekly reports.
"""

import logging
from datetime import datetime, timedelta
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sql_text
from ..models import InboxMessage, Conversation, AgentSoul, UserMemory
from .llm import call_gemini

logger = logging.getLogger("samva.relationship")

IST = pytz.timezone("Asia/Kolkata")


async def check_relationship_decay(db: AsyncSession, user_id: str) -> list[str]:
    """
    Check for contacts where response time has increased significantly.
    Returns alert strings for contacts showing decay.
    """
    alerts = []

    try:
        # Get all inbox messages from last 30 days, grouped by chat_id
        msgs_result = await db.execute(
            select(InboxMessage).where(
                InboxMessage.user_id == user_id,
                sql_text("inbox_messages.created_at >= NOW() - INTERVAL '30 days'"),
            ).order_by(InboxMessage.msg_timestamp)
        )
        all_msgs = msgs_result.scalars().all()

        if not all_msgs:
            return []

        # Group by chat_id
        by_chat: dict[str, list] = {}
        for msg in all_msgs:
            chat_id = msg.chat_id
            if chat_id not in by_chat:
                by_chat[chat_id] = []
            by_chat[chat_id].append(msg)

        # Check dedup — only alert once per day per user
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        dedup_key = f"_decay_alert_{today_str}"
        dedup_result = await db.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.key == dedup_key,
            )
        )
        if dedup_result.scalar_one_or_none():
            return []

        for chat_id, msgs in by_chat.items():
            # Need at least 5 messages to analyze
            if len(msgs) < 5:
                continue

            chat_name = msgs[-1].chat_name or chat_id

            # Calculate response times: time between their message and user's reply
            response_times = []
            for i, msg in enumerate(msgs):
                if msg.from_me:
                    continue
                # Find next from_me message after this one
                for j in range(i + 1, len(msgs)):
                    if msgs[j].from_me and msgs[j].chat_id == chat_id:
                        delta = msgs[j].msg_timestamp - msg.msg_timestamp
                        if delta > 0:
                            response_times.append(delta)
                        break

            if len(response_times) < 3:
                continue

            # Split into historical (first half) and recent (last half)
            mid = len(response_times) // 2
            historical_avg = sum(response_times[:mid]) / mid
            recent_avg = sum(response_times[mid:]) / (len(response_times) - mid)

            # If recent response time is 2x+ the historical average
            if historical_avg > 0 and recent_avg > historical_avg * 2:
                hist_hours = historical_avg / 3600
                recent_hours = recent_avg / 3600

                if hist_hours < 1:
                    hist_label = f"{historical_avg / 60:.0f} min"
                else:
                    hist_label = f"{hist_hours:.0f} hours"

                if recent_hours < 1:
                    recent_label = f"{recent_avg / 60:.0f} min"
                elif recent_hours < 24:
                    recent_label = f"{recent_hours:.0f} hours"
                else:
                    recent_label = f"{recent_hours / 24:.1f} din"

                alerts.append(
                    f"⚠️ {chat_name} ke saath response time {recent_label} ho gayi. "
                    f"Pehle {hist_label} mein reply karte the."
                )

        # Mark dedup if we generated alerts
        if alerts:
            db.add(UserMemory(user_id=user_id, key=dedup_key, value=str(len(alerts))))
            await db.commit()

    except Exception as e:
        logger.error(f"Relationship decay error for {user_id}: {e}", exc_info=True)

    return alerts[:3]  # Max 3 decay alerts at once


async def get_cross_contact_intelligence(
    db: AsyncSession, user_id: str, current_message: str
) -> str:
    """
    When user gets a message asking about price/product/info,
    check if someone else asked the same thing before.
    Returns intelligence string or empty string.
    """
    try:
        if not current_message or len(current_message) < 10:
            return ""

        # Search recent inbox + conversations for similar questions
        # Look for price/rate/cost mentions
        price_keywords = ["price", "rate", "cost", "kitna", "kya rate", "bhav",
                          "charges", "fees", "quotation", "quote", "amount"]
        has_price_query = any(kw in current_message.lower() for kw in price_keywords)
        if not has_price_query:
            return ""

        # Search inbox messages from other contacts for similar content
        search_result = await db.execute(
            select(InboxMessage).where(
                InboxMessage.user_id == user_id,
                sql_text("inbox_messages.created_at >= NOW() - INTERVAL '30 days'"),
            ).order_by(InboxMessage.created_at.desc()).limit(200)
        )
        recent_msgs = search_result.scalars().all()

        # Find similar questions from other contacts
        similar = []
        for msg in recent_msgs:
            if msg.from_me:
                continue
            content_lower = (msg.content or "").lower()
            if any(kw in content_lower for kw in price_keywords):
                similar.append({
                    "name": msg.chat_name or msg.chat_id,
                    "content": msg.content[:150],
                    "chat_id": msg.chat_id,
                })

        if not similar:
            return ""

        # Check if user replied with a price to any of these
        for s in similar[:5]:
            reply_result = await db.execute(
                select(InboxMessage).where(
                    InboxMessage.user_id == user_id,
                    InboxMessage.chat_id == s["chat_id"],
                    InboxMessage.from_me == True,
                    sql_text("inbox_messages.created_at >= NOW() - INTERVAL '30 days'"),
                ).order_by(InboxMessage.created_at.desc()).limit(5)
            )
            replies = reply_result.scalars().all()
            for reply in replies:
                reply_lower = (reply.content or "").lower()
                # Check if reply contains numbers (likely a price/rate)
                if any(c.isdigit() for c in reply.content or ""):
                    return (
                        f"💡 {s['name']} ne bhi yahi pucha tha — "
                        f"aapne reply kiya tha: \"{reply.content[:100]}\""
                    )

        return ""

    except Exception as e:
        logger.error(f"Cross-contact intelligence error for {user_id}: {e}", exc_info=True)
        return ""


async def get_weekly_report(db: AsyncSession, user_id: str) -> dict | None:
    """
    Weekly report card: messages received/sent, most active contact,
    avg response time, unreplied count.
    Returns dict with "text" key or None.
    """
    try:
        # Get soul for language
        soul_result = await db.execute(
            select(AgentSoul).where(AgentSoul.user_id == user_id)
        )
        soul = soul_result.scalar_one_or_none()
        if not soul or not soul.onboarding_complete:
            return None

        # This week's messages
        msgs_result = await db.execute(
            select(InboxMessage).where(
                InboxMessage.user_id == user_id,
                sql_text("inbox_messages.created_at >= NOW() - INTERVAL '7 days'"),
            ).order_by(InboxMessage.msg_timestamp)
        )
        week_msgs = msgs_result.scalars().all()

        if not week_msgs:
            return None

        # Stats
        received = [m for m in week_msgs if not m.from_me]
        sent = [m for m in week_msgs if m.from_me]
        unreplied = [m for m in received if not m.replied]

        # Most active contact
        contact_counts: dict[str, int] = {}
        for msg in received:
            name = msg.chat_name or msg.chat_id
            contact_counts[name] = contact_counts.get(name, 0) + 1
        most_active = max(contact_counts, key=contact_counts.get) if contact_counts else "N/A"
        most_active_count = contact_counts.get(most_active, 0)

        # Average response time
        response_times = []
        by_chat: dict[str, list] = {}
        for msg in week_msgs:
            if msg.chat_id not in by_chat:
                by_chat[msg.chat_id] = []
            by_chat[msg.chat_id].append(msg)

        for chat_id, msgs in by_chat.items():
            for i, msg in enumerate(msgs):
                if msg.from_me:
                    continue
                for j in range(i + 1, len(msgs)):
                    if msgs[j].from_me:
                        delta = msgs[j].msg_timestamp - msg.msg_timestamp
                        if 0 < delta < 86400 * 3:  # cap at 3 days
                            response_times.append(delta)
                        break

        avg_response = ""
        if response_times:
            avg_secs = sum(response_times) / len(response_times)
            if avg_secs < 3600:
                avg_response = f"{avg_secs / 60:.0f} minutes"
            else:
                avg_response = f"{avg_secs / 3600:.1f} hours"
        else:
            avg_response = "N/A"

        # Unique contacts this week
        unique_contacts = len(set(m.chat_id for m in received))

        # Build report with Gemini for natural language
        language = soul.language_preference or "auto"
        lang_instruction = ""
        if language in ("hindi", "hinglish"):
            lang_instruction = "Speak in Hinglish."
        elif language == "english":
            lang_instruction = "Speak in warm Indian English."
        else:
            lang_instruction = "Speak in natural Hinglish."

        prompt = f"""You are Sam, giving a weekly WhatsApp report card to your boss.
{lang_instruction}

Make it warm, brief, conversational — like a friend summarizing the week.
No markdown or special formatting — this will be spoken aloud.
Keep it under 200 words.

STATS:
- Messages received: {len(received)}
- Messages sent: {len(sent)}
- Unique contacts: {unique_contacts}
- Most active contact: {most_active} ({most_active_count} messages)
- Average response time: {avg_response}
- Unreplied messages: {len(unreplied)}

Give a fun, warm summary. Include a rating (like "8/10 week" or "busy week!").
End with one tip to improve next week."""

        try:
            report_text = await call_gemini(
                prompt,
                "Generate the weekly report card.",
                user_id=user_id,
                max_tokens=500,
            )
        except Exception as e:
            logger.error(f"Weekly report LLM error for {user_id}: {e}")
            return None

        if not report_text or report_text.startswith("Sorry"):
            return None

        return {
            "user_id": user_id,
            "text": report_text,
            "stats": {
                "received": len(received),
                "sent": len(sent),
                "most_active": most_active,
                "avg_response_time": avg_response,
                "unreplied": len(unreplied),
                "unique_contacts": unique_contacts,
            },
        }

    except Exception as e:
        logger.error(f"Weekly report error for {user_id}: {e}", exc_info=True)
        return None
