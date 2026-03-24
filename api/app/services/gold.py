"""
Gold/Silver/Platinum brief service.
- Any user can ask "gold rate" and get live prices instantly
- Jeweller users get auto morning brief at 9am IST
- Price change alerts for jeweller users (>150/gm move)
"""

import logging
from datetime import datetime, date, time
import pytz
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import AgentSoul, UserMemory
from .llm import call_gemini

logger = logging.getLogger("samva.gold")

IST = pytz.timezone("Asia/Kolkata")

GOLD_KEYWORDS = ["jewel", "gold", "sona", "trader", "bullion", "ornament", "diamond", "jewellery", "jewelry"]
PRICE_ALERT_THRESHOLD = 150  # INR per gram change triggers alert


async def _fetch_prices() -> dict:
    """Fetch live gold, silver, platinum prices + USD/INR."""
    prices = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Gold (XAU) from gold-api.com
        try:
            resp = await client.get("https://api.gold-api.com/price/XAU")
            if resp.status_code == 200:
                prices["gold_usd_oz"] = resp.json().get("price")
        except Exception as e:
            logger.warning(f"Gold API failed: {e}")

        # Silver (XAG)
        try:
            resp = await client.get("https://api.gold-api.com/price/XAG")
            if resp.status_code == 200:
                prices["silver_usd_oz"] = resp.json().get("price")
        except Exception as e:
            logger.warning(f"Silver API failed: {e}")

        # Platinum (XPT)
        try:
            resp = await client.get("https://api.gold-api.com/price/XPT")
            if resp.status_code == 200:
                prices["platinum_usd_oz"] = resp.json().get("price")
        except Exception as e:
            logger.warning(f"Platinum API failed: {e}")

        # USD/INR
        try:
            resp = await client.get("https://open.er-api.com/v6/latest/USD")
            if resp.status_code == 200:
                prices["usd_inr"] = resp.json().get("rates", {}).get("INR", 83.5)
        except Exception:
            prices["usd_inr"] = 83.5

    if not prices.get("gold_usd_oz"):
        return {}

    # Calculate Indian prices
    usd_inr = prices["usd_inr"]
    india_premium = 1.069  # ~6.9% India retail premium
    grams_per_oz = 31.1035

    gold_24k = (prices["gold_usd_oz"] * usd_inr * india_premium) / grams_per_oz
    prices["gold_24k"] = gold_24k
    prices["gold_22k"] = gold_24k * 0.916
    prices["gold_18k"] = gold_24k * 0.75
    prices["gold_14k"] = gold_24k * 0.585

    if prices.get("silver_usd_oz"):
        silver_premium = 1.20
        prices["silver_inr"] = (prices["silver_usd_oz"] * usd_inr * silver_premium) / grams_per_oz

    if prices.get("platinum_usd_oz"):
        platinum_premium = 1.10
        prices["platinum_inr"] = (prices["platinum_usd_oz"] * usd_inr * platinum_premium) / grams_per_oz

    return prices


async def _get_user_memory(db: AsyncSession, user_id: str, key: str) -> str:
    """Get a value from user memory."""
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.key == key)
    )
    mem = result.scalar_one_or_none()
    return mem.value if mem else None


async def _set_user_memory(db: AsyncSession, user_id: str, key: str, value: str):
    """Upsert a value in user memory."""
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.key == key)
    )
    mem = result.scalar_one_or_none()
    if mem:
        mem.value = value
        mem.updated_at = datetime.utcnow()
    else:
        db.add(UserMemory(user_id=user_id, key=key, value=value))


def _format_change(current: float, previous_str: str) -> str:
    """Format price change indicator."""
    if not previous_str:
        return ""
    try:
        previous = float(previous_str)
        diff = current - previous
        if abs(diff) < 0.5:
            return ""
        arrow = "\u2191" if diff > 0 else "\u2193"
        return f" {arrow}\u20b9{abs(diff):,.0f}"
    except (ValueError, TypeError):
        return ""


async def get_gold_brief(db: AsyncSession, user_id: str) -> str:
    """Get formatted gold/silver/platinum brief. Works for ANY user."""
    prices = await _fetch_prices()
    if not prices:
        return "Gold prices fetch nahi ho paaye. Thodi der mein try karo."

    # Get yesterday's prices for change indicators
    yesterday_24k = await _get_user_memory(db, user_id, "gold_price_yesterday")
    yesterday_silver = await _get_user_memory(db, user_id, "silver_price_yesterday")

    # Calculate changes
    chg_24k = _format_change(prices["gold_24k"], yesterday_24k)
    chg_22k = _format_change(prices["gold_22k"], str(float(yesterday_24k) * 0.916) if yesterday_24k else None)
    chg_18k = _format_change(prices["gold_18k"], str(float(yesterday_24k) * 0.75) if yesterday_24k else None)
    chg_silver = _format_change(prices.get("silver_inr", 0), yesterday_silver) if prices.get("silver_inr") else ""

    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%d %b %Y")

    lines = [
        f"\U0001f304 *MORNING BRIEF* -- {date_str}",
        "",
        "\U0001f4b0 *GOLD* (\u20b9/gram)",
        f"\u25b8 24K \u20b9{prices['gold_24k']:,.0f}{chg_24k}",
        f"\u25b8 22K \u20b9{prices['gold_22k']:,.0f}{chg_22k}",
        f"\u25b8 18K \u20b9{prices['gold_18k']:,.0f}{chg_18k}",
        f"\u25b8 14K \u20b9{prices['gold_14k']:,.0f}",
    ]

    if prices.get("silver_inr"):
        lines.append(f"\n\U0001fa99 Silver \u20b9{prices['silver_inr']:,.0f}/gm{chg_silver}")

    if prices.get("platinum_inr"):
        lines.append(f"\u2b1c Platinum \u20b9{prices['platinum_inr']:,.0f}/gm")

    lines.append(f"\n\U0001f30d *International*")
    lines.append(f"\u25b8 Gold ${prices['gold_usd_oz']:,.1f}/oz")
    if prices.get("silver_usd_oz"):
        lines.append(f"\u25b8 Silver ${prices['silver_usd_oz']:,.2f}/oz")
    lines.append(f"\u25b8 USD/INR \u20b9{prices['usd_inr']:.2f}")

    # Expert view from Gemini
    try:
        expert = await call_gemini(
            "You are a gold market expert. Give a ONE paragraph (3-4 lines max) expert analysis. Include: should jewellers BUY, HOLD, or WAIT today and why. Mention any trends. Be specific and actionable. No disclaimers.",
            f"Gold 24K: Rs{prices['gold_24k']:,.0f}/gm, yesterday: Rs{yesterday_24k or 'unknown'}/gm. Silver: Rs{prices.get('silver_inr', 0):,.0f}/gm. International gold: ${prices['gold_usd_oz']:,.1f}/oz. Date: {date_str}",
            user_id=user_id,
        )
        lines.append(f"\n\U0001f4a1 *EXPERT VIEW*\n{expert}")
    except Exception as e:
        logger.warning(f"Expert analysis failed: {e}")

    lines.append(f"\nSay 'rates' anytime for live prices")

    # Save today's price as yesterday for tomorrow's change calc
    await _set_user_memory(db, user_id, "gold_price_yesterday", str(round(prices["gold_24k"], 2)))
    if prices.get("silver_inr"):
        await _set_user_memory(db, user_id, "silver_price_yesterday", str(round(prices["silver_inr"], 2)))
    # Save current price for alert tracking
    await _set_user_memory(db, user_id, "gold_price_last", str(round(prices["gold_24k"], 2)))

    await db.commit()
    return "\n".join(lines)


def _is_jeweller(business_type: str) -> bool:
    """Check if business type is gold/jewellery related."""
    if not business_type:
        return False
    bt = business_type.lower()
    return any(kw in bt for kw in GOLD_KEYWORDS)


async def should_get_gold_brief(db: AsyncSession, user_id: str) -> bool:
    """
    Check if user should get the 9am gold brief RIGHT NOW.
    All three conditions must be true:
    1. Business type is jewellery-related
    2. Current IST time is between 9:00-9:15am
    3. Brief hasn't been sent today yet
    """
    result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = result.scalar_one_or_none()
    if not soul or not soul.onboarding_complete or not soul.daily_brief_enabled:
        return False

    # Condition 1: jeweller business type
    if not _is_jeweller(soul.business_type):
        return False

    # Condition 2: between 9:00-9:15 IST
    now_ist = datetime.now(IST)
    if not (time(9, 0) <= now_ist.time() <= time(9, 15)):
        return False

    # Condition 3: not already sent today
    today = now_ist.date()
    if soul.last_gold_brief_date and soul.last_gold_brief_date >= today:
        return False

    return True


async def mark_brief_sent(db: AsyncSession, user_id: str):
    """Mark that today's brief has been sent."""
    today = datetime.now(IST).date()
    await db.execute(
        update(AgentSoul)
        .where(AgentSoul.user_id == user_id)
        .values(last_gold_brief_date=today)
    )
    await db.commit()


async def check_price_alerts(db: AsyncSession, user_id: str) -> str:
    """
    Check if gold price moved >150/gm since last check.
    Returns alert message or empty string.
    Called on every 15-minute cron run for jeweller users.
    """
    result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = result.scalar_one_or_none()
    if not soul or not _is_jeweller(soul.business_type):
        return ""

    # Get last known price
    last_price_str = await _get_user_memory(db, user_id, "gold_price_last")
    if not last_price_str:
        return ""

    try:
        last_price = float(last_price_str)
    except (ValueError, TypeError):
        return ""

    # Fetch current price
    prices = await _fetch_prices()
    if not prices or not prices.get("gold_24k"):
        return ""

    current = prices["gold_24k"]
    diff = current - last_price

    # Save new price regardless
    await _set_user_memory(db, user_id, "gold_price_last", str(round(current, 2)))
    await db.commit()

    if abs(diff) >= PRICE_ALERT_THRESHOLD:
        arrow = "\u2191" if diff > 0 else "\u2193"
        return (
            f"\U0001f6a8 *Gold Alert:* 24K \u20b9{current:,.0f} "
            f"-- moved {arrow}\u20b9{abs(diff):,.0f} since last check"
        )

    return ""
