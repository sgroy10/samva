import logging
import httpx
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import StockWatchlist
from .llm import call_gemini_json

logger = logging.getLogger("samva.stocks")

SYMBOL_MAP = {
    "nifty": "^NSEI",
    "nifty50": "^NSEI",
    "sensex": "^BSESN",
    "banknifty": "^NSEBANK",
    "btc": "BTC-USD",
    "bitcoin": "BTC-USD",
    "eth": "ETH-USD",
    "ethereum": "ETH-USD",
}


def normalize_symbol(raw: str) -> str:
    """Normalize stock symbol to Yahoo Finance format."""
    s = raw.strip().upper()
    low = raw.strip().lower()

    if low in SYMBOL_MAP:
        return SYMBOL_MAP[low]

    # Already has exchange suffix
    if "." in s or "-" in s or s.startswith("^"):
        return s

    # Default to NSE for Indian stocks
    return f"{s}.NS"


async def get_price(symbol: str) -> dict:
    """Get current price from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return {}
            data = resp.json()
            meta = data["chart"]["result"][0]["meta"]
            return {
                "symbol": symbol,
                "price": meta.get("regularMarketPrice", 0),
                "prev_close": meta.get("previousClose", 0),
                "currency": meta.get("currency", "INR"),
                "name": meta.get("shortName", symbol),
            }
    except Exception as e:
        logger.error(f"Price fetch error for {symbol}: {e}")
        return {}


async def add_to_watchlist(db: AsyncSession, user_id: str, text: str) -> str:
    """Parse user request and add stocks to watchlist."""
    extracted = await call_gemini_json(
        """Extract stock symbols from the user's message.
Return JSON: {"stocks": [{"name": "company name", "symbol": "SYMBOL"}], "action": "add" or "remove", "target_high": null, "target_low": null}
For Indian stocks, use NSE symbols. Examples:
- "Watch Reliance" -> {"stocks": [{"name": "Reliance Industries", "symbol": "RELIANCE"}], "action": "add"}
- "Remove TCS from watchlist" -> {"stocks": [{"name": "TCS", "symbol": "TCS"}], "action": "remove"}
- "Alert me when Infosys crosses 1800" -> {"stocks": [{"name": "Infosys", "symbol": "INFY"}], "action": "add", "target_high": 1800}""",
        text,
        user_id=user_id,
    )

    if "error" in extracted or not extracted.get("stocks"):
        return "Which stock would you like me to watch? Tell me the company name or symbol."

    action = extracted.get("action", "add")
    results = []

    for stock in extracted["stocks"]:
        symbol = normalize_symbol(stock.get("symbol", ""))
        name = stock.get("name", symbol)

        if action == "remove":
            await db.execute(
                update(StockWatchlist)
                .where(
                    StockWatchlist.user_id == user_id,
                    StockWatchlist.symbol == symbol,
                )
                .values(is_active=False)
            )
            results.append(f"Removed {name} from watchlist")
        else:
            # Check if already exists
            existing = await db.execute(
                select(StockWatchlist).where(
                    StockWatchlist.user_id == user_id,
                    StockWatchlist.symbol == symbol,
                )
            )
            item = existing.scalar_one_or_none()

            target_high = extracted.get("target_high")
            target_low = extracted.get("target_low")

            if item:
                item.is_active = True
                if target_high:
                    item.target_high = target_high
                if target_low:
                    item.target_low = target_low
                results.append(f"Updated {name} on watchlist")
            else:
                price_data = await get_price(symbol)
                db.add(
                    StockWatchlist(
                        user_id=user_id,
                        symbol=symbol,
                        market="NSE" if ".NS" in symbol else "OTHER",
                        target_high=target_high,
                        target_low=target_low,
                        last_price=price_data.get("price"),
                        last_checked=datetime.utcnow() if price_data else None,
                    )
                )
                price_str = f" (currently \u20b9{price_data['price']:,.1f})" if price_data.get("price") else ""
                alert_str = ""
                if target_high:
                    alert_str += f" | Alert above \u20b9{target_high:,.0f}"
                if target_low:
                    alert_str += f" | Alert below \u20b9{target_low:,.0f}"
                results.append(f"Added {name}{price_str}{alert_str}")

    await db.commit()
    return "\n".join(results) if results else "Done!"


async def get_watchlist_brief(db: AsyncSession, user_id: str) -> str:
    """Get current prices for all watched stocks."""
    result = await db.execute(
        select(StockWatchlist).where(
            StockWatchlist.user_id == user_id, StockWatchlist.is_active == True
        )
    )
    items = result.scalars().all()

    if not items:
        return "Your watchlist is empty. Tell me which stocks to watch!"

    lines = ["\ud83d\udcc8 *Your Stocks*"]

    for item in items:
        price_data = await get_price(item.symbol)
        if price_data.get("price"):
            price = price_data["price"]
            prev = price_data.get("prev_close", price)
            change = price - prev
            pct = (change / prev * 100) if prev else 0
            arrow = "\u2191" if change >= 0 else "\u2193"
            name = price_data.get("name", item.symbol)
            lines.append(
                f"{name}: \u20b9{price:,.1f} {arrow}{abs(pct):.1f}%"
            )

            # Update last price
            item.last_price = price
            item.last_checked = datetime.utcnow()
        else:
            lines.append(f"{item.symbol}: Unable to fetch")

    await db.commit()
    return "\n".join(lines)


async def check_alerts(db: AsyncSession, user_id: str) -> list[str]:
    """Check if any stocks hit alert targets."""
    result = await db.execute(
        select(StockWatchlist).where(
            StockWatchlist.user_id == user_id, StockWatchlist.is_active == True
        )
    )
    items = result.scalars().all()
    alerts = []

    for item in items:
        if not item.target_high and not item.target_low:
            continue

        price_data = await get_price(item.symbol)
        if not price_data.get("price"):
            continue

        price = price_data["price"]
        name = price_data.get("name", item.symbol)

        if item.target_high and price >= item.target_high:
            alerts.append(
                f"\ud83d\udea8 *Alert:* {name} crossed \u20b9{item.target_high:,.0f} \u2014 now at \u20b9{price:,.1f}"
            )

        if item.target_low and price <= item.target_low:
            alerts.append(
                f"\ud83d\udea8 *Alert:* {name} dropped below \u20b9{item.target_low:,.0f} \u2014 now at \u20b9{price:,.1f}"
            )

        item.last_price = price
        item.last_checked = datetime.utcnow()

    if alerts:
        await db.commit()

    return alerts
