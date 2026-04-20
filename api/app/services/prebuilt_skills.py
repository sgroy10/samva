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
import re
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
             "RUPAYE": "INR", "EURO": "EUR", "EUROS": "EUR", "POUND": "GBP",
             "POUNDS": "GBP", "YEN": "JPY", "DIRHAM": "AED", "DIRHAMS": "AED",
             "RIYAL": "SAR", "BAHT": "THB", "YUAN": "CNY", "DINAR": "KWD",
             "RINGGIT": "MYR", "PESO": "PHP", "TAKA": "BDT", "RUPIAH": "IDR"}
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

    # Extract jewelry type — check longer words FIRST to avoid "ring" matching inside "earring"
    jewelry_type = "ring"  # default
    TYPE_MAP = [
        ("mangalsutra", "pendant"), ("earring", "earring"), ("necklace", "pendant"),
        ("bracelet", "bracelet"), ("pendant", "pendant"), ("bangle", "bangle"),
        ("chain", "pendant"), ("ring", "ring"), ("tops", "earring"),
        ("jhumka", "earring"), ("jhumki", "earring"), ("kangan", "bangle"),
        ("haar", "pendant"), ("anguthi", "ring"),
    ]
    for kw, jtype in TYPE_MAP:
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


# ── Gold/Silver Rate (uses existing gold.py) ───────────────────
async def gold_rate_skill(query: str, context: dict = None) -> str:
    """Live gold/silver/platinum rates — calls the existing gold service."""
    try:
        from .gold import _fetch_prices
        prices = await _fetch_prices()
        if not prices or not prices.get("gold_24k"):
            return "📊 Gold rate abhi fetch nahi ho raha. Thodi der mein try karo."

        g24 = prices.get("gold_24k", 0)
        g22 = prices.get("gold_22k", 0)
        g18 = prices.get("gold_18k", 0)
        silver = prices.get("silver_inr", 0)
        platinum = prices.get("platinum_inr", 0)

        lines = ["📊 *Live Gold & Silver Rates:*\n"]
        lines.append(f"▸ Gold 24K: ₹{g24:,.0f}/gm")
        lines.append(f"▸ Gold 22K: ₹{g22:,.0f}/gm")
        lines.append(f"▸ Gold 18K: ₹{g18:,.0f}/gm")
        if silver:
            lines.append(f"▸ Silver: ₹{silver:,.0f}/gm")
        if platinum:
            lines.append(f"▸ Platinum: ₹{platinum:,.0f}/gm")

        return "\n".join(lines)
    except Exception as e:
        return f"📊 Gold rate fetch error: {str(e)[:50]}"


# ══════════════════════════════════════════════════════════════════
# NEW SKILLS — integrated from open-source GitHub repos
# ══════════════════════════════════════════════════════════════════


# ── Flight Search (REAL Google Flights via fli library) ─────────
async def flight_search(query: str, context: dict = None) -> str:
    """Search REAL flights using Google Flights via fli library.
    Returns actual prices, airlines, times — not just links."""
    import re
    from datetime import date, datetime, timedelta

    query_lower = query.lower()

    # City to IATA code mapping
    city_codes = {
        "mumbai": "BOM", "delhi": "DEL", "bangalore": "BLR", "bengaluru": "BLR",
        "chennai": "MAA", "kolkata": "CCU", "hyderabad": "HYD", "pune": "PNQ",
        "ahmedabad": "AMD", "goa": "GOI", "jaipur": "JAI", "lucknow": "LKO",
        "kochi": "COK", "guwahati": "GAU", "chandigarh": "IXC", "srinagar": "SXR",
        "varanasi": "VNS", "indore": "IDR", "bhopal": "BHO", "patna": "PAT",
        "dubai": "DXB", "singapore": "SIN", "bangkok": "BKK", "london": "LHR",
        "new york": "JFK", "toronto": "YYZ", "doha": "DOH", "sharjah": "SHJ",
    }

    # Extract cities
    from_city = ""
    to_city = ""
    for city in city_codes:
        if city in query_lower:
            if not from_city:
                from_city = city
            elif not to_city:
                to_city = city

    if not (from_city and to_city):
        if from_city or to_city:
            return "✈️ Dono cities batao — kahan se kahan?\nExample: 'Mumbai to Delhi flight 20 April'"
        return ""

    from_code = city_codes[from_city]
    to_code = city_codes[to_city]

    # Extract date (default: 7 days from now)
    travel_date = date.today() + timedelta(days=7)
    date_match = re.search(r'(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|april|march|june|july)', query_lower)
    if date_match:
        day = int(date_match.group(1))
        month_str = date_match.group(2)[:3]
        months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                  "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
        month = months.get(month_str, date.today().month)
        year = date.today().year
        if month < date.today().month:
            year += 1
        try:
            travel_date = date(year, month, day)
        except ValueError:
            pass

    # Search using fli
    try:
        from fli.search import SearchFlights
        from fli.models.google_flights.flights import FlightSearchFilters
        from fli.models.google_flights.base import FlightSegment, PassengerInfo
        from fli.models.airport import Airport

        dep_airport = getattr(Airport, from_code, None)
        arr_airport = getattr(Airport, to_code, None)
        if not dep_airport or not arr_airport:
            return f"✈️ Airport code {from_code} or {to_code} not found"

        filters = FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[dep_airport, 0]],
                    arrival_airport=[[arr_airport, 0]],
                    travel_date=travel_date.isoformat(),
                )
            ],
        )

        sf = SearchFlights()
        results = sf.search(filters, top_n=5)

        if not results:
            return f"✈️ {from_city.title()} → {to_city.title()} ({travel_date.strftime('%d %b')}): No flights found"

        # Format results
        lines = [f"✈️ *{from_city.title()} → {to_city.title()}* ({travel_date.strftime('%d %b %Y')}):\n"]

        cheapest = None
        for i, flight in enumerate(results[:5]):
            if flight.stops == 0:  # Prefer non-stop
                leg = flight.legs[0]
                airline = leg.airline.value if hasattr(leg.airline, 'value') else str(leg.airline)
                dep_time = leg.departure_datetime.strftime("%H:%M") if leg.departure_datetime else "?"
                arr_time = leg.arrival_datetime.strftime("%H:%M") if leg.arrival_datetime else "?"
                duration_h = flight.duration // 60
                duration_m = flight.duration % 60
                price = int(flight.price)

                if not cheapest or price < cheapest:
                    cheapest = price

                star = " ⭐" if price == cheapest else ""
                lines.append(
                    f"▸ {airline} {leg.flight_number} | {dep_time}→{arr_time} | "
                    f"₹{price:,} | {duration_h}h{duration_m}m{star}"
                )

        if cheapest:
            lines.append(f"\n💡 Cheapest non-stop: ₹{cheapest:,}")
            lines.append("Book karun? Ya aur dates check karni hain?")

        return "\n".join(lines)

    except ImportError:
        return (
            f"✈️ *{from_city.title()} → {to_city.title()} ({travel_date.strftime('%d %b')}):*\n\n"
            f"Check: google.com/flights, makemytrip.com, cleartrip.com\n"
            f"💡 Book 2-3 weeks advance for best rates!"
        )
    except Exception as e:
        return f"✈️ Flight search error: {str(e)[:100]}. Try google.com/flights"


# ── Train / IRCTC (PNR + availability) ──────────────────────────
async def train_info(query: str, context: dict = None) -> str:
    """Indian Railways info — PNR status, train search."""
    import httpx as hx
    import re

    query_lower = query.lower()

    # PNR check
    pnr_match = re.search(r'\b(\d{10})\b', query)
    if pnr_match:
        pnr = pnr_match.group(1)
        # Try multiple PNR APIs
        apis = [
            f"https://indianrailapi.com/api/v2/PNRCheck/apikey/demo/PNRNumber/{pnr}",
            f"https://pnr-status-indian-railway.p.rapidapi.com/pnr-check/{pnr}",
        ]
        for api_url in apis:
            try:
                async with hx.AsyncClient(timeout=10) as client:
                    resp = await client.get(api_url, headers={"User-Agent": "Samva/1.0"})
                    if resp.status_code == 200:
                        data = resp.json()
                        train = data.get("TrainName", data.get("train_name", data.get("trainName", "")))
                        status = data.get("CurrentStatus", data.get("current_status", data.get("chartStatus", "")))
                        boarding = data.get("BoardingPoint", data.get("boarding_point", ""))
                        dest = data.get("ReservationUpto", data.get("destination", ""))
                        date_journey = data.get("DateOfJourney", data.get("journey_date", ""))

                        passengers = data.get("PassengerStatus", data.get("passengers", []))
                        pax_text = ""
                        if passengers and isinstance(passengers, list):
                            for j, p in enumerate(passengers[:4]):
                                pax_status = p.get("CurrentStatus", p.get("current_status", ""))
                                pax_text += f"\n  Passenger {j+1}: {pax_status}"

                        return (
                            f"🚂 *PNR: {pnr}*\n\n"
                            f"Train: {train}\n"
                            f"Date: {date_journey}\n"
                            f"From: {boarding} → {dest}\n"
                            f"Status: {status}"
                            f"{pax_text}"
                        )
            except Exception:
                continue
        # All APIs failed — still give useful response
        return (
            f"🚂 *PNR {pnr}:*\n\n"
            f"Live status abhi fetch nahi ho raha.\n"
            f"Check karo: https://www.indianrail.gov.in/enquiry/PNR\n"
            f"Ya IRCTC app pe PNR dal ke dekho."
        )

    # General train query
    return (
        "🚂 *Indian Railways Help:*\n\n"
        "▸ PNR check: apna 10-digit PNR number bhejo\n"
        "▸ Booking: irctc.co.in\n"
        "▸ Tatkal booking: 10 AM (AC), 11 AM (non-AC)\n"
        "▸ Live status: enquiry.indianrail.gov.in\n\n"
        "Kya specifically chahiye? PNR, schedule, ya booking help?"
    )


# ── Indian Stock Market (NSE/BSE — free, no API key) ────────────
async def indian_stocks(query: str, context: dict = None) -> str:
    """Live Indian stock prices from NSE/BSE."""
    import httpx as hx

    query_lower = query.lower()

    # Map common names to NSE symbols
    stock_map = {
        "reliance": "RELIANCE", "tcs": "TCS", "infosys": "INFY",
        "hdfc": "HDFCBANK", "icici": "ICICIBANK", "sbi": "SBIN",
        "wipro": "WIPRO", "itc": "ITC", "adani": "ADANIENT",
        "tata motors": "TATAMOTORS", "maruti": "MARUTI", "bajaj": "BAJFINANCE",
        "hcl": "HCLTECH", "sun pharma": "SUNPHARMA", "titan": "TITAN",
        "asian paints": "ASIANPAINT", "kotak": "KOTAKBANK", "axis": "AXISBANK",
        "nifty": "NIFTY", "sensex": "SENSEX",
    }

    # Find stock symbol — use word boundary to avoid "itc" matching inside "bitcoin"
    import re as stock_re
    symbol = None
    for name, sym in stock_map.items():
        if stock_re.search(r'\b' + stock_re.escape(name) + r'\b', query_lower):
            symbol = sym
            break

    if not symbol:
        return ""

    # Try multiple free stock APIs
    apis = [
        f"https://stock-market-india-api.vercel.app/nse/{symbol}",
        f"https://priceapi.moneycontrol.com/techCharts/techChartController/symbols?symbol={symbol}&resolution=1D",
        f"https://groww.in/v1/api/stocks_data/v1/accord_points/exchange/NSE/segment/CASH/latest_prices_ohlc/{symbol}",
    ]

    for api_url in apis:
        try:
            async with hx.AsyncClient(timeout=8) as client:
                resp = await client.get(api_url, headers={"User-Agent": "Samva/1.0"})
                if resp.status_code == 200:
                    data = resp.json()
                    # Handle different API response formats
                    price = (data.get("lastPrice") or data.get("close") or
                             data.get("ltp") or data.get("price") or
                             data.get("lastTradedPrice"))
                    change = (data.get("pChange") or data.get("change_percent") or
                              data.get("dayChangePerc") or "")

                    if price:
                        arrow = "↑" if str(change).replace('-','').replace('.','').isdigit() and float(str(change)) > 0 else "↓"
                        return (
                            f"📈 *{symbol}:* ₹{price:,}" if isinstance(price, (int, float)) else f"📈 *{symbol}:* ₹{price}\n"
                            f"Change: {arrow}{change}%\n\n"
                            f"Watchlist mein add karun?"
                        )
        except Exception:
            continue

    # Use yfinance — most reliable for Indian stocks
    try:
        import yfinance as yf
        stock = yf.Ticker(f"{symbol}.NS")
        info = stock.fast_info
        price = info.last_price
        day_high = info.day_high
        day_low = info.day_low
        volume = info.last_volume
        prev = info.previous_close

        if price:
            lines = [f"📈 *{symbol}:* ₹{price:,.2f}"]
            if prev:
                change = round((price - prev) / prev * 100, 2)
                arrow = "↑" if change > 0 else "↓"
                lines[0] += f" {arrow}{abs(change)}%"
            if day_high and day_low:
                lines.append(f"High: ₹{day_high:,.2f} | Low: ₹{day_low:,.2f}")
            if volume:
                lines.append(f"Volume: {volume:,}")
            if prev:
                lines.append(f"Prev: ₹{prev:,.2f}")
            lines.append("\nWatchlist mein add karun?")
            return "\n".join(lines)
    except Exception as e:
        import logging
        logging.getLogger("samva.skills").warning(f"yfinance error for {symbol}: {e}")

    return f"📈 {symbol}: Rate abhi fetch nahi ho raha. Market band ho sakta hai."


# ── IFSC Code Lookup ────────────────────────────────────────────
async def ifsc_lookup(query: str, context: dict = None) -> str:
    """Look up bank branch details from IFSC code."""
    import httpx as hx
    import re

    # Only match if "ifsc" or "branch" mentioned, OR pattern is clearly IFSC
    if not any(w in query.lower() for w in ["ifsc", "branch code", "bank branch"]):
        # If no keyword, only match if the IFSC pattern is very clear
        ifsc_strict = re.search(r'\b([A-Z]{4}0[A-Z0-9]{6})\b', query.upper())
        if not ifsc_strict or len(query.split()) > 5:
            return ""  # Don't match random text

    ifsc_match = re.search(r'\b([A-Z]{4}0[A-Z0-9]{6})\b', query.upper())
    if not ifsc_match:
        return ""

    ifsc = ifsc_match.group(1)
    try:
        async with hx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://ifsc.razorpay.com/{ifsc}")
            if resp.status_code == 200:
                data = resp.json()
                return (
                    f"🏦 *IFSC: {ifsc}*\n\n"
                    f"Bank: {data.get('BANK', 'N/A')}\n"
                    f"Branch: {data.get('BRANCH', 'N/A')}\n"
                    f"City: {data.get('CITY', 'N/A')}\n"
                    f"State: {data.get('STATE', 'N/A')}\n"
                    f"Address: {data.get('ADDRESS', 'N/A')}"
                )
    except Exception:
        pass
    return ""


# ── Pincode Lookup ──────────────────────────────────────────────
async def pincode_lookup(query: str, context: dict = None) -> str:
    """Look up area details from Indian pincode."""
    import httpx as hx
    import re

    pin_match = re.search(r'\b(\d{6})\b', query)
    if not pin_match:
        return ""

    pincode = pin_match.group(1)
    try:
        async with hx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://api.postalpincode.in/pincode/{pincode}")
            if resp.status_code == 200:
                data = resp.json()
                if data and data[0].get("Status") == "Success":
                    offices = data[0].get("PostOffice", [])
                    if offices:
                        o = offices[0]
                        return (
                            f"📮 *Pincode {pincode}:*\n\n"
                            f"Area: {o.get('Name', 'N/A')}\n"
                            f"District: {o.get('District', 'N/A')}\n"
                            f"State: {o.get('State', 'N/A')}\n"
                            f"Delivery: {o.get('DeliveryStatus', 'N/A')}"
                        )
    except Exception:
        pass
    return ""


# ── Loan EMI Calculator ─────────────────────────────────────────
async def emi_calculator(query: str, context: dict = None) -> str:
    """Calculate loan EMI from amount, rate, tenure."""
    import re

    ql = query.lower()

    # Handle lakh/crore multipliers
    lakh_match = re.search(r'([\d,.]+)\s*(?:lakh|lac|lacs)', ql)
    crore_match = re.search(r'([\d,.]+)\s*(?:crore|cr)', ql)

    # Extract all numbers
    numbers = re.findall(r'[\d,.]+', ql.replace(',', ''))
    if len(numbers) < 2:
        return ""

    nums = [float(n) for n in numbers[:3]]

    if len(nums) >= 3:
        amount, rate, years = nums[0], nums[1], nums[2]
    elif len(nums) == 2:
        amount, rate = nums[0], nums[1]
        years = 20 if amount > 100000 else 5

    # Apply lakh/crore multiplier
    if crore_match:
        amount = float(crore_match.group(1).replace(',', '')) * 10000000
    elif lakh_match:
        amount = float(lakh_match.group(1).replace(',', '')) * 100000
    elif amount < 1000:
        # Maybe they said "50" meaning 50 lakh
        if "lakh" in ql or "lac" in ql:
            amount *= 100000
        elif "crore" in ql or "cr" in ql:
            amount *= 10000000
        else:
            return ""

    # EMI formula: P × r × (1+r)^n / ((1+r)^n - 1)
    monthly_rate = rate / (12 * 100)
    months = int(years * 12)
    if monthly_rate == 0:
        emi = amount / months
    else:
        emi = amount * monthly_rate * (1 + monthly_rate)**months / ((1 + monthly_rate)**months - 1)

    total = emi * months
    interest = total - amount

    return (
        f"💰 *EMI Calculator:*\n\n"
        f"Loan: ₹{amount:,.0f}\n"
        f"Rate: {rate}% p.a.\n"
        f"Tenure: {years:.0f} years ({months} months)\n\n"
        f"*EMI: ₹{emi:,.0f}/month*\n"
        f"Total payment: ₹{total:,.0f}\n"
        f"Interest: ₹{interest:,.0f}"
    )


# ── BMI Calculator ──────────────────────────────────────────────
async def bmi_calculator(query: str, context: dict = None) -> str:
    """Calculate BMI from height and weight."""
    import re

    # Try feet+inches pattern first: "5 feet 10 inch", "5'10", "5ft 10in"
    feet_inch_match = re.search(
        r'(\d+)\s*(?:feet|foot|ft|\')\s*(\d+)\s*(?:inch|inches|in|")?',
        query, re.IGNORECASE
    )

    height_m = None
    weight = None

    if feet_inch_match:
        feet = float(feet_inch_match.group(1))
        inches = float(feet_inch_match.group(2))
        height_m = (feet * 12 + inches) * 0.0254  # Convert total inches to meters
        # Find weight: the number NOT part of the feet/inch match
        remaining = query[:feet_inch_match.start()] + query[feet_inch_match.end():]
        weight_nums = re.findall(r'[\d.]+', remaining)
        if weight_nums:
            weight = float(weight_nums[0])
    else:
        numbers = re.findall(r'[\d.]+', query)
        if len(numbers) < 2:
            return ""

        nums = sorted([float(n) for n in numbers[:2]])
        # Heuristic: smaller is height (in feet or meters), larger is weight (kg)
        height_val = nums[0]
        weight = nums[1]

        # Convert feet to meters if needed
        if height_val < 3:
            height_m = height_val  # Already meters
        elif height_val < 10:
            height_m = height_val * 0.3048  # Feet to meters
        else:
            height_m = height_val / 100  # CM to meters

    if not height_m or not weight:
        return ""

    if height_m < 0.5 or weight < 10:
        return ""

    bmi = weight / (height_m ** 2)

    if bmi < 18.5:
        cat = "Underweight"
        emoji = "⚠️"
    elif bmi < 25:
        cat = "Normal"
        emoji = "✅"
    elif bmi < 30:
        cat = "Overweight"
        emoji = "⚠️"
    else:
        cat = "Obese"
        emoji = "🚨"

    return (
        f"📊 *BMI Calculator:*\n\n"
        f"Height: {height_m:.2f}m | Weight: {weight:.0f}kg\n"
        f"*BMI: {bmi:.1f}* {emoji} ({cat})\n\n"
        f"Normal range: 18.5 - 24.9"
    )


# ── Age Calculator ──────────────────────────────────────────────
async def age_calculator(query: str, context: dict = None) -> str:
    """Calculate age from date of birth."""
    import re
    from datetime import datetime

    # Try to find date patterns: dd/mm/yyyy, dd-mm-yyyy, dd month yyyy
    date_patterns = [
        r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})',  # dd/mm/yyyy
        r'(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})',  # yyyy/mm/dd
    ]

    for pattern in date_patterns:
        match = re.search(pattern, query)
        if match:
            groups = match.groups()
            try:
                if len(groups[0]) == 4:  # yyyy/mm/dd
                    dob = datetime(int(groups[0]), int(groups[1]), int(groups[2]))
                else:  # dd/mm/yyyy
                    dob = datetime(int(groups[2]), int(groups[1]), int(groups[0]))

                today = datetime.now()
                age_years = today.year - dob.year
                if (today.month, today.day) < (dob.month, dob.day):
                    age_years -= 1
                age_months = (today.month - dob.month) % 12
                age_days = (today - dob).days

                return (
                    f"🎂 *Age Calculator:*\n\n"
                    f"DOB: {dob.strftime('%d %B %Y')}\n"
                    f"Age: *{age_years} years, {age_months} months*\n"
                    f"Total days: {age_days:,}\n\n"
                    f"Next birthday in: {365 - (age_days % 365)} days"
                )
            except (ValueError, IndexError):
                pass
    return ""


# ── GST Calculator ──────────────────────────────────────────────
async def gst_calculator(query: str, context: dict = None) -> str:
    """Calculate GST on an amount."""
    import re

    numbers = re.findall(r'[\d,.]+', query.replace(',', ''))
    if not numbers:
        return ""

    amount = float(numbers[0])
    if amount < 10:
        return ""

    # Try to find GST slab
    gst_rate = 18  # default
    if "5%" in query or "5 percent" in query.lower():
        gst_rate = 5
    elif "12%" in query or "12 percent" in query.lower():
        gst_rate = 12
    elif "28%" in query or "28 percent" in query.lower():
        gst_rate = 28

    gst = amount * gst_rate / 100
    cgst = gst / 2
    sgst = gst / 2
    total = amount + gst

    return (
        f"📊 *GST Calculator:*\n\n"
        f"Amount: ₹{amount:,.0f}\n"
        f"GST Rate: {gst_rate}%\n\n"
        f"CGST ({gst_rate//2}%): ₹{cgst:,.0f}\n"
        f"SGST ({gst_rate//2}%): ₹{sgst:,.0f}\n"
        f"Total GST: ₹{gst:,.0f}\n\n"
        f"*Total with GST: ₹{total:,.0f}*"
    )


# ── Hindi Jokes ─────────────────────────────────────────────────
async def hindi_joke(query: str, context: dict = None) -> str:
    """Get a random Hindi joke."""
    import httpx as hx
    try:
        async with hx.AsyncClient(timeout=8) as client:
            resp = await client.get("https://hindi-jokes-api.onrender.com/jokes?api_key=93ecab36e0")
            if resp.status_code == 200:
                data = resp.json()
                joke = data.get("jokeContent", data.get("joke", ""))
                if joke:
                    return f"😂 *Joke:*\n\n{joke}"
    except Exception:
        pass
    # Fallback jokes
    import random
    jokes = [
        "Teacher: Tumne homework kyun nahi kiya?\nStudent: WiFi nahi tha.\nTeacher: Homework toh copy mein tha!\nStudent: ...virus aa gaya tha! 😂",
        "Pappu: Doctor saab, sab log mujhe ignore karte hain.\nDoctor: Next please! 😂",
        "Wife: Aaj khana nahi banaugi.\nHusband: Koi baat nahi.\nWife: Matlab?!\nHusband: Matlab... Zomato hai na! 😂",
        "Chhotu: Main bada hokar pilot banunga!\nMummy: Pehle 10th pass kar lo! 😂",
    ]
    return f"😂 *Joke:*\n\n{random.choice(jokes)}"


# ── Quotes (Hindi + English) ───────────────────────────────────
async def daily_quote(query: str, context: dict = None) -> str:
    """Get a motivational quote."""
    import httpx as hx
    try:
        async with hx.AsyncClient(timeout=8) as client:
            resp = await client.get("https://api.quotable.io/random?maxLength=150")
            if resp.status_code == 200:
                data = resp.json()
                return f"💡 *Quote of the Day:*\n\n\"{data['content']}\"\n— {data['author']}"
    except Exception:
        pass
    import random
    quotes = [
        "\"Kaam karo, fal ki chinta mat karo.\" — Bhagavad Gita 💪",
        "\"Sapne wo nahi jo neend mein aaye, sapne wo hain jo neend na aane de.\" — APJ Abdul Kalam 🌟",
        "\"Mushkilein toh aati hain, par himmat rakhne wala hi jeet-ta hai.\" 💪",
        "\"Haar ke baad jeet hoti hai, aur raat ke baad subah.\" 🌅",
    ]
    return f"💡 *Aaj ka Vichar:*\n\n{random.choice(quotes)}"


# ── QR Code Generator ──────────────────────────────────────────
async def qr_generator(query: str, context: dict = None) -> str:
    """Generate QR code for text/URL/UPI."""
    import re
    # Extract the content to encode
    query_lower = query.lower()
    # Remove trigger words
    content = re.sub(r'qr\s*(code)?\s*(bana|generate|create|make|of|for|ka)?\s*', '', query_lower, flags=re.I).strip()
    if not content or len(content) < 3:
        return ""

    # Use Google Charts API for QR (free, no key)
    encoded = content.replace(' ', '+')
    qr_url = f"https://chart.googleapis.com/chart?cht=qr&chs=300x300&chl={encoded}"

    return (
        f"📱 *QR Code Generated:*\n\n"
        f"Content: {content}\n"
        f"Link: {qr_url}\n\n"
        f"_Image bhi chahiye toh 'show qr' bolo_"
    )


# ── Mutual Fund NAV ────────────────────────────────────────────
async def mutual_fund(query: str, context: dict = None) -> str:
    """Get mutual fund NAV from AMFI."""
    import httpx as hx

    query_lower = query.lower()

    # Only match if "fund" or "nav" or "sip" or "mf" is mentioned
    if not any(w in query_lower for w in ["fund", "nav", "sip", "mutual", "mf "]):
        return ""

    # Common fund name mappings (AMFI scheme codes)
    fund_map = {
        "sbi": "119598", "hdfc": "118989", "icici": "120505",
        "axis": "120503", "kotak": "120166", "nippon": "118778",
        "tata": "119551", "dsp": "119455",
    }

    fund_code = None
    for name, code in fund_map.items():
        if name in query_lower:
            fund_code = code
            break

    if fund_code:
        try:
            # Use mftool for reliable data
            from mftool import Mftool
            mf = Mftool()
            data = mf.get_scheme_quote(fund_code)
            if data:
                return (
                    f"📊 *Mutual Fund NAV:*\n\n"
                    f"Scheme: {data.get('scheme_name', 'N/A')[:60]}\n"
                    f"NAV: ₹{data.get('last_updated_nav', 'N/A')}\n"
                    f"Date: {data.get('last_updated', 'N/A')}\n"
                    f"Category: {data.get('scheme_category', 'N/A')}"
                )
        except ImportError:
            # Fallback to API
            try:
                async with hx.AsyncClient(timeout=10) as client:
                    resp = await client.get(f"https://api.mfapi.in/mf/{fund_code}/latest")
                    if resp.status_code == 200:
                        api_data = resp.json()
                        nav_data = api_data.get("data", [{}])[0]
                        scheme = api_data.get("meta", {}).get("scheme_name", "Fund")
                        return (
                            f"📊 *Mutual Fund NAV:*\n\n"
                            f"Scheme: {scheme[:60]}\n"
                            f"NAV: ₹{nav_data.get('nav', 'N/A')}\n"
                            f"Date: {nav_data.get('date', 'N/A')}"
                        )
            except Exception:
                pass
        except Exception:
            pass

    return (
        "📊 *Mutual Fund Help:*\n\n"
        "Fund ka naam batao — SBI, HDFC, ICICI, Axis, Kotak, Nippon, Tata, DSP\n"
        "Example: 'SBI mutual fund NAV'\n\n"
        "Investment advice: SIP (Systematic Investment Plan) sabse achha tarika hai!"
    )


# ── Crypto Prices ──────────────────────────────────────────────
async def crypto_price(query: str, context: dict = None) -> str:
    """Get cryptocurrency prices."""
    import httpx as hx

    query_lower = query.lower()

    # Only match if crypto-specific word is present
    if not any(w in query_lower for w in ["bitcoin", "btc", "ethereum", "eth", "crypto",
                                           "dogecoin", "doge", "solana", "xrp", "ripple",
                                           "cryptocurrency"]):
        return ""

    crypto_map = {
        "bitcoin": "bitcoin", "btc": "bitcoin",
        "ethereum": "ethereum", "eth ": "ethereum",
        "solana": "solana",
        "dogecoin": "dogecoin", "doge": "dogecoin",
        "xrp": "ripple", "ripple": "ripple",
    }

    coin_id = None
    for name, cid in crypto_map.items():
        if name in query_lower:
            coin_id = cid
            break

    if not coin_id:
        coin_id = "bitcoin"  # Default to BTC if just "crypto" mentioned

    try:
        async with hx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=inr,usd&include_24hr_change=true"
            )
            if resp.status_code == 200:
                data = resp.json().get(coin_id, {})
                inr = data.get("inr", "N/A")
                usd = data.get("usd", "N/A")
                change = data.get("inr_24h_change", 0)
                arrow = "↑" if change > 0 else "↓"
                return (
                    f"₿ *{coin_id.title()}:*\n\n"
                    f"₹{inr:,.0f} | ${usd:,.2f}\n"
                    f"24h: {arrow}{abs(change):.1f}%\n\n"
                    f"⚠️ Crypto volatile hai — invest carefully."
                )
    except Exception:
        pass
    return ""


# ── Cricket Live Scores ─────────────────────────────────────────
async def cricket_score(query: str, context: dict = None) -> str:
    """Live cricket scores from Cricbuzz."""
    import httpx as hx
    try:
        async with hx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://cricbuzz-live.vercel.app/matches/live",
                                    headers={"User-Agent": "Samva/1.0"})
            if resp.status_code == 200:
                data = resp.json()
                matches = data if isinstance(data, list) else data.get("matches", data.get("data", []))
                if matches:
                    lines = ["🏏 *Live Cricket:*\n"]
                    for m in matches[:3]:
                        title = m.get("title", m.get("matchDesc", ""))
                        team1 = m.get("team1", {})
                        team2 = m.get("team2", {})
                        t1_name = team1.get("name", team1.get("teamName", "")) if isinstance(team1, dict) else str(team1)
                        t2_name = team2.get("name", team2.get("teamName", "")) if isinstance(team2, dict) else str(team2)
                        status = m.get("status", m.get("matchStatus", ""))
                        lines.append(f"▸ {t1_name} vs {t2_name}")
                        if status:
                            lines.append(f"  {status}")
                    return "\n".join(lines)
    except Exception:
        pass
    return "🏏 Live scores check kar rahi hoon... Cricbuzz pe dekho: cricbuzz.com"


# ── Translation (Hindi ↔ English + Indian langs) ───────────────
async def translate_text(query: str, context: dict = None) -> str:
    """Translate text between Hindi, English, and Indian languages."""
    import re
    query_lower = query.lower()

    # Extract: "translate X to Y" or "X ka hindi" or "hindi mein batao"
    to_hindi = any(w in query_lower for w in ["hindi mein", "hindi me", "ka hindi", "to hindi"])
    to_english = any(w in query_lower for w in ["english mein", "english me", "ka english", "to english",
                                                  "meaning of", "matlab"])

    # Extract the text to translate
    text = re.sub(r'(translate|hindi mein|english mein|ka hindi|ka english|to hindi|to english|meaning of|matlab|batao)', '', query_lower).strip()
    if not text or len(text) < 2:
        return ""

    # Try deep_translator first, then httpx fallback
    try:
        from deep_translator import GoogleTranslator
        if to_hindi:
            result = GoogleTranslator(source='en', target='hi').translate(text)
        elif to_english:
            result = GoogleTranslator(source='hi', target='en').translate(text)
        else:
            result = GoogleTranslator(source='auto', target='en').translate(text)
        return f"🔤 *Translation:*\n\n{text} → *{result}*"
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: use free translation API
    try:
        import httpx as hx
        target = "hi" if to_hindi else "en"
        source = "en" if to_hindi else "hi"
        async with hx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.mymemory.translated.net/get?q={text}&langpair={source}|{target}"
            )
            if resp.status_code == 200:
                data = resp.json()
                translated = data.get("responseData", {}).get("translatedText", "")
                if translated:
                    return f"🔤 *Translation:*\n\n{text} → *{translated}*"
    except Exception:
        pass
    return f"🔤 Translation abhi available nahi hai. Try: translate.google.com"


# ── Air Quality Index (Indian cities) ──────────────────────────
async def air_quality(query: str, context: dict = None) -> str:
    """Get air quality index for Indian cities."""
    import httpx as hx
    import re

    # Extract city
    query_lower = query.lower()
    city_coords = {
        "delhi": (28.61, 77.23), "mumbai": (19.07, 72.88), "bangalore": (12.97, 77.59),
        "chennai": (13.08, 80.27), "kolkata": (22.57, 88.36), "hyderabad": (17.38, 78.49),
        "pune": (18.52, 73.85), "ahmedabad": (23.02, 72.57), "jaipur": (26.91, 75.79),
        "lucknow": (26.85, 80.95), "noida": (28.57, 77.32), "gurgaon": (28.46, 77.03),
    }

    city = None
    for c in city_coords:
        if c in query_lower:
            city = c
            break

    if not city:
        return ""

    lat, lon = city_coords[city]
    try:
        async with hx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=pm2_5,pm10,us_aqi"
            )
            if resp.status_code == 200:
                data = resp.json().get("current", {})
                aqi = data.get("us_aqi", 0)
                pm25 = data.get("pm2_5", 0)
                pm10 = data.get("pm10", 0)

                if aqi <= 50: level, emoji = "Good", "🟢"
                elif aqi <= 100: level, emoji = "Moderate", "🟡"
                elif aqi <= 150: level, emoji = "Unhealthy (Sensitive)", "🟠"
                elif aqi <= 200: level, emoji = "Unhealthy", "🔴"
                else: level, emoji = "Hazardous", "🟣"

                return (
                    f"🌬️ *Air Quality — {city.title()}:*\n\n"
                    f"AQI: {aqi} {emoji} ({level})\n"
                    f"PM2.5: {pm25} µg/m³\n"
                    f"PM10: {pm10} µg/m³\n\n"
                    f"{'Mask lagao bahar jaate waqt!' if aqi > 100 else 'Fresh air hai, enjoy!'}"
                )
    except Exception:
        pass
    return ""


# ── Indian Holidays ────────────────────────────────────────────
async def indian_holiday(query: str, context: dict = None) -> str:
    """Check upcoming Indian holidays."""
    from datetime import date, timedelta

    # Hardcoded 2026 holidays (reliable, no API needed)
    holidays_2026 = [
        (date(2026, 1, 14), "Makar Sankranti / Pongal"),
        (date(2026, 1, 26), "Republic Day"),
        (date(2026, 3, 10), "Maha Shivaratri"),
        (date(2026, 3, 17), "Holi"),
        (date(2026, 3, 31), "Eid ul-Fitr"),
        (date(2026, 4, 2), "Good Friday"),
        (date(2026, 4, 6), "Ram Navami"),
        (date(2026, 4, 14), "Ambedkar Jayanti / Baisakhi"),
        (date(2026, 5, 1), "May Day"),
        (date(2026, 5, 26), "Buddha Purnima"),
        (date(2026, 6, 7), "Bakrid / Eid ul-Adha"),
        (date(2026, 7, 7), "Muharram"),
        (date(2026, 7, 17), "Guru Purnima"),
        (date(2026, 8, 15), "Independence Day"),
        (date(2026, 8, 19), "Janmashtami"),
        (date(2026, 8, 29), "Raksha Bandhan"),
        (date(2026, 9, 5), "Milad un-Nabi"),
        (date(2026, 9, 7), "Ganesh Chaturthi"),
        (date(2026, 10, 2), "Gandhi Jayanti"),
        (date(2026, 10, 20), "Dussehra"),
        (date(2026, 11, 1), "Diwali"),
        (date(2026, 11, 15), "Guru Nanak Jayanti"),
        (date(2026, 12, 25), "Christmas"),
    ]

    today = date.today()
    upcoming = [(d, name) for d, name in holidays_2026 if d >= today][:5]

    if not upcoming:
        return "📅 Is saal ke holidays khatam. Naye saal ka intezaar!"

    lines = ["📅 *Upcoming Indian Holidays:*\n"]
    for d, name in upcoming:
        days_left = (d - today).days
        lines.append(f"▸ {d.strftime('%d %b')} — {name} ({days_left} din)")

    return "\n".join(lines)


# ── Income Tax Calculator (India) ──────────────────────────────
async def income_tax(query: str, context: dict = None) -> str:
    """Calculate Indian income tax under new regime."""
    import re

    numbers = re.findall(r'[\d,.]+', query.replace(',', ''))
    if not numbers:
        return ""

    income = float(numbers[0])
    if income < 10000:
        income *= 100000  # Convert lakhs to rupees

    if income < 300000:
        return f"💰 Income: ₹{income:,.0f}\nTax: *₹0* (below ₹3L exempt)\n\nNo tax! 🎉"

    # New regime 2024-25 slabs
    tax = 0
    slabs = [
        (300000, 0), (600000, 0.05), (900000, 0.10),
        (1200000, 0.15), (1500000, 0.20), (float('inf'), 0.30),
    ]

    remaining = income
    prev = 0
    breakdown = []
    for limit, rate in slabs:
        if remaining <= 0:
            break
        slab_amount = min(remaining, limit - prev)
        slab_tax = slab_amount * rate
        tax += slab_tax
        if rate > 0:
            breakdown.append(f"  ₹{prev:,.0f}-{min(limit, income):,.0f} @ {int(rate*100)}%: ₹{slab_tax:,.0f}")
        remaining -= slab_amount
        prev = limit

    cess = tax * 0.04
    total = tax + cess

    result = (
        f"💰 *Income Tax Calculator (New Regime):*\n\n"
        f"Income: ₹{income:,.0f}\n\n"
        f"*Slabs:*\n"
        + "\n".join(breakdown) + "\n\n"
        f"Tax: ₹{tax:,.0f}\n"
        f"Cess (4%): ₹{cess:,.0f}\n"
        f"*Total Tax: ₹{total:,.0f}*"
    )
    return result


# ── Bhagavad Gita Shloka ──────────────────────────────────────
async def gita_shloka(query: str, context: dict = None) -> str:
    """Get a Bhagavad Gita shloka with translation."""
    import httpx as hx
    import random

    chapter = random.randint(1, 18)
    verse = random.randint(1, 20)

    try:
        async with hx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://bhagavadgitaapi.in/slok/{chapter}/{verse}")
            if resp.status_code == 200:
                data = resp.json()
                sanskrit = data.get("slok", "")
                hindi = data.get("tej", {}).get("ht", "") if isinstance(data.get("tej"), dict) else ""
                english = data.get("spicer", {}).get("et", "") if isinstance(data.get("spicer"), dict) else ""

                return (
                    f"🙏 *Bhagavad Gita — Chapter {chapter}, Verse {verse}:*\n\n"
                    f"_{sanskrit[:200]}_\n\n"
                    f"*Hindi:* {hindi[:200]}\n"
                    f"*English:* {english[:200]}"
                )
    except Exception:
        pass
    return "🙏 Gita shloka abhi fetch nahi ho raha. 'Karmanye vadhikaraste ma phaleshu kadachan' — Bhagavad Gita"


# ── Wikipedia Summary ──────────────────────────────────────────
async def wiki_summary(query: str, context: dict = None) -> str:
    """Get Wikipedia article summary."""
    import httpx as hx
    import re

    # Extract topic
    topic = re.sub(r'(wikipedia|wiki|about|tell me about|kya hai|ke baare mein|batao)', '', query.lower()).strip()
    if not topic or len(topic) < 3:
        return ""

    import urllib.parse
    topic_encoded = urllib.parse.quote(topic.replace(' ', '_'))
    try:
        async with hx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic_encoded}",
                headers={"User-Agent": "Samva/1.0 (https://samva.in; sgroy10@gmail.com) WhatsApp-AI-Assistant"}
            )
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", topic)
                extract = data.get("extract", "")[:400]
                return f"📖 *{title}:*\n\n{extract}"
    except Exception:
        pass
    return ""


# ── FD/RD Calculator ──────────────────────────────────────────
async def fd_calculator(query: str, context: dict = None) -> str:
    """Calculate Fixed Deposit returns."""
    import re

    numbers = re.findall(r'[\d,.]+', query.replace(',', ''))
    if len(numbers) < 2:
        return ""

    amount = float(numbers[0])
    rate = float(numbers[1])
    years = float(numbers[2]) if len(numbers) > 2 else 1

    if amount < 100:
        return ""

    # Quarterly compounding (most Indian banks)
    n = 4  # quarters per year
    maturity = amount * (1 + rate / (n * 100)) ** (n * years)
    interest = maturity - amount

    return (
        f"🏦 *FD Calculator:*\n\n"
        f"Principal: ₹{amount:,.0f}\n"
        f"Rate: {rate}% p.a.\n"
        f"Tenure: {years:.0f} year(s)\n\n"
        f"Interest: ₹{interest:,.0f}\n"
        f"*Maturity: ₹{maturity:,.0f}*"
    )


# ── Phone Number Validator ────────────────────────────────────
async def phone_validator(query: str, context: dict = None) -> str:
    """Validate and identify Indian phone numbers."""
    import re

    # Find 10-digit Indian number
    phone_match = re.search(r'(?:\+91|91|0)?(\d{10})', query.replace(' ', ''))
    if not phone_match:
        return ""

    number = phone_match.group(1)
    first4 = number[:4]

    # Indian mobile operators by prefix (approximate)
    operators = {
        "6": "Jio/Airtel/Vi", "7": "Airtel/Jio/BSNL",
        "8": "Airtel/Jio/Vi", "9": "Airtel/Vi/BSNL",
    }

    op = operators.get(number[0], "Unknown")
    is_mobile = number[0] in "6789"

    return (
        f"📞 *Phone: +91 {number[:5]} {number[5:]}*\n\n"
        f"Type: {'Mobile' if is_mobile else 'Landline'}\n"
        f"Operator: {op} (approx)\n"
        f"Valid: {'✅' if len(number) == 10 and is_mobile else '⚠️ Check'}"
    )


# ── REAL Vedic Astrology (PyJHora + Swiss Ephemeris) ───────────
async def panchang_info(query: str, context: dict = None) -> str:
    """REAL Vedic Panchang — calculated from Swiss Ephemeris, not hardcoded."""
    from datetime import datetime
    import pytz

    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    query_lower = query.lower()

    try:
        import swisseph as swe
        from jhora.panchanga import drik

        # Default place: user's city or Mumbai
        place = drik.Place("Mumbai", 19.076, 72.8777, 5.5)
        jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute / 60.0)

        # Rahu Kaal (standard weekday-based)
        weekday = now.weekday()
        rahu_kaal = {
            0: "7:30-9:00 AM", 1: "3:00-4:30 PM", 2: "12:00-1:30 PM",
            3: "1:30-3:00 PM", 4: "10:30 AM-12:00 PM", 5: "9:00-10:30 AM", 6: "4:30-6:00 PM",
        }

        if any(w in query_lower for w in ["rahu", "rahu kaal", "rahu kal"]):
            return (
                f"🕉️ *Aaj ka Rahu Kaal ({now.strftime('%A')}):*\n\n"
                f"⏰ {rahu_kaal[weekday]}\n\n"
                f"Rahu Kaal mein naye kaam avoid karein."
            )

        # Full Panchang
        tithi_data = drik.tithi(jd, place)
        nak_data = drik.nakshatra(jd, place)

        tithi_names = ["Pratipada","Dwitiya","Tritiya","Chaturthi","Panchami","Shashthi","Saptami",
                       "Ashtami","Navami","Dashami","Ekadashi","Dwadashi","Trayodashi","Chaturdashi","Purnima",
                       "Pratipada","Dwitiya","Tritiya","Chaturthi","Panchami","Shashthi","Saptami",
                       "Ashtami","Navami","Dashami","Ekadashi","Dwadashi","Trayodashi","Chaturdashi","Amavasya"]
        nak_names = ["Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu",
                     "Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni","Hasta","Chitra",
                     "Swati","Vishakha","Anuradha","Jyeshtha","Mula","Purva Ashadha","Uttara Ashadha",
                     "Shravana","Dhanishta","Shatabhisha","Purva Bhadrapada","Uttara Bhadrapada","Revati"]

        tithi_num = tithi_data[0]
        paksha = "Shukla" if tithi_num <= 15 else "Krishna"
        tithi_name = tithi_names[tithi_num - 1] if 1 <= tithi_num <= 30 else f"T{tithi_num}"

        nak_num = nak_data[0]
        nak_name = nak_names[nak_num] if 0 <= nak_num < 27 else f"N{nak_num}"
        pada = nak_data[1]

        return (
            f"🕉️ *Aaj ka Panchang ({now.strftime('%d %B %Y, %A')}):*\n\n"
            f"▸ Tithi: {paksha} {tithi_name}\n"
            f"▸ Nakshatra: {nak_name} (Pada {pada})\n"
            f"▸ Rahu Kaal: {rahu_kaal[weekday]}\n\n"
            f"_(Swiss Ephemeris se calculated — astronomical accuracy)_"
        )
    except ImportError:
        # Fallback if PyJHora not installed on server
        weekday = now.weekday()
        rahu = {0: "7:30-9:00 AM", 1: "3:00-4:30 PM", 2: "12:00-1:30 PM",
                3: "1:30-3:00 PM", 4: "10:30 AM-12:00 PM", 5: "9:00-10:30 AM", 6: "4:30-6:00 PM"}
        return f"🕉️ *Rahu Kaal ({now.strftime('%A')}):* {rahu[weekday]}"
    except Exception as e:
        return f"🕉️ Panchang check kar rahi hoon... ({str(e)[:50]})"


async def kundli_generator(query: str, context: dict = None) -> str:
    """Generate REAL Vedic Kundli from date/time/place using Swiss Ephemeris."""
    import re
    from datetime import datetime

    query_lower = query.lower()

    # Extract date: DD/MM/YYYY or DD-MM-YYYY or "15 march 1990"
    date_match = re.search(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})', query)
    if not date_match:
        return ""

    day, month, year = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))

    # Extract time: HH:MM or "10:30" or "10:30am"
    time_match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', query_lower)
    hour, minute = 12, 0
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if time_match.group(3) == 'pm' and hour < 12:
            hour += 12
        elif time_match.group(3) == 'am' and hour == 12:
            hour = 0

    # Extract city (default Mumbai)
    cities = {
        "mumbai": (19.076, 72.878, 5.5), "delhi": (28.614, 77.209, 5.5),
        "bangalore": (12.972, 77.594, 5.5), "chennai": (13.083, 80.270, 5.5),
        "kolkata": (22.572, 88.364, 5.5), "hyderabad": (17.385, 78.487, 5.5),
        "pune": (18.520, 73.857, 5.5), "jaipur": (26.912, 75.787, 5.5),
        "ahmedabad": (23.023, 72.571, 5.5), "surat": (21.170, 72.831, 5.5),
        "lucknow": (26.847, 80.947, 5.5), "nagpur": (21.146, 79.088, 5.5),
    }

    city_name = "Mumbai"
    lat, lon, tz = 19.076, 72.878, 5.5
    for c, coords in cities.items():
        if c in query_lower:
            city_name = c.title()
            lat, lon, tz = coords
            break

    try:
        import swisseph as swe
        from jhora.panchanga import drik

        place = drik.Place(city_name, lat, lon, tz)
        jd = swe.julday(year, month, day, hour + minute / 60.0)

        rashi_names = ["Mesha (♈)", "Vrishabha (♉)", "Mithuna (♊)", "Karka (♋)",
                       "Simha (♌)", "Kanya (♍)", "Tula (♎)", "Vrischika (♏)",
                       "Dhanu (♐)", "Makara (♑)", "Kumbha (♒)", "Meena (♓)"]

        planet_names = ["Surya", "Chandra", "Mangal", "Budh", "Guru", "Shukra", "Shani"]
        planet_ids = [swe.SUN, swe.MOON, swe.MARS, swe.MERCURY, swe.JUPITER, swe.VENUS, swe.SATURN]

        swe.set_sid_mode(swe.SIDM_LAHIRI)
        ayan = swe.get_ayanamsa_ex(jd, swe.FLG_SIDEREAL)[1]

        lines = [
            f"🕉️ *KUNDLI — Vedic Birth Chart*\n",
            f"📅 {day:02d}/{month:02d}/{year} | ⏰ {hour:02d}:{minute:02d} | 📍 {city_name}\n",
        ]

        # Ascendant
        asc = drik.ascendant(jd, place)
        lines.append(f"\n*Lagna:* {rashi_names[asc[0]]} ({asc[1]:.1f}°)")

        # Planets
        lines.append("\n*Graha Sthiti:*")
        for pid, pname in zip(planet_ids, planet_names):
            lon_val = swe.calc_ut(jd, pid)[0][0]
            sid_lon = (lon_val - ayan) % 360
            rashi_idx = int(sid_lon / 30)
            degrees = sid_lon % 30
            lines.append(f"  {pname}: {rashi_names[rashi_idx]} {degrees:.1f}°")

        # Rahu/Ketu
        rahu_lon = swe.calc_ut(jd, swe.MEAN_NODE)[0][0]
        rahu_sid = (rahu_lon - ayan) % 360
        lines.append(f"  Rahu: {rashi_names[int(rahu_sid / 30)]} {rahu_sid % 30:.1f}°")
        ketu_sid = (rahu_sid + 180) % 360
        lines.append(f"  Ketu: {rashi_names[int(ketu_sid / 30)]} {ketu_sid % 30:.1f}°")

        # Tithi & Nakshatra
        tithi_data = drik.tithi(jd, place)
        nak_data = drik.nakshatra(jd, place)

        tithi_names_list = ["Pratipada","Dwitiya","Tritiya","Chaturthi","Panchami","Shashthi","Saptami",
                           "Ashtami","Navami","Dashami","Ekadashi","Dwadashi","Trayodashi","Chaturdashi","Purnima",
                           "Pratipada","Dwitiya","Tritiya","Chaturthi","Panchami","Shashthi","Saptami",
                           "Ashtami","Navami","Dashami","Ekadashi","Dwadashi","Trayodashi","Chaturdashi","Amavasya"]
        nak_names_list = ["Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu",
                         "Pushya","Ashlesha","Magha","P.Phalguni","U.Phalguni","Hasta","Chitra",
                         "Swati","Vishakha","Anuradha","Jyeshtha","Mula","P.Ashadha","U.Ashadha",
                         "Shravana","Dhanishta","Shatabhisha","P.Bhadrapada","U.Bhadrapada","Revati"]

        t_num = tithi_data[0]
        paksha = "Shukla" if t_num <= 15 else "Krishna"
        t_name = tithi_names_list[t_num - 1] if 1 <= t_num <= 30 else f"T{t_num}"

        n_num = nak_data[0]
        n_name = nak_names_list[n_num] if 0 <= n_num < 27 else f"N{n_num}"

        lines.append(f"\n*Tithi:* {paksha} {t_name}")
        lines.append(f"*Nakshatra:* {n_name} (Pada {nak_data[1]})")

        # Mangal Dosh check (basic)
        mars_sid = (swe.calc_ut(jd, swe.MARS)[0][0] - ayan) % 360
        mars_house = (int(mars_sid / 30) - asc[0]) % 12 + 1
        mangal_dosh = mars_house in [1, 2, 4, 7, 8, 12]
        lines.append(f"\n*Mangal Dosh:* {'⚠️ Hai (Mars in house {mars_house})' if mangal_dosh else '✅ Nahi hai'}")

        lines.append(f"\n_(Swiss Ephemeris + Lahiri Ayanamsa)_")

        return "\n".join(lines)

    except ImportError:
        return "🕉️ Kundli generation ke liye server pe PyJHora + Swiss Ephemeris chahiye."
    except Exception as e:
        return f"🕉️ Kundli error: {str(e)[:100]}"


# ══════════════════════════════════════════════════════════════════
# SKILL REGISTRY — the routing table the orchestrator uses
# ══════════════════════════════════════════════════════════════════

SKILL_REGISTRY = [
    # ── IFSC Lookup (BEFORE stocks so IFSC codes don't match as stock names)
    {
        "name": "ifsc",
        "description": "Bank branch details from IFSC code",
        "keywords": ["ifsc", "bank branch", "branch code"],
        "vertical": "universal",
        "execute": ifsc_lookup,
    },
    # ── Pincode (expanded keywords) ──────────────────────────
    {
        "name": "pincode",
        "description": "Area details from Indian pincode",
        "keywords": ["pincode", "pin code", "postal code", "area code",
                      "400001", "110001", "560001", "ka area", "ka pincode"],
        "vertical": "universal",
        "execute": pincode_lookup,
    },
    # ── Flights ──────────────────────────────────────────────
    {
        "name": "flights",
        "description": "Search flights between cities",
        "keywords": ["flight", "fly", "airplane", "airport", "udaan",
                      "mumbai to", "delhi to", "bangalore to", "chennai to",
                      "flight book", "ticket book", "plane ticket", "hawa jahaaz"],
        "vertical": "universal",
        "execute": flight_search,
    },
    # ── Trains / IRCTC ───────────────────────────────────────
    {
        "name": "trains",
        "description": "Indian Railways — PNR, train search, booking help",
        "keywords": ["train", "railway", "irctc", "pnr", "rail", "station",
                      "tatkal", "waiting list", "rac", "train ticket",
                      "rajdhani", "shatabdi", "duronto", "garibrath"],
        "vertical": "universal",
        "execute": train_info,
    },
    # ── Gold/Silver Rate (calls existing gold.py service) ──
    {
        "name": "gold_rate",
        "description": "Live gold, silver, platinum rates",
        "keywords": ["gold rate", "sona", "sone ka", "gold price", "gold bhav",
                      "silver rate", "chandi", "platinum rate", "sona kitne ka",
                      "22k rate", "24k rate", "18k rate", "gold batao"],
        "vertical": "universal",
        "execute": gold_rate_skill,
    },
    # ── Finance (MF + Crypto BEFORE stocks — keyword priority) ─
    {
        "name": "mutual_fund",
        "description": "Mutual fund NAV from AMFI/mftool",
        "keywords": ["mutual fund", "nav check", "sip", "mf nav", "mutual fund nav",
                      "fund nav", "fund ka nav", "fund return"],
        "vertical": "universal",
        "execute": mutual_fund,
    },
    {
        "name": "crypto",
        "description": "Cryptocurrency prices in INR",
        "keywords": ["bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
                      "dogecoin", "doge", "solana", "xrp", "ripple"],
        "vertical": "universal",
        "execute": crypto_price,
    },
    # ── Indian Stocks ────────────────────────────────────────
    {
        "name": "indian_stocks",
        "description": "Live NSE/BSE stock prices",
        "keywords": ["stock", "share", "nifty", "sensex", "nse", "bse",
                      "reliance", "tcs", "infosys", "hdfc", "icici", "sbi",
                      "wipro", "itc", "adani", "tata motors", "maruti",
                      "bajaj", "hcl", "titan", "kotak", "axis bank"],
        "vertical": "universal",
        "execute": indian_stocks,
    },
    # ── EMI Calculator ───────────────────────────────────────
    {
        "name": "emi",
        "description": "Loan EMI calculation",
        "keywords": ["emi", "loan calculate", "loan emi", "home loan", "car loan",
                      "personal loan", "emi kitna", "emi calculator"],
        "vertical": "universal",
        "execute": emi_calculator,
    },
    # ── BMI Calculator ───────────────────────────────────────
    {
        "name": "bmi",
        "description": "Body Mass Index calculator",
        "keywords": ["bmi", "body mass", "weight check", "mota", "patla",
                      "overweight", "underweight"],
        "vertical": "universal",
        "execute": bmi_calculator,
    },
    # ── Age Calculator ───────────────────────────────────────
    {
        "name": "age",
        "description": "Calculate age from date of birth",
        "keywords": ["age calculate", "age calculator", "umar", "born on",
                      "date of birth", "dob", "kitne saal"],
        "vertical": "universal",
        "execute": age_calculator,
    },
    # ── GST Calculator ───────────────────────────────────────
    {
        "name": "gst",
        "description": "GST calculation on any amount",
        "keywords": ["gst calculate", "gst on", "gst kitna", "cgst", "sgst",
                      "gst amount", "tax calculate"],
        "vertical": "universal",
        "execute": gst_calculator,
    },
    # ── Fun & Daily ──────────────────────────────────────────
    {
        "name": "joke",
        "description": "Hindi jokes — instant mood lifter",
        "keywords": ["joke", "jokes", "chutkula", "mazak", "funny", "hasi",
                      "mast joke", "joke sunao", "hasao"],
        "vertical": "universal",
        "execute": hindi_joke,
    },
    {
        "name": "quote",
        "description": "Motivational quotes in Hindi/English",
        "keywords": ["quote", "vichar", "suvichar", "motivational", "motivation",
                      "inspirational", "thought of the day", "quote of the day"],
        "vertical": "universal",
        "execute": daily_quote,
    },
    # ── Tools ────────────────────────────────────────────────
    {
        "name": "qr_code",
        "description": "Generate QR code for any text or URL",
        "keywords": ["qr code", "qr bana", "qr generate", "qr create"],
        "vertical": "universal",
        "execute": qr_generator,
    },
    # ── Cricket ──────────────────────────────────────────────
    {
        "name": "cricket",
        "description": "Live cricket scores",
        "keywords": ["cricket", "score", "ipl", "match", "batting", "bowling",
                      "cricket score", "live score", "india match"],
        "vertical": "universal",
        "execute": cricket_score,
    },
    # ── Translation ──────────────────────────────────────────
    {
        "name": "translate",
        "description": "Translate Hindi ↔ English + Indian languages",
        "keywords": ["translate", "translation", "hindi mein", "english mein",
                      "ka hindi", "ka english", "matlab kya", "meaning of"],
        "vertical": "universal",
        "execute": translate_text,
    },
    # ── Air Quality ──────────────────────────────────────────
    {
        "name": "aqi",
        "description": "Air quality index for Indian cities",
        "keywords": ["air quality", "aqi", "pollution", "pradushan", "pm2.5",
                      "hawa kaisi", "mask lagana"],
        "vertical": "universal",
        "execute": air_quality,
    },
    # ── Holidays ─────────────────────────────────────────────
    {
        "name": "holidays",
        "description": "Upcoming Indian holidays",
        "keywords": ["holiday", "chutti", "bank holiday", "gazetted holiday",
                      "next holiday", "upcoming holiday", "public holiday"],
        "vertical": "universal",
        "execute": indian_holiday,
    },
    # ── Income Tax ───────────────────────────────────────────
    {
        "name": "income_tax",
        "description": "Indian income tax calculator (new regime)",
        "keywords": ["income tax", "tax calculate", "tax kitna", "tax slab",
                      "income par tax", "salary tax"],
        "vertical": "universal",
        "execute": income_tax,
    },
    # ── Bhagavad Gita ────────────────────────────────────────
    {
        "name": "gita",
        "description": "Random Bhagavad Gita shloka with Hindi/English translation",
        "keywords": ["gita shloka", "bhagavad gita", "shloka sunao", "geeta ka",
                      "gita verse", "krishna ne kya kaha", "bhagwan krishna"],
        "vertical": "universal",
        "execute": gita_shloka,
    },
    # ── Wikipedia ────────────────────────────────────────────
    {
        "name": "wikipedia",
        "description": "Wikipedia article summaries",
        "keywords": ["wikipedia", "wiki", "ke baare mein batao", "kya hai yeh",
                      "tell me about", "who is", "what is"],
        "vertical": "universal",
        "execute": wiki_summary,
    },
    # ── FD Calculator ────────────────────────────────────────
    {
        "name": "fd_calc",
        "description": "Fixed Deposit returns calculator",
        "keywords": ["fd calculate", "fixed deposit", "fd kitna", "fd returns",
                      "fd interest", "fd maturity"],
        "vertical": "universal",
        "execute": fd_calculator,
    },
    # ── Phone Validator ──────────────────────────────────────
    {
        "name": "phone",
        "description": "Validate Indian phone numbers",
        "keywords": ["phone number", "mobile number", "phone check", "number validate",
                      "kis ka number", "operator check"],
        "vertical": "universal",
        "execute": phone_validator,
    },
    # ── Indian Spiritual ─────────────────────────────────────
    {
        "name": "panchang",
        "description": "REAL Vedic Panchang — Tithi, Nakshatra, Rahu Kaal from Swiss Ephemeris",
        "keywords": ["rahu kaal", "rahu kal", "panchang", "tithi", "muhurat",
                      "shubh muhurat", "nakshatra", "rahu", "kaal"],
        "vertical": "universal",
        "execute": panchang_info,
    },
    {
        "name": "kundli",
        "description": "REAL Vedic Kundli — birth chart with planetary positions, Mangal Dosh check",
        "keywords": ["kundli", "kundali", "birth chart", "janam patri", "janam kundli",
                      "horoscope", "rashi", "graha", "mangal dosh"],
        "vertical": "universal",
        "execute": kundli_generator,
    },
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
                      "THB", "SGD", "JPY", "CAD", "AUD", "CNY", "SAR", "KWD",
                      "to INR", "to USD", "kitne rupees", "dollars", "dirhams", "pounds",
                      "baht", "yen", "yuan", "riyal", "dinar"],
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
        "keywords": ["render", "design banao", "design dikhao", "concept",
                      "generate design", "jewelry design", "ring design",
                      "ring banao", "necklace banao", "pendant banao",
                      "bracelet banao", "jewellery banao", "jewelry banao"],
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
        "keywords": ["panchang", "tithi", "nakshatra", "karana",
                      "aaj ka panchang", "hindu calendar", "panchangam",
                      "panchang yoga", "aaj ka yoga karana"],
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
        # Use word boundary matching for short keywords to avoid substring false positives
        # e.g. "emi" should not match inside "remind", "ad" not inside "bad"
        matched = False
        for kw in skill["keywords"]:
            kw_lower = kw.lower()
            if len(kw_lower) <= 4:
                # Short keyword — require word boundary
                if re.search(r'\b' + re.escape(kw_lower) + r'\b', query_lower):
                    matched = True
                    break
            else:
                if kw_lower in query_lower:
                    matched = True
                    break
        if matched:
            try:
                result = await skill["execute"](query, context)
                if result and not result.startswith("__"):
                    logger.info(f"Prebuilt skill matched: {skill['name']}")
                    return result
                elif result and result.startswith("__"):
                    return result
                else:
                    # Skill matched but returned empty — log and continue to next layer
                    logger.warning(f"Prebuilt skill {skill['name']} matched but returned empty for: {query[:50]}")
                    continue
            except Exception as e:
                logger.error(f"Prebuilt skill {skill['name']} crashed: {e}")
                continue

    return ""
