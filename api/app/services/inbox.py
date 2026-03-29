"""
Sam's Inbox — the core agent behaviour.

Sam reads ALL WhatsApp messages, stores them, summarizes them,
drafts replies, and auto-responds when the owner is busy.

This is what makes Sam an AGENT, not a chatbot.
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text as sql_text, update, func
from ..models import InboxMessage, User, AgentSoul
from .llm import call_gemini

logger = logging.getLogger("samva.inbox")


async def store_message(
    db: AsyncSession, user_id: str, chat_id: str, chat_name: str,
    sender_name: str, sender_id: str, content: str, from_me: bool, timestamp: int
):
    """Store an incoming/outgoing WhatsApp message to inbox."""
    db.add(InboxMessage(
        user_id=user_id,
        chat_id=chat_id,
        chat_name=chat_name or sender_name or chat_id.split("@")[0],
        sender_name=sender_name,
        sender_id=sender_id,
        content=content,
        from_me=from_me,
        msg_timestamp=timestamp,
    ))
    # If owner sent a message to this chat, mark thread as replied
    if from_me:
        await db.execute(
            update(InboxMessage).where(
                InboxMessage.user_id == user_id,
                InboxMessage.chat_id == chat_id,
                InboxMessage.replied == False,
            ).values(replied=True)
        )
    await db.commit()


async def get_inbox_summary(db: AsyncSession, user_id: str, hours: int = 24) -> str:
    """
    Summarize all messages from last N hours.
    Groups by sender. Shows count, preview, time ago.
    """
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

    # Group by chat
    by_chat = defaultdict(list)
    for msg in messages:
        by_chat[msg.chat_id].append(msg)

    now = datetime.utcnow()
    lines = [f"\U0001f4ec *Aaj ke messages* (last {hours}h):\n"]
    total_msgs = 0
    unreplied = 0

    for chat_id, msgs in by_chat.items():
        name = msgs[0].chat_name or msgs[0].sender_name or chat_id.split("@")[0]
        count = len(msgs)
        total_msgs += count
        latest = msgs[0]  # Already sorted desc

        # Time ago
        msg_time = datetime.utcfromtimestamp(latest.msg_timestamp) if latest.msg_timestamp else latest.created_at
        if msg_time:
            diff = now - msg_time
            if diff.total_seconds() < 3600:
                time_ago = f"{int(diff.total_seconds() / 60)} min ago"
            else:
                time_ago = f"{int(diff.total_seconds() / 3600)} hours ago"
        else:
            time_ago = ""

        # Preview — first message content truncated
        preview = latest.content[:60] if latest.content else ""

        # Check if replied
        is_replied = latest.replied
        if not is_replied:
            unreplied += 1

        reply_tag = "" if is_replied else " \u26a0\ufe0f"
        count_tag = f"({count} messages)" if count > 1 else ""

        lines.append(f"\u2022 *{name}*{reply_tag} — {preview} {count_tag} — {time_ago}")

    lines.append(f"\nTotal: {len(by_chat)} conversations, {total_msgs} messages")
    if unreplied > 0:
        lines.append(f"\u26a0\ufe0f {unreplied} unreplied")
    lines.append("\nKisi ko reply karna hai? Naam batao aur main draft kar deti hoon.")

    return "\n".join(lines)


async def get_chat_thread(db: AsyncSession, user_id: str, search_name: str, limit: int = 10) -> list:
    """Get recent messages from a specific contact by name search."""
    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
            InboxMessage.chat_name.ilike(f"%{search_name}%"),
        ).order_by(InboxMessage.msg_timestamp.desc()).limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def draft_reply(db: AsyncSession, user_id: str, contact_name: str, instruction: str = "") -> str:
    """
    Read the conversation thread with a contact and draft a reply.
    Uses Soul context so Sam replies as the owner.
    """
    # Get the thread
    thread = await get_chat_thread(db, user_id, contact_name)
    if not thread:
        return f"'{contact_name}' se koi message nahi mila. Naam check karo."

    # Get soul for context
    soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
    soul = soul_result.scalar_one_or_none()
    soul_prompt = soul.system_prompt if soul else ""

    # Get user name
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    owner_name = user.name if user else "Owner"

    # Format thread
    thread_text = "\n".join(
        f"{'Customer' if not m.from_me else owner_name}: {m.content}"
        for m in thread
    )

    customer_name = thread[0].chat_name or contact_name

    reply = await call_gemini(
        f"""You are drafting a WhatsApp reply on behalf of {owner_name}.

{owner_name}'s profile:
{soul_prompt[:500]}

The customer is: {customer_name}
Their conversation:
{thread_text}

{f'Owner instruction: {instruction}' if instruction else 'Draft a helpful, professional reply based on the conversation.'}

RULES:
- Write the reply as if {owner_name} is typing it
- Match the language the customer used
- Keep it short — WhatsApp style
- Use the owner's business knowledge from the profile
- Be warm and professional""",
        f"Draft reply to {customer_name}",
        user_id=user_id,
    )

    # Store pending reply in DB for confirmation
    chat_id = thread[0].chat_id
    await store_pending_reply(db, user_id, chat_id, reply, customer_name)

    return f"*Reply to {customer_name}:*\n\n{reply}\n\n_Bhejun? (haan/nahi)_"


async def store_pending_reply(db: AsyncSession, user_id: str, chat_id: str, reply_text: str, customer_name: str):
    """Store pending reply in DB — survives restarts."""
    from ..models import PendingReply
    # Clear old pending for this user
    from sqlalchemy import delete
    await db.execute(delete(PendingReply).where(PendingReply.user_id == user_id))
    db.add(PendingReply(
        user_id=user_id, chat_jid=chat_id,
        chat_name=customer_name, reply_text=reply_text,
    ))
    await db.commit()


async def confirm_and_send_reply(db: AsyncSession, user_id: str) -> dict:
    """Owner said "haan" — get pending reply from DB and return for sending."""
    from ..models import PendingReply
    from sqlalchemy import delete
    result = await db.execute(
        select(PendingReply).where(PendingReply.user_id == user_id)
        .order_by(PendingReply.created_at.desc()).limit(1)
    )
    pending = result.scalar_one_or_none()
    if not pending:
        return {}

    data = {
        "chat_id": pending.chat_jid,
        "text": pending.reply_text,
        "customer_name": pending.chat_name or "",
    }
    await db.execute(delete(PendingReply).where(PendingReply.user_id == user_id))
    await db.commit()
    return data


async def has_pending_reply(db: AsyncSession, user_id: str) -> bool:
    from ..models import PendingReply
    result = await db.execute(
        select(PendingReply).where(PendingReply.user_id == user_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def cancel_pending_reply(db: AsyncSession, user_id: str):
    from ..models import PendingReply
    from sqlalchemy import delete
    await db.execute(delete(PendingReply).where(PendingReply.user_id == user_id))
    await db.commit()


async def check_auto_reply_needed(db: AsyncSession, user_id: str) -> list:
    """
    Find messages where customer has been waiting 2+ hours with no reply.
    Returns list of {chat_id, chat_name, message} for auto-reply.
    """
    two_hours_ago = datetime.utcnow() - timedelta(hours=2)

    # Find unreplied messages older than 2 hours
    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
            InboxMessage.from_me == False,
            InboxMessage.replied == False,
            InboxMessage.auto_replied == False,
        ).where(sql_text("created_at <= NOW() - INTERVAL '2 hours'"))
    )
    messages = result.scalars().all()

    # Group by chat — only auto-reply once per chat
    seen_chats = set()
    auto_replies = []

    # Get owner name
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    owner_name = user.name if user else "the owner"

    for msg in messages:
        if msg.chat_id in seen_chats:
            continue
        seen_chats.add(msg.chat_id)

        customer_name = msg.chat_name or msg.sender_name or "customer"

        auto_replies.append({
            "chat_id": msg.chat_id,
            "chat_name": customer_name,
            "message": (
                f"Namaste {customer_name}! {owner_name} abhi available nahi hain. "
                f"Main Sam hoon, unki assistant. Kaise help kar sakti hoon?"
            ),
        })

        # Mark as auto-replied
        await db.execute(
            update(InboxMessage).where(
                InboxMessage.user_id == user_id,
                InboxMessage.chat_id == msg.chat_id,
                InboxMessage.auto_replied == False,
            ).values(auto_replied=True)
        )

    if auto_replies:
        await db.commit()

    return auto_replies


async def get_morning_inbox_summary(db: AsyncSession, user_id: str) -> str:
    """Short inbox summary for the morning brief."""
    result = await db.execute(
        select(
            func.count(InboxMessage.id).label("total"),
        ).where(
            InboxMessage.user_id == user_id,
            InboxMessage.from_me == False,
        ).where(sql_text("created_at >= NOW() - INTERVAL '24 hours'"))
    )
    row = result.one_or_none()
    total = row.total if row else 0

    if total == 0:
        return ""

    # Count unreplied
    unreplied_result = await db.execute(
        select(func.count(InboxMessage.id)).where(
            InboxMessage.user_id == user_id,
            InboxMessage.from_me == False,
            InboxMessage.replied == False,
        ).where(sql_text("created_at >= NOW() - INTERVAL '24 hours'"))
    )
    unreplied = unreplied_result.scalar() or 0

    summary = f"\n\U0001f4ec *Inbox:* {total} messages"
    if unreplied > 0:
        summary += f" ({unreplied} unreplied \u26a0\ufe0f)"
    summary += "\nBolo 'messages dikhao' for details."

    return summary
