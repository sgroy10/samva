"""
Life Observer — Sam's continuous intelligence engine.

This is what separates Sam from every other chatbot.
Sam doesn't wait to be asked. Sam OBSERVES your life and ACTS.

What Sam watches:
1. ALL WhatsApp messages (inbox_messages table)
2. ALL emails (if connected)
3. ALL spending patterns (from messages + emails)
4. ALL subscriptions (recurring payments)
5. ALL health signals (food orders, gym, medicine reminders)
6. ALL relationships (who you talk to, how often, sentiment)

What Sam does with observations:
- Spending alerts: "₹8,400/month subscriptions. Cancel karna hai?"
- Food alerts: "4th Zomato order this week. Ghar pe khana try karo?"
- Relationship alerts: "Mummy se 5 din se baat nahi hui. Call karo?"
- Health alerts: "3 din se gym nahi gaye. Kal jaroor jao!"
- Work alerts: "$90 Lovable charge — kya build kar rahe ho?"
- Booking alerts: "Dinner 7:30 pe. Restaurant speciality: tandoori"

This runs every 15 minutes and is the BRAIN of Sam's proactivity.
"""

import logging
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sql_text
from ..models import (
    InboxMessage, Conversation, UserMemory, Reminder,
    AgentSoul, User,
)

logger = logging.getLogger("samva.life_observer")


async def observe_life(db: AsyncSession, user_id: str) -> list:
    """
    The main observation loop. Scans all data sources and generates
    proactive intelligence. Returns list of messages to send.
    """
    observations = []

    # Get user context
    soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
    soul = soul_result.scalar_one_or_none()
    if not soul or not soul.onboarding_complete:
        return []

    lang = soul.language_preference or "hinglish"
    is_hindi = lang in ("hindi", "hinglish", "auto")

    # 1. Spending pattern detection
    spend = await _detect_spending_patterns(db, user_id, is_hindi)
    if spend:
        observations.append(spend)

    # 2. Food ordering patterns
    food = await _detect_food_patterns(db, user_id, is_hindi)
    if food:
        observations.append(food)

    # 3. Relationship health
    rel = await _detect_relationship_gaps(db, user_id, is_hindi)
    if rel:
        observations.append(rel)

    # 4. Subscription tracking
    subs = await _detect_subscriptions(db, user_id, is_hindi)
    if subs:
        observations.append(subs)

    # 5. Booking/event detection (restaurant, travel, appointment)
    events = await _detect_upcoming_events(db, user_id, is_hindi)
    if events:
        observations.extend(events)

    return observations


async def _detect_spending_patterns(db: AsyncSession, user_id: str, is_hindi: bool) -> str:
    """Detect spending patterns from WhatsApp messages (payment notifications)."""
    # Check if we already alerted today
    check = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == "_last_spend_alert",
        )
    )
    last_alert = check.scalar_one_or_none()
    if last_alert:
        try:
            last_date = datetime.fromisoformat(last_alert.value)
            if (datetime.utcnow() - last_date).days < 7:
                return ""  # Already alerted this week
        except Exception:
            pass

    # Search for payment-related messages in last 7 days
    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
        ).where(sql_text("created_at >= NOW() - INTERVAL '7 days'"))
    )
    messages = result.scalars().all()

    payment_keywords = [
        "debited", "credited", "payment of", "paid", "charged",
        "subscription", "renewed", "invoice", "receipt", "₹", "rs.",
        "upi", "transaction", "order placed",
    ]

    payment_msgs = []
    for msg in messages:
        content = (msg.content or "").lower()
        if any(kw in content for kw in payment_keywords):
            payment_msgs.append(msg)

    if len(payment_msgs) >= 5:
        # Extract amounts (basic pattern)
        import re
        amounts = []
        for msg in payment_msgs:
            nums = re.findall(r'[₹rs\.]?\s*(\d+[,\d]*\.?\d*)', (msg.content or "").lower())
            for n in nums:
                try:
                    val = float(n.replace(',', ''))
                    if 10 < val < 500000:  # Reasonable range
                        amounts.append(val)
                except (ValueError, TypeError):
                    pass

        if amounts:
            total = sum(amounts)
            count = len(amounts)

            # Save alert timestamp
            from sqlalchemy import delete as sa_delete
            await db.execute(sa_delete(UserMemory).where(
                UserMemory.user_id == user_id, UserMemory.key == "_last_spend_alert"
            ))
            db.add(UserMemory(user_id=user_id, key="_last_spend_alert", value=datetime.utcnow().isoformat()))
            await db.commit()

            if is_hindi:
                return (
                    f"💰 *Weekly Spend Alert:*\n\n"
                    f"Is hafte {count} payments detected.\n"
                    f"Approx total: ₹{total:,.0f}\n\n"
                    f"Zyada spend ho raha hai ya normal? Main track kar rahi hoon! 📊"
                )
            else:
                return (
                    f"💰 *Weekly Spend Alert:*\n\n"
                    f"{count} payments detected this week.\n"
                    f"Approx total: ₹{total:,.0f}\n\n"
                    f"Spending more than usual? I'm tracking! 📊"
                )
    return ""


async def _detect_food_patterns(db: AsyncSession, user_id: str, is_hindi: bool) -> str:
    """Detect excessive food ordering."""
    check = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == "_last_food_alert",
        )
    )
    last = check.scalar_one_or_none()
    if last:
        try:
            if (datetime.utcnow() - datetime.fromisoformat(last.value)).days < 3:
                return ""
        except Exception:
            pass

    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
        ).where(sql_text("created_at >= NOW() - INTERVAL '7 days'"))
    )
    messages = result.scalars().all()

    food_keywords = ["zomato", "swiggy", "order placed", "delivery partner",
                     "out for delivery", "food is ready", "dominos", "mcdonalds",
                     "burger king", "pizza hut", "kfc"]

    food_count = sum(1 for m in messages if any(kw in (m.content or "").lower() for kw in food_keywords))

    if food_count >= 4:
        from sqlalchemy import delete as sa_delete
        await db.execute(sa_delete(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == "_last_food_alert"
        ))
        db.add(UserMemory(user_id=user_id, key="_last_food_alert", value=datetime.utcnow().isoformat()))
        await db.commit()

        if is_hindi:
            return (
                f"🍔 *Food Order Alert:*\n\n"
                f"Is hafte {food_count} baar bahar se order kiya!\n"
                f"Health ke liye ghar ka khana better hai yaar.\n"
                f"Kal try karo — simple dal chawal bhi chalega! 💪"
            )
        else:
            return (
                f"🍔 *Food Order Alert:*\n\n"
                f"You ordered {food_count} times from delivery apps this week!\n"
                f"Home cooked meals are healthier. Try tomorrow? 💪"
            )
    return ""


async def _detect_relationship_gaps(db: AsyncSession, user_id: str, is_hindi: bool) -> str:
    """Detect if user hasn't talked to important people recently."""
    check = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == "_last_rel_alert",
        )
    )
    last = check.scalar_one_or_none()
    if last:
        try:
            if (datetime.utcnow() - datetime.fromisoformat(last.value)).days < 7:
                return ""
        except Exception:
            pass

    # Get important contacts from memory
    family_keywords = ["mummy", "papa", "wife", "husband", "mom", "dad", "bhai", "behen"]
    mem_result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id)
    )
    memories = mem_result.scalars().all()
    important_names = set()
    for m in memories:
        if any(kw in m.key.lower() for kw in family_keywords):
            important_names.add(m.value)

    if not important_names:
        return ""

    # Check last message from/to important people
    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
        ).where(sql_text("created_at >= NOW() - INTERVAL '14 days'"))
    )
    messages = result.scalars().all()

    name_last_seen = {}
    for msg in messages:
        sender = (msg.sender_name or msg.chat_name or "").lower()
        for name in important_names:
            if name.lower() in sender:
                if name not in name_last_seen:
                    name_last_seen[name] = msg.created_at

    # Find people not contacted in 7+ days
    silent = [name for name in important_names
              if name not in name_last_seen or
              (datetime.utcnow() - name_last_seen.get(name, datetime.min)).days >= 7]

    if silent:
        from sqlalchemy import delete as sa_delete
        await db.execute(sa_delete(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == "_last_rel_alert"
        ))
        db.add(UserMemory(user_id=user_id, key="_last_rel_alert", value=datetime.utcnow().isoformat()))
        await db.commit()

        names = ", ".join(silent[:3])
        if is_hindi:
            return f"💕 {names} se kaafi din se baat nahi hui. Ek call karo aaj? Family important hai! 🤗"
        else:
            return f"💕 Haven't talked to {names} in a while. Give them a call today? Family matters! 🤗"
    return ""


async def _detect_subscriptions(db: AsyncSession, user_id: str, is_hindi: bool) -> str:
    """Detect recurring subscriptions from payment messages."""
    check = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == "_last_sub_alert",
        )
    )
    last = check.scalar_one_or_none()
    if last:
        try:
            if (datetime.utcnow() - datetime.fromisoformat(last.value)).days < 30:
                return ""  # Monthly alert max
        except Exception:
            pass

    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
        ).where(sql_text("created_at >= NOW() - INTERVAL '30 days'"))
    )
    messages = result.scalars().all()

    sub_keywords = {
        "netflix": "Netflix", "spotify": "Spotify", "prime": "Amazon Prime",
        "hotstar": "Hotstar", "youtube premium": "YouTube Premium",
        "chatgpt": "ChatGPT", "claude": "Claude", "copilot": "Copilot",
        "lovable": "Lovable", "vercel": "Vercel", "railway": "Railway",
        "notion": "Notion", "figma": "Figma", "canva": "Canva",
        "icloud": "iCloud", "google one": "Google One",
        "jio": "Jio", "airtel": "Airtel",
    }

    detected_subs = set()
    for msg in messages:
        content = (msg.content or "").lower()
        if any(kw in content for kw in ["subscription", "renewed", "charged", "billing", "invoice"]):
            for keyword, name in sub_keywords.items():
                if keyword in content:
                    detected_subs.add(name)

    if len(detected_subs) >= 3:
        from sqlalchemy import delete as sa_delete
        await db.execute(sa_delete(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == "_last_sub_alert"
        ))
        db.add(UserMemory(user_id=user_id, key="_last_sub_alert", value=datetime.utcnow().isoformat()))
        await db.commit()

        subs_list = ", ".join(sorted(detected_subs))
        if is_hindi:
            return (
                f"📋 *Subscription Tracker:*\n\n"
                f"{len(detected_subs)} active subscriptions detected:\n"
                f"{subs_list}\n\n"
                f"Koi cancel karna hai? Ya sab use ho rahe hain? 🤔"
            )
        else:
            return (
                f"📋 *Subscription Tracker:*\n\n"
                f"{len(detected_subs)} active subscriptions:\n"
                f"{subs_list}\n\n"
                f"Want to cancel any? Or are they all in use? 🤔"
            )
    return ""


async def _detect_upcoming_events(db: AsyncSession, user_id: str, is_hindi: bool) -> list:
    """Detect upcoming events from messages (restaurant, travel, appointments)."""
    result = await db.execute(
        select(InboxMessage).where(
            InboxMessage.user_id == user_id,
        ).where(sql_text("created_at >= NOW() - INTERVAL '4 hours'"))
        .order_by(InboxMessage.msg_timestamp.desc()).limit(30)
    )
    messages = result.scalars().all()

    events = []
    event_keywords = {
        "restaurant": ["booking confirmed", "reservation", "table booked", "dineout",
                        "eazydiner", "restaurant booking"],
        "travel": ["flight confirmed", "ticket booked", "pnr", "boarding pass",
                    "hotel confirmation", "check-in"],
        "delivery": ["out for delivery", "arriving today", "will be delivered"],
        "appointment": ["appointment confirmed", "doctor", "consultation at"],
    }

    for msg in messages:
        content = (msg.content or "").lower()
        sender = msg.sender_name or msg.chat_name or ""

        for event_type, keywords in event_keywords.items():
            if any(kw in content for kw in keywords):
                if is_hindi:
                    emoji = {"restaurant": "🍽️", "travel": "✈️", "delivery": "📦", "appointment": "🏥"}
                    events.append(
                        f"{emoji.get(event_type, '📌')} *Sam noticed:* {sender} se {event_type} ki notification aayi.\n"
                        f"Reminder set karun? Details chahiye toh bolo!"
                    )
                else:
                    events.append(
                        f"📌 *Sam noticed:* {event_type} notification from {sender}.\n"
                        f"Want me to set a reminder? Ask for details!"
                    )
                break

    return events
