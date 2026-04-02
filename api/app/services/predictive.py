"""
Predictive Behavior — learns patterns after just 2 occurrences.
Predicts when contacts will message, when user checks gold, etc.
"""

import logging
from datetime import datetime
from collections import defaultdict
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text as sql_text
from ..models import InboxMessage, Conversation, UserMemory

logger = logging.getLogger("samva.predictive")

IST = pytz.timezone("Asia/Kolkata")


async def check_predictions(db: AsyncSession, user_id: str) -> list[str]:
    """
    Check for predictable patterns and return prediction alerts.
    Only alerts once per day (dedup via UserMemory).
    """
    alerts = []
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")

    try:
        # Dedup check — only once per day
        dedup_key = f"_predictions_sent_{today_str}"
        dedup_result = await db.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.key == dedup_key,
            )
        )
        if dedup_result.scalar_one_or_none():
            return []

        # --- Pattern 1: Same contact, same day-of-week ---
        msgs_result = await db.execute(
            select(InboxMessage).where(
                InboxMessage.user_id == user_id,
                InboxMessage.from_me == False,
                sql_text("inbox_messages.created_at >= NOW() - INTERVAL '30 days'"),
            ).order_by(InboxMessage.msg_timestamp)
        )
        inbox_msgs = msgs_result.scalars().all()

        if inbox_msgs:
            # Group by chat_id + day_of_week + hour_bucket
            patterns: dict[str, dict] = defaultdict(lambda: defaultdict(list))
            for msg in inbox_msgs:
                ts = datetime.fromtimestamp(msg.msg_timestamp, IST)
                day_name = ts.strftime("%A")  # Monday, Tuesday, etc.
                hour_bucket = ts.hour
                chat_name = msg.chat_name or msg.chat_id
                key = f"{msg.chat_id}|{day_name}"
                patterns[key]["name"] = chat_name
                patterns[key]["day"] = day_name
                patterns[key]["hours"].append(hour_bucket)
                patterns[key]["dates"].append(ts.date())

            current_day = now_ist.strftime("%A")
            current_hour = now_ist.hour

            for key, data in patterns.items():
                if data["day"] != current_day:
                    continue

                # Count unique dates (not just messages)
                unique_dates = len(set(data["dates"]))
                if unique_dates < 2:
                    continue

                # Check if they typically message around this hour (±2 hours)
                typical_hours = data["hours"]
                nearby = [h for h in typical_hours if abs(h - current_hour) <= 2]
                if nearby:
                    avg_hour = sum(nearby) // len(nearby)
                    am_pm = "AM" if avg_hour < 12 else "PM"
                    display_hour = avg_hour if avg_hour <= 12 else avg_hour - 12
                    if display_hour == 0:
                        display_hour = 12

                    alerts.append(
                        f"🔮 Aaj {current_day} hai. Last {unique_dates} "
                        f"{current_day}s {data['name']} ne ~{display_hour} {am_pm} "
                        f"pe message kiya. Ready raho!"
                    )

        # --- Pattern 2: User checks gold at same time ---
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.role == "user",
                sql_text("conversations.created_at >= NOW() - INTERVAL '14 days'"),
            ).order_by(Conversation.created_at)
        )
        conversations = conv_result.scalars().all()

        gold_keywords = {"gold", "rate", "sona", "bhav", "rates", "gold rate"}
        gold_hours = []
        for conv in conversations:
            content_lower = (conv.content or "").lower()
            if any(kw in content_lower for kw in gold_keywords):
                if conv.created_at:
                    # Convert to IST
                    conv_ist = conv.created_at.replace(tzinfo=pytz.UTC).astimezone(IST) if conv.created_at.tzinfo is None else conv.created_at.astimezone(IST)
                    gold_hours.append(conv_ist.hour)

        if len(gold_hours) >= 3:
            # Check if they cluster around the same hour
            from collections import Counter
            hour_counts = Counter(gold_hours)
            most_common_hour, count = hour_counts.most_common(1)[0]
            if count >= 3:
                am_pm = "AM" if most_common_hour < 12 else "PM"
                display_hour = most_common_hour if most_common_hour <= 12 else most_common_hour - 12
                if display_hour == 0:
                    display_hour = 12
                alerts.append(
                    f"📊 Aap roz ~{display_hour} {am_pm} baje gold check karte ho — "
                    f"main automatically bhej doon?"
                )

        # Save dedup if we have alerts
        if alerts:
            db.add(UserMemory(user_id=user_id, key=dedup_key, value=str(len(alerts))))
            await db.commit()

    except Exception as e:
        logger.error(f"Prediction error for {user_id}: {e}", exc_info=True)

    return alerts[:3]  # Max 3 predictions at once
