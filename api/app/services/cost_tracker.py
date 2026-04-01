"""
API Cost Tracker — logs every API call with token counts and cost.

Pricing (per 1M tokens):
- OpenRouter Gemini 2.5 Flash: $0.15 in, $0.60 out
- OpenRouter Gemini 2.5 Pro: $1.25 in, $10.00 out
- OpenRouter Claude Sonnet 4: $3.00 in, $15.00 out
- OpenRouter Claude Haiku 4.5: $0.80 in, $4.00 out
- Gemini API (TTS): ~$0.075 in (preview, estimated)
- Gemini API (Transcribe): $0.15 in, $0.60 out
- Perplexity: ~$0.005/call flat
- GemLens/JewelCraft: $0 (our own Supabase functions)
"""

import logging
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sql_text
from ..models import ApiCostLog

logger = logging.getLogger("samva.cost")

USD_TO_INR = 84

# Pricing per 1M tokens (USD)
PRICING = {
    "google/gemini-2.5-flash": {"in": 0.15, "out": 0.60},
    "google/gemini-2.5-pro-preview": {"in": 1.25, "out": 10.00},
    "anthropic/claude-sonnet-4": {"in": 3.00, "out": 15.00},
    "anthropic/claude-haiku-4-5-20251001": {"in": 0.80, "out": 4.00},
    "gemini-tts": {"in": 0.075, "out": 0.0},  # TTS preview estimate
    "gemini-transcribe": {"in": 0.15, "out": 0.60},
    "perplexity": {"flat": 0.005},
}


def calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Calculate USD cost for a given model and token count."""
    pricing = PRICING.get(model)
    if not pricing:
        # Default to flash pricing
        pricing = PRICING["google/gemini-2.5-flash"]
    if "flat" in pricing:
        return pricing["flat"]
    cost = (tokens_in / 1_000_000) * pricing["in"] + (tokens_out / 1_000_000) * pricing["out"]
    return round(cost, 6)


async def log_cost(
    db: AsyncSession,
    api_type: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    endpoint: str = "",
    user_id: str = "",
):
    """Log an API call cost to the database."""
    try:
        cost_usd = calc_cost(model, tokens_in, tokens_out)
        cost_inr = round(cost_usd * USD_TO_INR, 4)
        db.add(ApiCostLog(
            user_id=user_id or None,
            api_type=api_type,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            cost_inr=cost_inr,
            endpoint=endpoint,
        ))
        await db.commit()
    except Exception as e:
        logger.error(f"Cost log error: {e}")


async def get_daily_costs(db: AsyncSession, target_date: date = None) -> dict:
    """Get cost breakdown for a specific day."""
    if not target_date:
        target_date = date.today()

    date_str = target_date.isoformat()

    # Total cost
    total = await db.execute(
        select(
            func.sum(ApiCostLog.cost_inr).label("total_inr"),
            func.sum(ApiCostLog.cost_usd).label("total_usd"),
            func.count(ApiCostLog.id).label("call_count"),
            func.sum(ApiCostLog.tokens_in).label("total_tokens_in"),
            func.sum(ApiCostLog.tokens_out).label("total_tokens_out"),
        ).where(sql_text(f"DATE(created_at) = '{date_str}'"))
    )
    row = total.one()

    # By API type
    by_type = await db.execute(
        select(
            ApiCostLog.api_type,
            func.sum(ApiCostLog.cost_inr).label("cost_inr"),
            func.count(ApiCostLog.id).label("calls"),
            func.sum(ApiCostLog.tokens_in).label("tokens_in"),
            func.sum(ApiCostLog.tokens_out).label("tokens_out"),
        ).where(sql_text(f"DATE(created_at) = '{date_str}'"))
        .group_by(ApiCostLog.api_type)
    )
    type_breakdown = [
        {
            "api_type": r.api_type,
            "cost_inr": round(r.cost_inr or 0, 2),
            "calls": r.calls,
            "tokens_in": r.tokens_in or 0,
            "tokens_out": r.tokens_out or 0,
        }
        for r in by_type.all()
    ]

    # By user
    by_user = await db.execute(
        select(
            ApiCostLog.user_id,
            func.sum(ApiCostLog.cost_inr).label("cost_inr"),
            func.count(ApiCostLog.id).label("calls"),
        ).where(sql_text(f"DATE(created_at) = '{date_str}'"))
        .group_by(ApiCostLog.user_id)
    )
    user_breakdown = [
        {
            "user_id": r.user_id or "system",
            "cost_inr": round(r.cost_inr or 0, 2),
            "calls": r.calls,
        }
        for r in by_user.all()
    ]

    # By endpoint
    by_endpoint = await db.execute(
        select(
            ApiCostLog.endpoint,
            func.sum(ApiCostLog.cost_inr).label("cost_inr"),
            func.count(ApiCostLog.id).label("calls"),
        ).where(sql_text(f"DATE(created_at) = '{date_str}'"))
        .group_by(ApiCostLog.endpoint)
    )
    endpoint_breakdown = [
        {
            "endpoint": r.endpoint or "unknown",
            "cost_inr": round(r.cost_inr or 0, 2),
            "calls": r.calls,
        }
        for r in by_endpoint.all()
    ]

    return {
        "date": date_str,
        "total_cost_inr": round(row.total_inr or 0, 2),
        "total_cost_usd": round(row.total_usd or 0, 4),
        "total_calls": row.call_count or 0,
        "total_tokens_in": row.total_tokens_in or 0,
        "total_tokens_out": row.total_tokens_out or 0,
        "by_api_type": type_breakdown,
        "by_user": user_breakdown,
        "by_endpoint": endpoint_breakdown,
    }


async def get_monthly_costs(db: AsyncSession, year: int = None, month: int = None) -> dict:
    """Get cost breakdown for a month."""
    now = date.today()
    if not year:
        year = now.year
    if not month:
        month = now.month

    result = await db.execute(
        select(
            func.sum(ApiCostLog.cost_inr).label("total_inr"),
            func.sum(ApiCostLog.cost_usd).label("total_usd"),
            func.count(ApiCostLog.id).label("call_count"),
        ).where(sql_text(f"EXTRACT(YEAR FROM created_at) = {year} AND EXTRACT(MONTH FROM created_at) = {month}"))
    )
    row = result.one()

    # Daily breakdown for chart
    daily = await db.execute(
        select(
            sql_text("DATE(created_at) as day"),
            func.sum(ApiCostLog.cost_inr).label("cost_inr"),
            func.count(ApiCostLog.id).label("calls"),
        ).where(sql_text(f"EXTRACT(YEAR FROM created_at) = {year} AND EXTRACT(MONTH FROM created_at) = {month}"))
        .group_by(sql_text("DATE(created_at)"))
        .order_by(sql_text("DATE(created_at)"))
    )
    daily_data = [
        {"date": str(r[0]), "cost_inr": round(r[1] or 0, 2), "calls": r[2]}
        for r in daily.all()
    ]

    return {
        "year": year,
        "month": month,
        "total_cost_inr": round(row.total_inr or 0, 2),
        "total_cost_usd": round(row.total_usd or 0, 4),
        "total_calls": row.call_count or 0,
        "daily": daily_data,
    }
