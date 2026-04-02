"""
Chat Intelligence — Sam's inbox brain.

Reads ALL WhatsApp messages (stored by bridge in real-time to InboxMessage).
Analyzes for urgency. Generates insights. Flags what needs attention.
Sam NEVER auto-replies — only shows owner what's important.
"""

import logging
from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import InboxMessage, ChatInsight
from .llm import call_gemini_json

logger = logging.getLogger("samva.chat_intel")


async def store_message_batch(db: AsyncSession, user_id: str, messages: list):
    """Store a batch of WhatsApp messages from bridge (legacy endpoint)."""
    for msg in messages:
        db.add(InboxMessage(
            user_id=user_id,
            chat_id=msg.get("chatId", ""),
            chat_name=msg.get("chatName", ""),
            sender_name=msg.get("senderName", ""),
            content=msg.get("content", ""),
            from_me=msg.get("fromMe", False),
            msg_timestamp=msg.get("timestamp", 0),
        ))
    await db.commit()
    logger.info(f"[{user_id}] Stored {len(messages)} chat messages")


async def analyze_new_messages(db: AsyncSession, user_id: str) -> list:
    """
    Analyze unanalyzed inbox messages. Group by chat, classify urgency.
    Returns list of insights for urgent/important messages.
    Uses InboxMessage table (where bridge stores ALL messages in real-time).
    """
    from sqlalchemy import text as sql_text
    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
            InboxMessage.from_me == False,
        ).where(sql_text("created_at >= NOW() - INTERVAL '1 hour'"))
        .order_by(InboxMessage.msg_timestamp.desc()).limit(100)
    )
    messages = result.scalars().all()

    if not messages:
        return []

    # Group by chat
    by_chat = defaultdict(list)
    for msg in messages:
        by_chat[msg.chat_id].append(msg)

    # Check which chats already have recent insights (dedup — don't re-analyze same hour)
    from sqlalchemy import text as sql_text2
    existing_result = await db.execute(
        select(ChatInsight.chat_id).where(
            ChatInsight.user_id == user_id,
        ).where(sql_text2("created_at >= NOW() - INTERVAL '1 hour'"))
    )
    recently_analyzed = {r[0] for r in existing_result.all()}

    insights = []
    for chat_id, msgs in by_chat.items():
        if chat_id in recently_analyzed:
            continue  # Already analyzed this chat recently

        # Get last 5 messages from this chat for context
        combined = "\n".join(
            f"{m.sender_name or 'Unknown'}: {m.content}" for m in msgs[-5:]
        )
        chat_name = msgs[0].chat_name or chat_id.split("@")[0]

        try:
            analysis = await call_gemini_json(
                """Analyze these WhatsApp messages and classify.
Return JSON:
{
    "is_urgent": true/false,
    "category": "customer_inquiry/price_request/complaint/order/follow_up/personal/general",
    "summary": "one line what this person wants or said",
    "suggested_reply": "brief reply the owner could send",
    "priority": "high/medium/low"
}
Priority guide:
- HIGH: payment pending, complaint, angry, deadline, someone arriving/coming, emergency
- MEDIUM: question waiting for answer, price inquiry, order discussion, follow-up, anything that needs a response
- LOW: greetings only, forwards, status updates that don't need reply""",
                combined,
                user_id=user_id,
                max_tokens=150,
            )

            if analysis.get("is_urgent") or analysis.get("priority") in ("high", "medium"):
                insight = ChatInsight(
                    user_id=user_id,
                    chat_id=chat_id,
                    chat_name=chat_name,
                    summary=analysis.get("summary", ""),
                    category=analysis.get("category", "general"),
                    suggested_reply=analysis.get("suggested_reply", ""),
                    priority=analysis.get("priority", "medium"),
                )
                db.add(insight)
                insights.append(insight)
                logger.info(f"[{user_id}] Insight: {chat_name} — {analysis.get('priority')} — {analysis.get('summary','')[:60]}")

        except Exception as e:
            logger.error(f"Chat analysis error for {chat_id}: {e}")

    if insights:
        await db.commit()
    return insights


async def get_undelivered_insights(db: AsyncSession, user_id: str) -> str:
    """Get urgent chat insights that haven't been shown to user yet."""
    result = await db.execute(
        select(ChatInsight).where(
            ChatInsight.user_id == user_id,
            ChatInsight.delivered == False,
            ChatInsight.priority.in_(["high", "medium"]),
        ).order_by(ChatInsight.created_at.desc()).limit(5)
    )
    insights = result.scalars().all()

    if not insights:
        return ""

    lines = ["\U0001f4ec *Messages that need your attention:*\n"]
    for insight in insights:
        emoji = "\U0001f534" if insight.priority == "high" else "\U0001f7e1"
        lines.append(f"{emoji} *{insight.chat_name}* -- {insight.summary}")
        if insight.suggested_reply:
            lines.append(f"   \U0001f4ac Suggested: _{insight.suggested_reply}_")

    lines.append("\nReply karna hai? Naam batao aur main draft kar deti hoon.")

    # Mark as delivered
    for insight in insights:
        insight.delivered = True
    await db.commit()

    return "\n".join(lines)


async def get_chat_summary(db: AsyncSession, user_id: str, hours: int = 24) -> str:
    """Full chat summary for inbox command."""
    from sqlalchemy import text as sql_text, func

    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
            InboxMessage.from_me == False,
        ).where(sql_text(f"created_at >= NOW() - INTERVAL '{hours} hours'"))
        .order_by(InboxMessage.msg_timestamp.desc())
    )
    messages = result.scalars().all()

    if not messages:
        return "\U0001f4ed Koi naya message nahi aaya last 24 hours mein."

    by_chat = defaultdict(list)
    for msg in messages:
        by_chat[msg.chat_id].append(msg)

    from datetime import datetime
    now = datetime.utcnow()

    lines = [f"\U0001f4ec *Last {hours}h messages:*\n"]
    total = 0
    for chat_id, msgs in by_chat.items():
        name = msgs[0].chat_name or chat_id.split("@")[0]
        count = len(msgs)
        total += count
        preview = msgs[0].content[:50] if msgs[0].content else ""

        # Time ago
        ts = msgs[0].msg_timestamp
        if ts:
            diff = int(now.timestamp()) - ts
            if diff < 3600:
                ago = f"{diff // 60}m ago"
            else:
                ago = f"{diff // 3600}h ago"
        else:
            ago = ""

        count_str = f" ({count})" if count > 1 else ""
        lines.append(f"\u2022 *{name}*{count_str} -- {preview} -- {ago}")

    lines.append(f"\nTotal: {len(by_chat)} chats, {total} messages")
    lines.append("Reply karna hai? Naam batao.")

    return "\n".join(lines)
