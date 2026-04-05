"""
Prebuilt Skills Library — organized by vertical.

These are hand-coded, tested, reliable skills that activate instantly.
No generation. No research. Just works.

Structure:
- UNIVERSAL: every user gets these
- JEWELRY: activates when business_type contains jewel/gold/diamond/ornament
- HEALTH: activates when business_type contains doctor/clinic/health/fitness
- FINANCE: activates when business_type contains CA/accountant/finance/tax
- LEGAL: activates when business_type contains lawyer/legal/advocate
- BUSINESS: general business skills for all active users

Each skill has:
  name: unique identifier
  description: what it does (shown to user)
  keywords: trigger words for routing
  vertical: "universal" or specific vertical name
  execute: async function(query, context) -> str
"""

import logging
import httpx

logger = logging.getLogger("samva.prebuilt")


# ══════════════════════════════════════════════════════════════════
# UNIVERSAL — every user gets these
# ══════════════════════════════════════════════════════════════════

async def weather(query: str, context: dict = None) -> str:
    """Current weather for any city via wttr.in."""
    words = query.lower().replace("?", "").split()
    stop = {"what", "is", "the", "weather", "in", "of", "for", "today", "how",
            "mausam", "kya", "hai", "ka", "batao", "bolo", "check", "current"}
    city = " ".join(w for w in words if w not in stop and len(w) > 1) or "Mumbai"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://wttr.in/{city}?format=j1")
            if resp.status_code != 200:
                return ""
            data = resp.json()
            c = data["current_condition"][0]
            return (
                f"*{city.title()}* weather:\n"
                f"{c['weatherDesc'][0]['value']}, {c['temp_C']}°C "
                f"(feels like {c['FeelsLikeC']}°C)\n"
                f"Humidity: {c['humidity']}% | Wind: {c['windspeedKmph']} km/h"
            )
    except Exception:
        return ""


async def currency_convert(query: str, context: dict = None) -> str:
    """Convert any currency to any other with amounts."""
    import re
    q = query.upper().replace(",", "")

    nums = re.findall(r"[\d.]+", q)
    amount = float(nums[0]) if nums else 1.0

    NAMES = {"DOLLAR": "USD", "DOLLARS": "USD", "RUPEE": "INR", "RUPEES": "INR",
             "EURO": "EUR", "EUROS": "EUR", "POUND": "GBP", "POUNDS": "GBP",
             "YEN": "JPY", "DIRHAM": "AED", "DIRHAMS": "AED", "RIYAL": "SAR"}
    CODES = {"USD", "EUR", "GBP", "INR", "AED", "SAR", "JPY", "CAD", "AUD",
             "SGD", "CHF", "CNY", "KWD", "BHD", "OMR", "QAR", "THB", "MYR",
             "IDR", "PHP", "BDT", "NPR", "LKR", "PKR"}

    found = []
    for w in q.split():
        w = w.strip(".,?!")
        if w in CODES:
            found.append(w)
        elif w in NAMES:
            found.append(NAMES[w])

    if len(found) < 1:
        return ""
    if len(found) < 2:
        found.append("INR")

    from_cur, to_cur = found[0], found[1]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://open.er-api.com/v6/latest/{from_cur}")
            if resp.status_code != 200:
                return ""
            rate = resp.json()["rates"].get(to_cur)
            if not rate:
                return ""
            result = amount * rate
            return f"{amount:,.0f} {from_cur} = *{result:,.2f} {to_cur}*\n(1 {from_cur} = {rate:.4f} {to_cur})"
    except Exception:
        return ""


async def stock_price(query: str, context: dict = None) -> str:
    """Live stock prices — Indian (NSE/BSE) and international."""
    SYMBOLS = {
        "reliance": "RELIANCE.NS", "tcs": "TCS.NS", "hdfc": "HDFCBANK.NS",
        "infosys": "INFY.NS", "wipro": "WIPRO.NS", "icici": "ICICIBANK.NS",
        "sbi": "SBIN.NS", "kotak": "KOTAKBANK.NS", "bajaj": "BAJFINANCE.NS",
        "adani": "ADANIENT.NS", "titan": "TITAN.NS", "maruti": "MARUTI.NS",
        "hul": "HINDUNILVR.NS", "itc": "ITC.NS", "lt": "LT.NS",
        "nifty": "^NSEI", "nifty50": "^NSEI", "sensex": "^BSESN",
        "banknifty": "^NSEBANK",
        "apple": "AAPL", "google": "GOOGL", "tesla": "TSLA",
        "amazon": "AMZN", "microsoft": "MSFT",
    }
    words = query.lower().replace("?", "").replace("'s", "").split()
    stop = {"what", "is", "the", "of", "for", "how", "much", "today", "current",
            "live", "nse", "bse", "share", "price", "stock", "kya", "hai", "ka", "ki", "rate", "check"}
    terms = [w for w in words if w not in stop and len(w) > 1]

    symbol = None
    for t in terms:
        if t in SYMBOLS:
            symbol = SYMBOLS[t]
            break
    if not symbol and terms:
        symbol = terms[0].upper() + ".NS"
    if not symbol:
        return ""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
            )
            if resp.status_code != 200:
                return ""
            meta = resp.json()["chart"]["result"][0]["meta"]
            price = meta["regularMarketPrice"]
            prev = meta.get("chartPreviousClose", price)
            change = price - prev
            pct = (change / prev * 100) if prev else 0
            arrow = "\u2191" if change >= 0 else "\u2193"
            name = meta.get("shortName", symbol)
            return f"*{name}*\n\u20b9{price:,.2f} {arrow} \u20b9{abs(change):,.2f} ({abs(pct):.1f}%)"
    except Exception:
        return ""


async def dictionary_lookup(query: str, context: dict = None) -> str:
    """English word definition, pronunciation, examples."""
    words = query.lower().replace("?", "").split()
    stop = {"what", "does", "mean", "meaning", "of", "the", "word", "define",
            "definition", "matlab", "kya", "hai", "ka", "ki", "english"}
    term = None
    for w in words:
        if w not in stop and len(w) > 2:
            term = w
            break
    if not term:
        return ""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{term}")
            if resp.status_code != 200:
                return ""
            data = resp.json()[0]
            word = data["word"]
            phonetic = data.get("phonetic", "")
            meanings = []
            for m in data.get("meanings", [])[:2]:
                pos = m["partOfSpeech"]
                defn = m["definitions"][0]["definition"]
                example = m["definitions"][0].get("example", "")
                line = f"*{pos}*: {defn}"
                if example:
                    line += f'\n  _"{example}"_'
                meanings.append(line)
            result = f"*{word}* {phonetic}\n\n" + "\n\n".join(meanings)
            return result
    except Exception:
        return ""


async def news_search(query: str, context: dict = None) -> str:
    """Search latest news by keyword. Uses free news APIs."""
    words = query.lower().replace("?", "").split()
    stop = {"news", "latest", "about", "on", "what", "is", "the", "happening",
            "kya", "hai", "batao", "tell", "me", "show", "today"}
    terms = [w for w in words if w not in stop and len(w) > 2]
    search = " ".join(terms) if terms else "India"

    try:
        # Use Google News RSS as free alternative (no API key needed)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://news.google.com/rss/search?q={search}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            if resp.status_code != 200:
                return ""
            # Parse RSS XML simply
            import re
            items = re.findall(r"<title>(.*?)</title>", resp.text)
            # Skip first item (feed title)
            headlines = items[1:6] if len(items) > 1 else []
            if not headlines:
                return ""
            lines = [f"*Latest news: {search}*\n"]
            for i, h in enumerate(headlines, 1):
                # Clean HTML entities
                h = h.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
                lines.append(f"{i}. {h}")
            return "\n".join(lines)
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════
# JEWELRY VERTICAL
# ══════════════════════════════════════════════════════════════════

async def gemstone_info(query: str, context: dict = None) -> str:
    """Gemstone identification and grading reference."""
    GEMS = {
        "diamond": (
            "*Diamond*\nHardness: 10 (Mohs)\n"
            "4Cs: Cut, Clarity, Color, Carat\n"
            "Clarity: FL > IF > VVS1 > VVS2 > VS1 > VS2 > SI1 > SI2 > I1\n"
            "Color: D(best) E F G H I J...Z\n"
            "Cut: Excellent > Very Good > Good > Fair\n"
            "Price: \u20b930K-5L/ct for VS-SI quality"
        ),
        "ruby": "*Ruby*\nHardness: 9. Red corundum.\nBurmese (pigeon blood) most valuable.\nPrice: \u20b910K-2L/ct depending on origin.",
        "sapphire": "*Sapphire*\nHardness: 9. Blue corundum.\nKashmir most valuable, Ceylon popular.\nPrice: \u20b95K-1L/ct.",
        "emerald": "*Emerald*\nHardness: 7.5. Green beryl.\nColombian most prized. Inclusions normal.\nPrice: \u20b95K-3L/ct.",
        "pearl": "*Pearl*\nOrganic gem. Akoya (Japanese) classic.\nSouth Sea largest. Tahitian (black).\nPrice: \u20b9500-50K per pearl.",
        "tanzanite": "*Tanzanite*\nOnly found in Tanzania.\nTrichroic. Heat treated for blue.\nPrice: \u20b93K-30K/ct.",
        "opal": "*Opal*\nPlay of color. Australian black most valuable.\nHardness 5.5-6.5 (fragile).\nPrice: \u20b9500-50K/ct.",
    }
    q = query.lower()
    for gem, info in GEMS.items():
        if gem in q:
            return info

    if any(w in q for w in ["clarity", "grade", "4c", "carat", "cut", "color"]):
        return GEMS["diamond"]

    return "*Gemstone Guide*\nI know: diamond, ruby, sapphire, emerald, pearl, tanzanite, opal.\nWhich stone?"


async def jewelry_pricing(query: str, context: dict = None) -> str:
    """Calculate full jewelry price using the pricing engine — live gold, labor, GST, loss."""
    import re
    from .jewelry_pricing_engine import calculate_full_jewelry_cost
    q = query.lower()

    # Extract weight in grams
    weight_match = re.search(r"([\d.]+)\s*(?:gram|gm|g\b)", q)
    weight = float(weight_match.group(1)) if weight_match else None

    if not weight:
        return ""

    # Extract karat
    karat = "22K"  # default
    karat_match = re.search(r"(\d{1,2})\s*[kK]", q)
    if karat_match:
        karat = f"{karat_match.group(1)}K"

    # Extract jewelry type
    jewelry_type = "ring"  # default
    TYPE_MAP = {
        "ring": "ring", "pendant": "pendant", "earring": "earring",
        "bangle": "bangle", "bracelet": "bracelet", "chain": "pendant",
        "necklace": "pendant", "mangalsutra": "pendant",
    }
    for kw, jtype in TYPE_MAP.items():
        if kw in q:
            jewelry_type = jtype
            break

    # Extract metal
    metal = "gold"
    if "silver" in q or "chandi" in q:
        metal = "silver"

    # Extract finishing hints
    finishing = {
        "rhodium": "rhodium" in q,
        "two_tone": "two tone" in q or "two-tone" in q,
        "special_finish": "special finish" in q or "matte" in q or "sandblast" in q,
        "stamping": True,
        "solder": True,
    }

    # Get stone_grid from image context if available
    stone_grid = None
    if context and context.get("gemlens_bom"):
        stone_grid = context["gemlens_bom"].get("stone_grid", [])

    try:
        # Use db and user_id from context if available, else pass None
        db = context.get("db") if context else None
        user_id = context.get("user_id") if context else None

        result = await calculate_full_jewelry_cost(
            db=db,
            user_id=user_id,
            weight_grams=weight,
            karat=karat,
            jewelry_type=jewelry_type,
            metal=metal,
            stone_grid=stone_grid,
            model="setting_charges",
            finishing=finishing,
        )

        return result.get("formatted", "")
    except Exception as e:
        logger.error(f"jewelry_pricing error: {e}", exc_info=True)
        return ""


async def gemlens_analyze(query: str, context: dict = None) -> str:
    """Analyze jewelry photo via GemLens — BOM, stone ID, metal analysis."""
    from ..config import settings
    if not settings.gemlens_api_key:
        return ""

    image_b64 = context.get("image_base64") if context else None
    if not image_b64:
        return "__NEED_IMAGE__"

    if not image_b64.startswith("data:"):
        image_b64 = f"data:image/jpeg;base64,{image_b64}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://uwmtnghafmckvavmwbfk.supabase.co/functions/v1/api-analyze",
                json={"image": image_b64, "include_bom": True},
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.gemlens_api_key,
                },
            )
            result = resp.json()

        if not result.get("success"):
            return ""

        bom = result.get("bom", {})
        metal_analysis = result.get("metal_analysis", {})
        item = bom.get("item_description") or bom.get("item_name", "Jewelry piece")
        bom_metal = bom.get("metal", {}) or bom.get("metal_info", {})
        stone_grid = bom.get("stone_grid", []) or bom.get("stone_inventory", [])
        totals = bom.get("totals", {})

        karat = bom_metal.get("karat") or metal_analysis.get("karat", "")
        metal_type = bom_metal.get("type") or metal_analysis.get("metal_type", "")
        weight = bom_metal.get("weight_grams") or metal_analysis.get("estimated_weight_grams", "")

        lines = [f"*{item}*\n"]
        if metal_type or karat:
            lines.append(f"Metal: {metal_type} {karat}")
        if weight:
            lines.append(f"Weight: ~{weight}g")
        if totals:
            lines.append(f"Stones: {totals.get('total_stone_count', len(stone_grid))} pcs, {totals.get('total_carat_weight', '')} ct")
        for s in stone_grid[:5]:
            lines.append(
                f"\u25b8 {s.get('stone_type', '?')} {s.get('shape', '')} "
                f"{s.get('weight_per_piece', s.get('estimated_carat', ''))} ct "
                f"x{s.get('quantity', 1)}"
            )
        lines.append("\n*BOM PDF chahiye?* Bolo 'bom pdf'\n*Enhance?* Bolo 'enhance'\n*Ad?* Bolo 'make ad'")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"GemLens error: {e}")
        return ""


async def gemlens_bom_pdf(query: str, context: dict = None) -> str:
    """Generate BOM PDF from jewelry image via GemLens + live gold pricing."""
    from ..config import settings
    if not settings.gemlens_api_key:
        return ""

    image_b64 = context.get("image_base64") if context else None
    if not image_b64:
        return "__NEED_IMAGE__"

    if not image_b64.startswith("data:"):
        image_b64 = f"data:image/jpeg;base64,{image_b64}"

    try:
        # Step 1: Get BOM from GemLens
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://uwmtnghafmckvavmwbfk.supabase.co/functions/v1/api-analyze",
                json={"image": image_b64, "include_bom": True},
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.gemlens_api_key,
                },
            )
            result = resp.json()

        if not result.get("success"):
            logger.warning(f"GemLens BOM failed: {result}")
            return ""

        bom = result.get("bom", {})
        # GemLens field names (match JewelClaw): item_description, metal, stone_grid
        item_name = bom.get("item_description") or bom.get("item_name", "Jewelry Item")
        bom_metal = bom.get("metal", {}) or bom.get("metal_info", {})
        stone_grid = bom.get("stone_grid", []) or bom.get("stone_inventory", [])
        metal_analysis = result.get("metal_analysis", {})
        totals = bom.get("totals", {})

        # Merge metal data from BOM and metal_analysis
        karat = bom_metal.get("karat") or metal_analysis.get("karat", "22K")
        metal_type = bom_metal.get("type") or metal_analysis.get("metal_type", "Gold")
        metal_color = bom_metal.get("color") or metal_analysis.get("color", "Yellow")
        weight_grams = float(bom_metal.get("weight_grams") or metal_analysis.get("estimated_weight_grams", 0) or 0)

        logger.info(f"GemLens BOM: {item_name}, metal={metal_type} {karat}, weight={weight_grams}g, stones={len(stone_grid)}")

        # Step 2: Get live gold rate
        gold_rate = 0
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                gold_resp = await client.get("https://api.gold-api.com/price/XAU")
                usd_resp = await client.get("https://open.er-api.com/v6/latest/USD")
                if gold_resp.status_code == 200 and usd_resp.status_code == 200:
                    gold_usd = gold_resp.json().get("price", 0)
                    usd_inr = usd_resp.json().get("rates", {}).get("INR", 83.5)
                    gold_24k = (gold_usd * usd_inr * 1.069) / 31.1035
                    purity = {"24K": 1.0, "22K": 0.916, "18K": 0.75, "14K": 0.585}
                    gold_rate = gold_24k * purity.get(karat, 0.916)
        except Exception:
            pass

        # Step 3: Full pricing via pricing engine
        from .jewelry_pricing_engine import calculate_full_jewelry_cost

        # Detect jewelry type from item name
        jtype = "ring"
        item_lower = item_name.lower()
        for kw, jt in [("pendant", "pendant"), ("earring", "earring"), ("bangle", "bangle"),
                        ("bracelet", "bracelet"), ("chain", "pendant"), ("necklace", "pendant"),
                        ("ring", "ring")]:
            if kw in item_lower:
                jtype = jt
                break

        metal_key = "gold" if "gold" in metal_type.lower() or "gold" in karat.lower() else "silver"

        # Use db and user_id from context for user memory lookup
        db = context.get("db") if context else None
        user_id = context.get("user_id") if context else None

        pricing = await calculate_full_jewelry_cost(
            db=db,
            user_id=user_id,
            weight_grams=weight_grams,
            karat=karat,
            jewelry_type=jtype,
            metal=metal_key,
            stone_grid=stone_grid,
            model="setting_charges",
        )

        making_pct = pricing.get("making_pct", 12)

        # Step 4: Generate PDF using full GemLens data + pricing breakdown
        from .bom_pdf import generate_bom_pdf
        pdf_b64 = generate_bom_pdf(
            item_name=item_name,
            metal_info={"type": metal_type, "karat": karat, "color": metal_color},
            stones=stone_grid,
            gold_rate_per_gram=pricing.get("gold_rate_per_gram", gold_rate),
            making_charge_pct=making_pct,
            weight_grams=weight_grams,
            totals=totals,
            pricing=pricing,
        )

        if pdf_b64:
            clean_name = item_name.replace(' ', '-')[:20]
            # Sam acknowledges what she's doing
            logger.info(f"BOM PDF ready: {item_name}, {karat}, {weight_grams}g, rate={gold_rate:.0f}/gm")
            return f"__PDF__{pdf_b64}__FILENAME__BOM-{clean_name}.pdf"

        return ""
    except Exception as e:
        logger.error(f"BOM PDF error: {e}", exc_info=True)
        return ""


async def jewelcraft_analyze(query: str, context: dict = None) -> str:
    """Analyze jewelry image with JewelCraft — identify metals, stones, settings, era."""
    from ..config import settings
    if not settings.jewelcraft_api_key:
        return ""

    image_b64 = context.get("image_base64") if context else None
    if not image_b64:
        return "__NEED_IMAGE__"

    if not image_b64.startswith("data:"):
        image_b64 = f"data:image/jpeg;base64,{image_b64}"

    try:
        base = settings.jewelcraft_base_url.rstrip("/")
        data = {"image": image_b64}
        if query and len(query) > 5:
            data["prompt"] = query

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/v1-analyze",
                json=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.jewelcraft_api_key,
                },
            )
            result = resp.json()

        analysis = result.get("analysis", "")
        if not analysis:
            return ""

        return f"*Jewelry Analysis:*\n{analysis}\n\nRender chahiye? Ad banana hai? Price nikalu?"
    except Exception as e:
        logger.error(f"JewelCraft analyze error: {e}")
        return ""


async def jewelcraft_render(query: str, context: dict = None) -> str:
    """Render a jewelry design from text description via JewelCraft."""
    from ..config import settings
    if not settings.jewelcraft_api_key:
        return ""

    # Use image as reference if available
    image_b64 = context.get("image_base64") if context else None

    try:
        data = {"prompt": query, "model": "standard"}
        if image_b64:
            if not image_b64.startswith("data:"):
                image_b64 = f"data:image/jpeg;base64,{image_b64}"
            data["reference_image"] = image_b64

        timeout = 90.0 if image_b64 else 30.0
        base = settings.jewelcraft_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/v1-render",
                json=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.jewelcraft_api_key,
                },
            )
            result = resp.json()

        if result.get("error"):
            return ""

        # Return signal with image data for bridge to send as image
        return f"__IMAGE__{result.get('image', '')}"
    except Exception as e:
        logger.error(f"JewelCraft render error: {e}")
        return ""


async def jewelcraft_enhance(query: str, context: dict = None) -> str:
    """Enhance jewelry photo to catalog quality via JewelCraft."""
    from ..config import settings
    if not settings.jewelcraft_api_key:
        return ""

    image_b64 = context.get("image_base64") if context else None
    if not image_b64:
        return "__NEED_IMAGE__"

    if not image_b64.startswith("data:"):
        image_b64 = f"data:image/jpeg;base64,{image_b64}"

    # Detect background from query
    bg = "velvet"
    q = query.lower()
    if "white" in q or "safed" in q:
        bg = "white"
    elif "marble" in q:
        bg = "marble"
    elif "lifestyle" in q:
        bg = "lifestyle"

    try:
        base = settings.jewelcraft_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/v1-enhance",
                json={"image": image_b64, "background": bg, "style": "studio"},
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.jewelcraft_api_key,
                },
            )
            result = resp.json()

        if result.get("error"):
            return ""

        return f"__IMAGE__{result.get('image', '')}"
    except Exception as e:
        logger.error(f"JewelCraft enhance error: {e}")
        return ""


async def jewelcraft_ad(query: str, context: dict = None) -> str:
    """Create Instagram/WhatsApp marketing ad from jewelry photo via JewelCraft."""
    from ..config import settings
    if not settings.jewelcraft_api_key:
        return ""

    image_b64 = context.get("image_base64") if context else None
    if not image_b64:
        return "__NEED_IMAGE__"

    if not image_b64.startswith("data:"):
        image_b64 = f"data:image/jpeg;base64,{image_b64}"

    # Detect platform from query
    platform = "instagram_post"
    q = query.lower()
    if "whatsapp" in q or "status" in q:
        platform = "whatsapp_status"
    elif "story" in q or "reel" in q:
        platform = "instagram_story"
    elif "facebook" in q:
        platform = "facebook_feed"

    # Get brand name from user memory if available
    brand = None
    if context and context.get("user_memory"):
        for mem in context["user_memory"]:
            if "brand" in mem.get("key", "").lower() or "shop" in mem.get("key", "").lower():
                brand = mem["value"]
                break

    try:
        data = {"image": image_b64, "format": "image", "platform": platform}
        if brand:
            data["brand_name"] = brand

        base = settings.jewelcraft_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/v1-ad",
                json=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.jewelcraft_api_key,
                },
            )
            result = resp.json()

        if result.get("error"):
            return ""

        return f"__IMAGE__{result.get('image', '')}"
    except Exception as e:
        logger.error(f"JewelCraft ad error: {e}")
        return ""


async def jewelcraft_vto(query: str, context: dict = None) -> str:
    """Virtual try-on — show jewelry on a person via JewelCraft."""
    from ..config import settings
    if not settings.jewelcraft_api_key:
        return ""

    image_b64 = context.get("image_base64") if context else None
    if not image_b64:
        return "__NEED_IMAGE__"

    if not image_b64.startswith("data:"):
        image_b64 = f"data:image/jpeg;base64,{image_b64}"

    try:
        base = settings.jewelcraft_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/v1-tryon",
                json={"jewelry_image": image_b64},
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.jewelcraft_api_key,
                },
            )
            result = resp.json()

        # Handle async polling if needed
        job_id = result.get("job_id")
        if job_id:
            import asyncio
            for _ in range(30):
                await asyncio.sleep(10)
                async with httpx.AsyncClient(timeout=15.0) as client:
                    status_resp = await client.get(
                        f"{base}/v1-tryon-status",
                        params={"job_id": job_id},
                        headers={"x-api-key": settings.jewelcraft_api_key},
                    )
                    status = status_resp.json()
                    if status.get("status") == "completed":
                        return f"__IMAGE__{status.get('image', '')}"
                    elif status.get("status") == "failed":
                        return ""
            return ""

        if result.get("image"):
            return f"__IMAGE__{result.get('image', '')}"
        return ""
    except Exception as e:
        logger.error(f"JewelCraft VTO error: {e}")
        return ""


# ══════════════════════════════════════════════════════════════════
# HEALTH VERTICAL
# ══════════════════════════════════════════════════════════════════

async def drug_interactions(query: str, context: dict = None) -> str:
    """Check drug interactions via FDA OpenFDA database."""
    words = query.lower().replace("?", "").replace("!", "").split()
    stop = {"what", "are", "the", "drug", "interaction", "interactions", "for", "of",
            "between", "check", "info", "about", "with", "can", "i", "take", "is",
            "it", "safe", "to", "me", "tell", "please", "fda", "and", "medicine",
            "medication", "prescribe", "dava", "dawai"}
    drugs = [w for w in words if w not in stop and len(w) > 2]
    if not drugs:
        return ""

    results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for drug in drugs[:2]:
            try:
                resp = await client.get(
                    f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{drug}&limit=1"
                )
                if resp.status_code != 200:
                    continue
                r = resp.json().get("results", [{}])[0]
                name = drug.upper()
                interactions = r.get("drug_interactions", ["No interaction data"])[0][:300]
                warnings = r.get("warnings", [""])[0][:200]
                text = f"*{name}* (FDA):\nInteractions: {interactions}"
                if warnings:
                    text += f"\nWarnings: {warnings}"
                results.append(text)
            except Exception:
                continue

    return "\n\n".join(results) if results else ""


async def calorie_lookup(query: str, context: dict = None) -> str:
    """Estimate calories from food description. Uses Gemini knowledge (no API key needed)."""
    # This is a pure-LLM skill — the orchestrator will call Gemini with a nutrition prompt
    # We return empty to signal the orchestrator to handle it with a specialized prompt
    return "__LLM_NUTRITION__"


async def medical_image_analysis(query: str, context: dict = None) -> str:
    """Analyze medical images (Xray, scan). Needs Gemini Pro Vision."""
    # Signal the orchestrator to use Gemini Pro Vision with medical prompt
    return "__LLM_MEDICAL_VISION__"


# ══════════════════════════════════════════════════════════════════
# FINANCE VERTICAL
# ══════════════════════════════════════════════════════════════════

async def gst_rate(query: str, context: dict = None) -> str:
    """Indian GST rate lookup by product/service category."""
    GST_RATES = {
        # Common categories
        "gold": ("Gold, silver, diamond jewelry", "3%"),
        "jewelry": ("Gold, silver, diamond jewelry", "3%"),
        "diamond": ("Cut and polished diamonds", "1.5%"),
        "restaurant": ("Restaurant services (non-AC)", "5%"),
        "hotel": ("Hotel rooms (tariff based)", "5% / 12% / 18% / 28%"),
        "mobile": ("Mobile phones", "12%"),
        "car": ("Cars (based on type)", "28% + cess"),
        "cement": ("Cement", "28%"),
        "software": ("IT services, SaaS", "18%"),
        "consulting": ("Consulting, professional services", "18%"),
        "textile": ("Textiles (up to 1000)", "5%"),
        "medicine": ("Medicines, medical devices", "5% / 12%"),
        "food": ("Packaged food items", "5% / 12% / 18%"),
        "electronics": ("Electronics, appliances", "18%"),
        "insurance": ("Insurance premium", "18%"),
        "banking": ("Banking, financial services", "18%"),
        "transport": ("Goods transport", "5% / 12%"),
        "education": ("Educational services", "Exempt"),
        "health": ("Healthcare services", "Exempt"),
        "agriculture": ("Agricultural produce (unprocessed)", "Exempt"),
    }
    q = query.lower()
    for key, (desc, rate) in GST_RATES.items():
        if key in q:
            return f"*GST Rate*\n{desc}\nRate: *{rate}*\n\n_Verify at cbic-gst.gov.in for exact HSN/SAC code._"

    return ""


async def invoice_draft(query: str, context: dict = None) -> str:
    """Signal orchestrator to draft an invoice using LLM."""
    return "__LLM_INVOICE__"


# ══════════════════════════════════════════════════════════════════
# LEGAL VERTICAL
# ══════════════════════════════════════════════════════════════════

async def indian_law_search(query: str, context: dict = None) -> str:
    """Search Indian legal cases and bare acts via Indian Kanoon."""
    words = query.lower().replace("?", "").split()
    stop = {"what", "is", "the", "law", "about", "case", "section", "act",
            "find", "search", "legal", "kanoon", "kya", "hai"}
    terms = [w for w in words if w not in stop and len(w) > 2]
    search = " ".join(terms) if terms else ""
    if not search:
        return ""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Indian Kanoon has a public search page we can scrape
            resp = await client.get(
                f"https://indiankanoon.org/search/?formInput={search}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return ""
            import re
            # Extract case titles from results
            titles = re.findall(r'class="result_title"[^>]*>(.*?)</a>', resp.text)
            if not titles:
                return ""
            lines = [f"*Indian Kanoon: {search}*\n"]
            for i, t in enumerate(titles[:5], 1):
                t = re.sub(r'<[^>]+>', '', t).strip()
                lines.append(f"{i}. {t}")
            lines.append(f"\nFull results: indiankanoon.org/search/?formInput={search}")
            return "\n".join(lines)
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════
# ASTROLOGY VERTICAL — Vedic/Jyotish (universal for Indian users)
# Uses VedAstro (free, MIT licensed, no auth needed)
# ══════════════════════════════════════════════════════════════════

VEDASTRO_BASE = "https://api.vedastro.org/api"

# Rashi names for reference
RASHI_MAP = {
    "mesh": "Aries", "aries": "Aries", "vrishabh": "Taurus", "taurus": "Taurus",
    "mithun": "Gemini", "gemini": "Gemini", "kark": "Cancer", "cancer": "Cancer",
    "simha": "Leo", "singh": "Leo", "leo": "Leo", "kanya": "Virgo", "virgo": "Virgo",
    "tula": "Libra", "libra": "Libra", "vrishchik": "Scorpio", "scorpio": "Scorpio",
    "dhanu": "Sagittarius", "sagittarius": "Sagittarius",
    "makar": "Capricorn", "capricorn": "Capricorn",
    "kumbh": "Aquarius", "aquarius": "Aquarius",
    "meen": "Pisces", "pisces": "Pisces",
}


async def daily_panchang(query: str, context: dict = None) -> str:
    """Today's Panchang — tithi, nakshatra, yoga, karana, shubh muhurat."""
    from datetime import datetime
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    date_str = now.strftime("%d/%m/%Y")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{VEDASTRO_BASE}/Calculate/PanchangaAtTime/Location/Mumbai/Time/{date_str}/00:00/+05:30"
            )
            if resp.status_code != 200:
                # Fallback: basic panchang from Gemini knowledge
                return "__LLM_PANCHANG__"
            data = resp.json()

        # Parse VedAstro response
        payload = data.get("Payload", {}).get("PanchangaAtTime", {})
        if not payload:
            return "__LLM_PANCHANG__"

        tithi = payload.get("Tithi", {}).get("Name", "?")
        nakshatra = payload.get("Nakshatra", {}).get("Name", "?")
        yoga = payload.get("NithyaYoga", {}).get("Name", "?")
        karana = payload.get("Karana", {}).get("Name", "?")
        day = now.strftime("%A")

        lines = [
            f"*Aaj ka Panchang* -- {now.strftime('%d %b %Y')} ({day})\n",
            f"Tithi: *{tithi}*",
            f"Nakshatra: *{nakshatra}*",
            f"Yoga: *{yoga}*",
            f"Karana: *{karana}*",
        ]

        # Add sunrise/sunset if available
        sunrise = payload.get("Sunrise", "")
        sunset = payload.get("Sunset", "")
        if sunrise:
            lines.append(f"\nSunrise: {sunrise}")
        if sunset:
            lines.append(f"Sunset: {sunset}")

        lines.append("\n_Shubh din ho!_")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Panchang error: {e}")
        return "__LLM_PANCHANG__"


async def kundli_generate(query: str, context: dict = None) -> str:
    """Generate kundli from birth details. Asks for DOB, time, place if not provided."""
    import re

    q = query.lower()

    # Try to extract date, time, place from query
    # Patterns: "15 march 1990 2:30pm mumbai", "1990-03-15 14:30 delhi"
    date_match = re.search(r"(\d{1,2})[/\-\s](\d{1,2}|\w+)[/\-\s](\d{4})", q)
    time_match = re.search(r"(\d{1,2})[:\.](\d{2})\s*(am|pm)?", q)

    if not date_match:
        return (
            "Kundli ke liye mujhe chahiye:\n"
            "1. *Janam tithi* (date of birth) — e.g., 15 March 1990\n"
            "2. *Janam samay* (time of birth) — e.g., 2:30 PM\n"
            "3. *Janam sthan* (place of birth) — e.g., Mumbai\n\n"
            "Sab ek message mein bhej do!"
        )

    # Extract parts
    day = date_match.group(1)
    month_raw = date_match.group(2)
    year = date_match.group(3)

    # Convert month name to number if needed
    MONTHS = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
              "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
              "january": "01", "february": "02", "march": "03", "april": "04",
              "june": "06", "july": "07", "august": "08", "september": "09",
              "october": "10", "november": "11", "december": "12"}
    month = MONTHS.get(month_raw.lower(), month_raw.zfill(2))

    hour = "12"
    minute = "00"
    if time_match:
        h = int(time_match.group(1))
        minute = time_match.group(2)
        ampm = time_match.group(3) or ""
        if ampm.lower() == "pm" and h < 12:
            h += 12
        elif ampm.lower() == "am" and h == 12:
            h = 0
        hour = str(h).zfill(2)

    # Extract city (last meaningful word)
    stop = {"kundli", "kundali", "janam", "patri", "patrika", "birth", "chart",
            "generate", "banao", "meri", "my", "ka", "ki", "ke", "am", "pm",
            day, month_raw, year, time_match.group(0) if time_match else ""}
    words = [w for w in q.split() if w not in stop and len(w) > 2 and not w.isdigit()]
    city = words[-1].title() if words else "Mumbai"

    date_formatted = f"{day}/{month}/{year}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{VEDASTRO_BASE}/Calculate/AllPlanetDataAtTime/Location/{city}/Time/{date_formatted}/{hour}:{minute}/+05:30"
            )
            if resp.status_code != 200:
                return f"Kundli generation mein dikkat aa rahi hai. Baad mein try karo."

            data = resp.json()
            planets = data.get("Payload", {}).get("AllPlanetDataAtTime", [])

        if not planets:
            return "__LLM_KUNDLI__"

        lines = [f"*Kundli* -- {day}/{month}/{year}, {hour}:{minute}, {city}\n"]

        for planet_data in planets:
            name = planet_data.get("Name", "?")
            sign = planet_data.get("PlanetZodiacSign", {}).get("Name", "?")
            house = planet_data.get("HouseNumber", "?")
            nakshatra = planet_data.get("PlanetConstellation", {}).get("Name", "?")
            lines.append(f"{name}: *{sign}* (House {house}, {nakshatra})")

        lines.append("\nDasha, dosha, ya compatibility check chahiye? Bolo!")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Kundli error: {e}")
        return "__LLM_KUNDLI__"


async def rashi_horoscope(query: str, context: dict = None) -> str:
    """Daily horoscope by rashi — uses LLM with planetary context."""
    q = query.lower()
    rashi = None
    for key, value in RASHI_MAP.items():
        if key in q:
            rashi = value
            break

    if not rashi:
        return (
            "Aapki rashi batao:\n"
            "Mesh | Vrishabh | Mithun | Kark | Simha | Kanya\n"
            "Tula | Vrishchik | Dhanu | Makar | Kumbh | Meen\n\n"
            "_Ya English mein: Aries, Taurus, Gemini..._"
        )

    # Signal orchestrator to use LLM with astrology prompt + planetary positions
    return f"__LLM_HOROSCOPE__{rashi}"


async def compatibility_match(query: str, context: dict = None) -> str:
    """Gun Milan / Kundli matching for marriage compatibility."""
    # This needs both birth details — complex interaction
    return (
        "Gun Milan ke liye dono ki details chahiye:\n\n"
        "*Person 1:*\nJanam tithi, samay, sthan\n\n"
        "*Person 2:*\nJanam tithi, samay, sthan\n\n"
        "Dono ki details bhejo — main 36 gun mein se kitne milte hain bata dungi!"
    )


async def muhurat_check(query: str, context: dict = None) -> str:
    """Check auspicious timing (muhurat) for events."""
    q = query.lower()

    # Common events people ask muhurat for
    events = {
        "shadi": "Vivah (Marriage)", "vivah": "Vivah (Marriage)", "marriage": "Vivah (Marriage)", "wedding": "Vivah (Marriage)",
        "griha pravesh": "Griha Pravesh", "house": "Griha Pravesh", "ghar": "Griha Pravesh",
        "mundan": "Mundan (Head Shaving)", "namkaran": "Namkaran (Naming)", "naming": "Namkaran (Naming)",
        "business": "Vyapar Arambh", "dukan": "Vyapar Arambh", "shop": "Vyapar Arambh",
        "travel": "Yatra", "yatra": "Yatra", "safar": "Yatra",
        "car": "Vahan (Vehicle Purchase)", "vehicle": "Vahan (Vehicle Purchase)", "gaadi": "Vahan (Vehicle Purchase)",
        "property": "Bhoomi (Property)", "zameen": "Bhoomi (Property)", "plot": "Bhoomi (Property)",
    }

    event = None
    for key, value in events.items():
        if key in q:
            event = value
            break

    if event:
        return f"__LLM_MUHURAT__{event}"

    return (
        "Kis kaam ka muhurat chahiye?\n\n"
        "Shadi | Griha Pravesh | Mundan | Namkaran\n"
        "Business | Travel | Vehicle | Property\n\n"
        "_Batao, main shubh din aur samay dhundh deti hoon!_"
    )


async def vastu_tips(query: str, context: dict = None) -> str:
    """Vastu Shastra tips and recommendations."""
    q = query.lower()

    VASTU = {
        "bedroom": (
            "*Vastu — Bedroom*\n"
            "Direction: Southwest is best for master bedroom\n"
            "Bed: Head towards South or East while sleeping\n"
            "Mirror: Never place mirror facing the bed\n"
            "Colors: Light pink, blue, or green for walls\n"
            "Electronics: Avoid TV/laptop in bedroom — disturbs sleep energy"
        ),
        "kitchen": (
            "*Vastu — Kitchen*\n"
            "Direction: Southeast corner (Agni kon) is ideal\n"
            "Stove: Face East while cooking\n"
            "Sink: North or Northeast — water and fire should not be adjacent\n"
            "Fridge: Southwest or West wall\n"
            "Colors: Yellow, orange, or red accents"
        ),
        "office": (
            "*Vastu — Office/Workspace*\n"
            "Desk: Face North or East while working\n"
            "Safe/Locker: Southwest corner, opens towards North\n"
            "Entrance: North or East facing is auspicious\n"
            "Boss cabin: Southwest corner of office\n"
            "Plants: Bamboo or money plant in Southeast"
        ),
        "entrance": (
            "*Vastu — Main Entrance*\n"
            "Best: North or East facing door\n"
            "Avoid: South-West facing entrance\n"
            "Threshold: Should be slightly elevated\n"
            "Decor: Toran, rangoli, or nameplate on right side\n"
            "Shoes: Keep shoe rack outside or in West direction"
        ),
        "pooja": (
            "*Vastu — Pooja Room*\n"
            "Direction: Northeast corner (Ishan kon) is ideal\n"
            "Face: Face East or North while praying\n"
            "Idols: Should not face each other or the South wall\n"
            "Height: Idols at chest level, not on ground\n"
            "Lamp: Light diya in Southeast corner of pooja room"
        ),
        "bathroom": (
            "*Vastu — Bathroom/Toilet*\n"
            "Direction: Northwest or West is best\n"
            "Avoid: Northeast corner (sacred direction)\n"
            "Toilet seat: Face North or South, never East\n"
            "Drainage: Water should flow North or East\n"
            "Ventilation: Window in East or North wall"
        ),
    }

    for key, tips in VASTU.items():
        if key in q:
            return tips

    # Check for general vastu query
    if any(w in q for w in ["direction", "disha", "konsa", "facing", "placement"]):
        return "__LLM_VASTU__"

    return (
        "*Vastu Guide*\nKis room ka vastu chahiye?\n\n"
        "Bedroom | Kitchen | Office | Entrance\n"
        "Pooja Room | Bathroom\n\n"
        "_Ya koi specific sawal pucho — direction, placement, colors_"
    )


async def graha_sthiti(query: str, context: dict = None) -> str:
    """Current planetary positions — graha sthiti."""
    from datetime import datetime
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{VEDASTRO_BASE}/Calculate/AllPlanetDataAtTime/Location/Mumbai/Time/{date_str}/{time_str}/+05:30"
            )
            if resp.status_code != 200:
                return "__LLM_PLANETS__"

            data = resp.json()
            planets = data.get("Payload", {}).get("AllPlanetDataAtTime", [])

        if not planets:
            return "__LLM_PLANETS__"

        lines = [f"*Graha Sthiti* -- {now.strftime('%d %b %Y, %I:%M %p')} IST\n"]
        for p in planets:
            name = p.get("Name", "?")
            sign = p.get("PlanetZodiacSign", {}).get("Name", "?")
            retro = " (R)" if p.get("IsRetrograde") else ""
            lines.append(f"{name}: *{sign}*{retro}")

        lines.append("\n_R = Retrograde (vakri)_")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Graha sthiti error: {e}")
        return "__LLM_PLANETS__"


# ══════════════════════════════════════════════════════════════════
# GENERAL BUSINESS
# ══════════════════════════════════════════════════════════════════

# Email drafting, meeting notes, reminders — already in dedicated services.
# These are referenced here for the orchestrator's routing table.


# ══════════════════════════════════════════════════════════════════
# SKILL REGISTRY — the routing table the orchestrator uses
# ══════════════════════════════════════════════════════════════════

SKILL_REGISTRY = [
    # ── Universal ────────────────────────────────────────────
    {
        "name": "weather",
        "description": "Current weather for any city",
        "keywords": ["weather", "temperature", "mausam", "barish", "rain", "forecast",
                      "garmi", "thand", "thandi", "climate"],
        "vertical": "universal",
        "execute": weather,
    },
    {
        "name": "currency_convert",
        "description": "Convert any currency with amounts",
        "keywords": ["convert", "currency", "exchange rate", "AED", "USD", "EUR", "GBP",
                      "to INR", "to USD", "kitne rupees", "dollars", "dirhams", "pounds"],
        "vertical": "universal",
        "execute": currency_convert,
    },
    {
        "name": "stock_price",
        "description": "Live stock prices — Indian and international",
        "keywords": ["share price", "stock price", "NSE", "BSE", "nifty", "sensex",
                      "reliance", "tcs", "hdfc", "infosys", "adani", "titan",
                      "apple", "google", "tesla", "banknifty"],
        "vertical": "universal",
        "execute": stock_price,
    },
    {
        "name": "dictionary",
        "description": "English word definitions and meaning",
        "keywords": ["meaning of", "define", "definition", "word meaning", "matlab",
                      "english word", "vocabulary"],
        "vertical": "universal",
        "execute": dictionary_lookup,
    },
    {
        "name": "news",
        "description": "Latest news search by topic",
        "keywords": ["news", "latest news", "headlines", "khabar", "samachar",
                      "what happened", "current events"],
        "vertical": "universal",
        "execute": news_search,
    },

    # ── Jewelry ──────────────────────────────────────────────
    {
        "name": "gemstone_info",
        "description": "Gemstone identification, grading, pricing reference",
        "keywords": ["stone", "gemstone", "diamond", "ruby", "sapphire", "emerald",
                      "pearl", "opal", "tanzanite", "clarity", "4c", "carat",
                      "gem", "heera", "neelam", "panna", "moti"],
        "vertical": "jewelry",
        "execute": gemstone_info,
    },
    {
        "name": "jewelry_pricing",
        "description": "Calculate jewelry price from weight + making charges",
        "keywords": ["price", "cost", "kitna padega", "rate kya hoga", "kitna hoga",
                      "price batao", "cost batao", "rate batao", "kya rate",
                      "gram gold", "grams gold", "gram silver",
                      "making charge", "making charges",
                      "ring price", "earring price", "pendant price", "necklace price",
                      "bangle price", "bracelet price", "chain price", "mangalsutra price",
                      "jewelry price", "jewellery price",
                      "kitne ka", "kitne mein", "kitna aayega", "kya padega",
                      "price this", "cost of", "padega"],
        "vertical": "jewelry",
        "execute": jewelry_pricing,
    },
    {
        "name": "jewelcraft_analyze",
        "description": "Analyze any jewelry image — identify metals, stones, settings, era",
        "keywords": ["analyze", "identify", "what is this", "kya hai ye", "is photo mein",
                      "describe", "batao ye kya hai"],
        "vertical": "jewelry",
        "execute": jewelcraft_analyze,
    },
    {
        "name": "bom_pdf",
        "description": "Generate BOM PDF with pricing from jewelry image",
        "keywords": ["bom pdf", "bom sheet", "bill of material pdf", "pdf banao",
                      "bom report", "generate bom"],
        "vertical": "jewelry",
        "execute": gemlens_bom_pdf,
    },
    {
        "name": "gemlens_analyze",
        "description": "Detailed BOM — bill of materials, stone ID, metal, weight",
        "keywords": ["analyze", "bom", "identify", "stone id", "kya hai ye",
                      "is photo mein", "breakdown", "bill of material"],
        "vertical": "jewelry",
        "execute": gemlens_analyze,
    },
    {
        "name": "jewelcraft_render",
        "description": "Render a jewelry design from text description",
        "keywords": ["render", "design", "banao", "dikhao", "concept",
                      "generate design", "jewelry design", "ring design"],
        "vertical": "jewelry",
        "execute": jewelcraft_render,
    },
    {
        "name": "jewelcraft_enhance",
        "description": "Enhance jewelry photo to catalog-ready studio shot",
        "keywords": ["enhance", "catalog", "studio shot", "clean photo",
                      "professional photo", "product photo", "white background"],
        "vertical": "jewelry",
        "execute": jewelcraft_enhance,
    },
    {
        "name": "jewelcraft_ad",
        "description": "Create Instagram/WhatsApp marketing ad from jewelry photo",
        "keywords": ["ad", "instagram", "marketing", "promote", "whatsapp status",
                      "facebook", "social media", "ad banao", "promote karo"],
        "vertical": "jewelry",
        "execute": jewelcraft_ad,
    },
    {
        "name": "jewelcraft_vto",
        "description": "Virtual try-on — show jewelry on a person",
        "keywords": ["try on", "tryon", "virtual try", "pehen ke dikhao",
                      "how it looks", "model pe dikhao", "wear"],
        "vertical": "jewelry",
        "execute": jewelcraft_vto,
    },

    # ── Astrology (universal — every Indian user) ─────────────
    {
        "name": "daily_panchang",
        "description": "Today's Panchang — tithi, nakshatra, yoga, karana",
        "keywords": ["panchang", "tithi", "nakshatra", "yoga", "karana",
                      "aaj ka panchang", "hindu calendar", "panchangam"],
        "vertical": "universal",
        "execute": daily_panchang,
    },
    {
        "name": "kundli",
        "description": "Generate kundli / birth chart from birth details",
        "keywords": ["kundli", "kundali", "janam patri", "birth chart", "janam kundli",
                      "patrika", "horoscope chart", "janam patrika"],
        "vertical": "universal",
        "execute": kundli_generate,
    },
    {
        "name": "rashi_horoscope",
        "description": "Daily horoscope by rashi / zodiac sign",
        "keywords": ["rashi", "rashifal", "horoscope", "zodiac", "mesh", "vrishabh",
                      "mithun", "kark", "simha", "kanya", "tula", "vrishchik",
                      "dhanu", "makar", "kumbh", "meen", "aries", "taurus",
                      "gemini", "cancer", "leo", "virgo", "libra", "scorpio",
                      "sagittarius", "capricorn", "aquarius", "pisces",
                      "aaj ka rashifal", "daily horoscope"],
        "vertical": "universal",
        "execute": rashi_horoscope,
    },
    {
        "name": "compatibility",
        "description": "Gun Milan / kundli matching for marriage",
        "keywords": ["gun milan", "kundli milan", "compatibility", "match",
                      "shaadi match", "marriage match", "36 gun"],
        "vertical": "universal",
        "execute": compatibility_match,
    },
    {
        "name": "muhurat",
        "description": "Find auspicious timing (muhurat) for events",
        "keywords": ["muhurat", "shubh muhurat", "auspicious", "shubh din",
                      "shubh samay", "good time", "griha pravesh", "vivah muhurat"],
        "vertical": "universal",
        "execute": muhurat_check,
    },
    {
        "name": "vastu",
        "description": "Vastu Shastra tips for home, office, rooms",
        "keywords": ["vastu", "vaastu", "direction", "disha", "placement",
                      "bedroom vastu", "kitchen vastu", "office vastu",
                      "pooja room", "feng shui"],
        "vertical": "universal",
        "execute": vastu_tips,
    },
    {
        "name": "graha_sthiti",
        "description": "Current planetary positions — graha sthiti",
        "keywords": ["graha", "planet", "graha sthiti", "planetary position",
                      "shani", "rahu", "ketu", "mangal", "shukra", "guru",
                      "budh", "surya", "chandra", "retrograde", "vakri"],
        "vertical": "universal",
        "execute": graha_sthiti,
    },

    # ── Health ───────────────────────────────────────────────
    {
        "name": "drug_interactions",
        "description": "Check drug interactions from FDA database",
        "keywords": ["drug interaction", "medicine interaction", "medication",
                      "warfarin", "aspirin", "metformin", "side effect",
                      "contraindication", "prescribe", "dava", "dawai"],
        "vertical": "health",
        "execute": drug_interactions,
    },
    {
        "name": "calorie_lookup",
        "description": "Estimate calories and nutrition from food description",
        "keywords": ["calorie", "calories", "nutrition", "protein", "carb",
                      "fat content", "kitni calorie", "healthy", "diet"],
        "vertical": "health",
        "execute": calorie_lookup,
    },
    {
        "name": "medical_image",
        "description": "Analyze medical images — Xray, scan, report",
        "keywords": ["xray", "x-ray", "scan", "mri", "ct scan", "report",
                      "chest xray", "analyze this scan"],
        "vertical": "health",
        "execute": medical_image_analysis,
    },

    # ── Finance ──────────────────────────────────────────────
    {
        "name": "gst_rate",
        "description": "Indian GST rate lookup by product/service",
        "keywords": ["gst", "gst rate", "tax rate", "hsn", "sac code",
                      "goods and services tax", "kitna tax"],
        "vertical": "finance",
        "execute": gst_rate,
    },
    {
        "name": "invoice_draft",
        "description": "Draft a professional invoice or quotation",
        "keywords": ["invoice", "quotation", "bill banao", "estimate",
                      "proforma", "challan"],
        "vertical": "finance",
        "execute": invoice_draft,
    },

    # ── Legal ────────────────────────────────────────────────
    {
        "name": "indian_law",
        "description": "Search Indian legal cases and bare acts",
        "keywords": ["section", "act", "ipc", "crpc", "case law", "supreme court",
                      "high court", "legal", "kanoon", "law", "bare act",
                      "judgment", "faisla"],
        "vertical": "legal",
        "execute": indian_law_search,
    },
]

# ── Vertical keyword mapping ─────────────────────────────────────

VERTICAL_KEYWORDS = {
    "jewelry": ["jewel", "gold", "diamond", "ornament", "sona", "heera", "jewelry", "jewellery"],
    "health": ["doctor", "clinic", "health", "fitness", "medical", "hospital", "patient", "cardio", "trainer"],
    "finance": ["ca", "accountant", "finance", "tax", "audit", "chartered", "gst", "banking"],
    "legal": ["lawyer", "legal", "advocate", "court", "law firm", "attorney"],
}


def get_user_vertical(business_type: str) -> str:
    """Detect which vertical a user belongs to from their business_type."""
    if not business_type:
        return "general"
    bt = business_type.lower()
    for vertical, keywords in VERTICAL_KEYWORDS.items():
        if any(kw in bt for kw in keywords):
            return vertical
    return "general"


def get_skills_for_user(business_type: str) -> list:
    """Get all skills available to this user — universal + their vertical."""
    vertical = get_user_vertical(business_type)
    return [
        s for s in SKILL_REGISTRY
        if s["vertical"] == "universal" or s["vertical"] == vertical
    ]


async def find_and_execute(query: str, business_type: str, context: dict = None) -> str:
    """
    Find the best matching prebuilt skill for this query and execute it.
    Returns the skill's response, or empty string if no match.
    """
    # Action requests should go to orchestrator's smart Layer 4, not prebuilt skills
    action_prefixes = ["find ", "book ", "search ", "track ", "order ", "call ",
                       "nearest ", "closest ", "where ", "how to reach ", "directions ",
                       "dhundh", "khoj ", "manga ", "get me "]
    query_lower = query.lower().strip()
    if any(query_lower.startswith(p) for p in action_prefixes):
        return None

    available = get_skills_for_user(business_type)

    for skill in available:
        if any(kw in query_lower for kw in skill["keywords"]):
            try:
                result = await skill["execute"](query, context)
                if result and not result.startswith("__"):
                    logger.info(f"Prebuilt skill matched: {skill['name']}")
                    return result
                elif result and result.startswith("__"):
                    # Signal for orchestrator — special handling needed
                    return result
            except Exception as e:
                logger.error(f"Prebuilt skill {skill['name']} failed: {e}")
                continue

    return ""
