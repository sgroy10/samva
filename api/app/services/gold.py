import logging
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import AgentSoul

logger = logging.getLogger("samva.gold")

GOLD_KEYWORDS = ["jewel", "gold", "sona", "trader", "bullion", "ornament", "diamond"]


async def should_get_gold_brief(db: AsyncSession, user_id: str) -> bool:
    """Check if user's business type is related to gold/jewellery."""
    result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = result.scalar_one_or_none()
    if not soul or not soul.business_type or not soul.daily_brief_enabled:
        return False

    bt = soul.business_type.lower()
    return any(kw in bt for kw in GOLD_KEYWORDS)


async def get_gold_brief(db: AsyncSession, user_id: str) -> str:
    """Get formatted gold/silver brief for jewellers."""
    try:
        # Get international gold price
        gold_usd = None
        silver_usd = None
        usd_inr = None

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Gold price from free API
            try:
                resp = await client.get("https://api.gold-api.com/price/XAU")
                if resp.status_code == 200:
                    data = resp.json()
                    gold_usd = data.get("price")  # per oz
            except Exception:
                pass

            # Silver
            try:
                resp = await client.get("https://api.gold-api.com/price/XAG")
                if resp.status_code == 200:
                    data = resp.json()
                    silver_usd = data.get("price")  # per oz
            except Exception:
                pass

            # USD/INR exchange rate
            try:
                resp = await client.get("https://open.er-api.com/v6/latest/USD")
                if resp.status_code == 200:
                    data = resp.json()
                    usd_inr = data.get("rates", {}).get("INR", 83.5)
            except Exception:
                usd_inr = 83.5

        if not gold_usd:
            return ""

        # Calculate Indian prices
        india_premium = 1.069  # ~6.9% India premium
        grams_per_oz = 31.1035

        gold_inr_per_gram_24k = (gold_usd * usd_inr * india_premium) / grams_per_oz
        gold_22k = gold_inr_per_gram_24k * 0.916
        gold_18k = gold_inr_per_gram_24k * 0.75

        silver_inr_per_gram = None
        if silver_usd:
            silver_premium = 1.20  # 20% India premium
            silver_inr_per_gram = (silver_usd * usd_inr * silver_premium) / grams_per_oz

        # Format brief
        lines = [
            "\ud83c\udfc5 *GOLD TODAY*",
            f"24K: \u20b9{gold_inr_per_gram_24k:,.0f}/gm",
            f"22K: \u20b9{gold_22k:,.0f}/gm",
            f"18K: \u20b9{gold_18k:,.0f}/gm",
        ]

        if silver_inr_per_gram:
            lines.append(f"Silver: \u20b9{silver_inr_per_gram:,.0f}/gm")

        lines.append(f"\nSpot: ${gold_usd:,.1f}/oz | \u20b9/{usd_inr:.1f}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Gold brief error for {user_id}: {e}")
        return ""
