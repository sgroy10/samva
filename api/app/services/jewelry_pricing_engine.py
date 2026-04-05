"""
Jewelry Pricing Engine — ported from JewelClaw V2.
Complete pricing constants, diamond rates, labor tables, and cost calculator.

Source: JewelClaw apps/core-api/app/services/pricing_data.py + vision_service.py + gold_service.py
All base rates in USD unless noted. Convert to INR at runtime using live forex.

Usage:
  from app.services.jewelry_pricing_engine import (
      calculate_full_jewelry_cost,
      get_labor_cost, get_setting_cost, get_diamond_rate_by_sieve,
      get_diamond_rate_by_grade, get_extras_cost, mm_to_sieve,
  )
"""

import logging
import re
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("samva.pricing_engine")


# ══════════════════════════════════════════════════════════════════
# CONSTANTS — copied exactly from JewelClaw pricing_data.py
# ══════════════════════════════════════════════════════════════════

# ── Metal Loss ────────────────────────────────────────────────────
GOLD_LOSS_PCT = 9.0    # 9% gold loss in manufacturing
SILVER_LOSS_PCT = 12.0  # 12% silver loss in manufacturing

# ── GST ───────────────────────────────────────────────────────────
GST_PCT = 3.0  # 3% GST on (metal + making)

# ── Default USD/INR rate (updated at runtime from forex) ─────────
DEFAULT_USD_INR = 83.50  # fallback if forex unavailable

# ── Purity Multipliers ───────────────────────────────────────────
PURITY_MULTIPLIERS = {
    "24K": 0.999,
    "22K": 0.916,
    "18K": 0.750,
    "14K": 0.585,
    "10K": 0.417,
    "9K":  0.375,
}

# Troy ounce to gram
TROY_OZ_TO_GRAM = 31.1035

# ── Gold Labor — Casting, Filing, Polishing (USD) ─────────────────
# Structure: {jewelry_type: [(max_weight_gms, unit, price_usd), ...]}
# Weight ranges are inclusive upper bounds. "per_gm" means rate x weight.

GOLD_LABOR = {
    "ring": [
        (2.50, "per_piece", 5.50),
        (6.00, "per_piece", 6.50),
        (9999, "per_gm",    1.20),   # > 6.01 gms
    ],
    "pendant": [
        (2.50, "per_piece", 5.50),
        (6.00, "per_piece", 6.50),
        (9999, "per_gm",    1.20),
    ],
    "earring": [
        (3.50, "per_pair", 6.00),
        (7.00, "per_pair", 7.00),
        (9999, "per_gm",   1.50),   # > 7.01 gms
    ],
    "bangle": [
        (15.0, "per_piece", 20.00),
        (9999, "per_piece", 25.00),
    ],
    "bracelet": [
        (15.0, "per_piece", 20.00),
        (9999, "per_piece", 25.00),
    ],
}

# Additional gold charges (USD) per piece unless noted
GOLD_EXTRAS = {
    "two_tone":      1.00,   # per piece
    "rhodium_ring":  2.50,   # per piece (ring/pendant)
    "rhodium_pendant": 2.50,
    "rhodium_earring": 3.50, # per pair
    "rhodium_bangle_small": 7.00,   # < 10 gms
    "rhodium_bangle_large": 12.00,  # > 10 gms
    "stamping_ring":    0.50,
    "stamping_pendant": 0.50,
    "stamping_earring": 0.40,
    "stamping_bangle":  5.00,
    "solder":        0.50,   # per piece
    "special_finish": 1.00,
}

# ── Silver Labor — Casting, Filing, Polishing (USD) ──────────────

SILVER_LABOR = {
    "ring": [
        (2.50, "per_piece", 4.50),
        (6.00, "per_piece", 5.50),
        (9999, "per_gm",    1.00),
    ],
    "pendant": [
        (2.50, "per_piece", 4.50),
        (6.00, "per_piece", 5.50),
        (9999, "per_gm",    1.00),
    ],
    "earring": [
        (3.50, "per_pair", 5.00),
        (7.00, "per_pair", 6.00),
        (9999, "per_gm",   1.20),
    ],
    # Bangle/bracelet rates not available for silver
    "bangle":   [],
    "bracelet": [],
}

SILVER_EXTRAS = {
    "two_tone":      1.00,
    "rhodium_ring":  2.00,
    "rhodium_pendant": 2.00,
    "rhodium_earring": 2.50,
    "stamping_ring":    0.50,
    "stamping_pendant": 0.50,
    "stamping_earring": 0.40,
    "solder":        0.50,
    "special_finish": 1.00,
}

# ── Setting Charges (USD per stone) ───────────────────────────────
# Structure: {setting_type: {"hand": price, "wax": price}}

GOLD_SETTING_CHARGES = {
    "pave":             {"hand": 0.25, "wax": 0.20},
    "prong":            {"hand": 0.25, "wax": 0.20},
    "baguette_small":   {"hand": None, "wax": 0.25},   # 2mm and below
    "baguette_large":   {"hand": None, "wax": 0.40},   # above 2mm
    "princess_small":   {"hand": None, "wax": 0.25},
    "princess_large":   {"hand": None, "wax": 0.40},
    "taper_small":      {"hand": None, "wax": 0.25},
    "taper_large":      {"hand": None, "wax": 0.40},
    "micro_pave":       {"hand": 0.35, "wax": None},
    "princess_invisible": {"hand": None, "wax": 0.50},
    "pressure":         {"hand": None, "wax": 0.35},
    "channel_small":    {"hand": 0.35, "wax": 0.20},   # 2mm and below
    "channel_large":    {"hand": 0.45, "wax": 0.25},   # above 2mm
    "bezel_small":      {"hand": 0.35, "wax": 0.20},
    "bezel_large":      {"hand": 0.45, "wax": 0.25},
    "flush_small":      {"hand": 0.35, "wax": 0.20},
    "flush_large":      {"hand": 0.45, "wax": 0.25},
    "nick_small":       {"hand": 0.35, "wax": 0.20},
    "nick_large":       {"hand": 0.45, "wax": 0.25},
    "center_stone_small": {"hand": 0.50, "wax": None},  # below 3mm
    "center_stone_large": {"hand": 1.00, "wax": None},  # above 3mm
    "pointer_small":    {"hand": 0.50, "wax": None},    # 0.10-0.25 cts
    "pointer_large":    {"hand": 1.00, "wax": None},    # 0.25+ cts
    "preset_miracle":   {"hand": 0.11, "wax": None},    # miracle plate setting
    "preset_labour":    {"hand": 0.70, "wax": None},    # miracle plate labour
}

SILVER_SETTING_CHARGES = {
    "pave":             {"hand": None, "wax": 0.08},
    "prong":            {"hand": None, "wax": 0.08},
    "baguette_small":   {"hand": None, "wax": 0.15},
    "channel_small":    {"hand": None, "wax": 0.15},
    "bezel_small":      {"hand": None, "wax": 0.15},
    "center_stone_small": {"hand": 0.15, "wax": None},
    "center_stone_large": {"hand": 0.50, "wax": None},
    "pointer_small":    {"hand": 0.50, "wax": None},
    "preset_miracle":   {"hand": 0.08, "wax": None},
    "preset_labour":    {"hand": 0.65, "wax": None},
}

# ── Other Standard Charges (USD) ─────────────────────────────────
MODEL_COST_USD = 50.0       # per new model/design
CPX_COST_USD = 6.0          # per reference (CAD)
FLASH_COST_USD = 1.0        # flash/rhodium flash

# ── Diamond Rates by Sieve Size (USD per carat) ──────────────────
# Source: Kiara 2023 selling price chart
# Quality: I1 clarity
# Types: FC = Full Cut, SC = Single Cut
# Color: WHITE and TTLB (Top Top Light Brown)

DIAMOND_RATES_SIEVE = [
    # (fraction, mm, sieve, fc_white, fc_ttlb, sc_white, sc_ttlb)
    ("-2",    0.80, "+0000-000",  415, 300, 230, 180),
    ("-2",    0.90, "+000-00",    415, 300, 230, 180),
    ("-2",    1.00, "+00-0",      415, 300, 230, 180),
    ("-2",    1.10, "+0-1",       405, 290, 245, 205),
    ("-2",    1.15, "+1-1.5",     405, 290, 245, 205),
    ("-2",    1.20, "+1.5-2.0",   405, 290, 245, 205),
    ("Star",  1.30, "+2.0-3.0",   395, 325, 245, 205),
    ("Star",  1.40, "+3.0-4.0",   395, 325, 245, 205),
    ("Star",  1.50, "+4.0-5.0",   390, 320, None, None),
    ("Star",  1.60, "+5.0-6.0",   390, 320, None, None),
    ("Star",  1.70, "+6.0-6.5",   390, 320, None, None),
    ("Melle", 1.80, "+6.5-7.0",   385, 315, None, None),
    ("Melle", 1.90, "+7.0-7.5",   385, 315, None, None),
    ("Melle", 2.00, "+7.5-8.0",   385, 315, None, None),
    ("Melle", 2.10, "+8.0-8.5",   440, 345, None, None),
    ("Melle", 2.20, "+8.5-9.0",   440, 345, None, None),
    ("Melle", 2.30, "+9.0-9.5",   450, 355, None, None),
    ("Melle", 2.40, "+9.5-10.0",  450, 355, None, None),
    ("Melle", 2.50, "+10-10.5",   460, 365, None, None),
    ("Melle", 2.60, "+10.5-11",   460, 365, None, None),
]

# Buy prices (for margin calculations)
DIAMOND_BUY_RATES_SIEVE = [
    # (mm, fc_white_buy, fc_ttlb_buy, sc_white_buy, sc_ttlb_buy)
    (0.80, 363, 265, 170, 140),
    (0.90, 363, 265, 190, 150),
    (1.00, 363, 265, 190, 150),
    (1.10, 363, 265, 205, 170),
    (1.15, 363, 265, 205, 170),
    (1.20, 363, 265, 205, 170),
    (1.30, 345, 285, 205, 170),
    (1.40, 345, 285, 205, 170),
    (1.50, 345, 285, None, None),
    (1.60, 345, 285, None, None),
    (1.70, 345, 285, None, None),
    (1.80, 345, 285, None, None),
    (1.90, 345, 285, None, None),
    (2.00, 345, 285, None, None),
    (2.10, 393, 285, None, None),
    (2.20, 393, 285, None, None),
    (2.30, 393, 285, None, None),
    (2.40, 393, 285, None, None),
    (2.50, 393, 285, None, None),
    (2.60, 393, 285, None, None),
]

# Average margins by type
DIAMOND_AVG_MARGINS = {
    "fc_white": 13,    # %
    "fc_ttlb": 16,
    "sc_white": 22,
    "sc_ttlb": 21,
}

# ── Diamond Rates by Grade (INR per carat) ───────────────────────
# Source: JewelClaw vision_service.py — higher quality stones
# Used when GemLens returns color/clarity grades but no sieve/mm

DIAMOND_RATES_PER_CT = {
    ("D-E", "IF-VVS1"):    90000,
    ("D-E", "VVS1-VVS2"):  75000,
    ("D-E", "VS1-VS2"):    55000,
    ("D-E", "SI1-SI2"):    35000,
    ("F-G", "IF-VVS1"):    70000,
    ("F-G", "VVS1-VVS2"):  55000,
    ("F-G", "VS1-VS2"):    42000,
    ("F-G", "SI1-SI2"):    28000,
    ("G-H", "IF-VVS1"):    55000,
    ("G-H", "VVS1-VVS2"):  42000,
    ("G-H", "VS1-VS2"):    32000,
    ("G-H", "VS-SI"):      28000,
    ("G-H", "SI1-SI2"):    20000,
    ("H-I", "VS1-VS2"):    25000,
    ("H-I", "VS-SI"):      22000,
    ("H-I", "SI1-SI2"):    16000,
    ("I-J", "VS1-VS2"):    18000,
    ("I-J", "SI1-SI2"):    12000,
}

DIAMOND_FALLBACK_RATE = 30000  # INR/ct for unknown grade small diamonds

# ── Gram-wise Pricing Model Defaults (INR) ───────────────────────
# Model 2: Job work pricing per gram (inclusive of gold loss)
GRAMWISE_DEFAULTS = {
    "gold_per_gram_inr": 750,      # INR/gram (includes gold loss)
    "diamond_handling_per_ct_inr": 1500,  # INR/carat for diamond setting
}

# ── Plain Gold Model Defaults ────────────────────────────────────
# Model 3: Gold + flat % (no itemized labor)
PLAIN_GOLD_DEFAULTS = {
    "domestic_pct": 7.0,     # gold + 7% all-inclusive (India domestic)
    "dubai_pct": 2.0,        # gold + 2% (Dubai/export)
}


# ══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS — copied exactly from JewelClaw
# ══════════════════════════════════════════════════════════════════

def get_labor_cost(jewelry_type: str, weight_grams: float, metal: str = "gold") -> dict:
    """
    Get standard labor (casting/filing/polishing) cost for a piece.
    Returns: {cost_usd, unit, tier_desc, jewelry_type, weight_grams}
    """
    jtype = jewelry_type.lower().strip()
    # Normalize aliases
    aliases = {
        "rings": "ring", "pendants": "pendant", "earrings": "earring",
        "bangles": "bangle", "bracelets": "bracelet", "necklace": "pendant",
        "chain": "pendant", "mangalsutra": "pendant",
    }
    jtype = aliases.get(jtype, jtype)

    table = GOLD_LABOR if metal.lower() == "gold" else SILVER_LABOR
    tiers = table.get(jtype, [])

    if not tiers:
        # Unknown type — estimate using ring rates
        tiers = table.get("ring", [])

    for max_wt, unit, price in tiers:
        if weight_grams <= max_wt or max_wt >= 9999:
            if unit == "per_gm":
                cost = price * weight_grams
                desc = f"${price:.2f}/gm x {weight_grams:.1f}g"
            else:
                cost = price
                desc = f"${price:.2f} {unit}"
            return {
                "cost_usd": round(cost, 2),
                "unit": unit,
                "tier_desc": desc,
                "jewelry_type": jtype,
                "weight_grams": weight_grams,
            }

    return {"cost_usd": 0, "unit": "unknown", "tier_desc": "N/A", "jewelry_type": jtype, "weight_grams": weight_grams}


def get_setting_cost(setting_type: str, stone_count: int, mm_size: float = 0,
                     method: str = "wax", metal: str = "gold") -> dict:
    """
    Get setting charge per stone x count.
    mm_size helps pick small vs large variant for channel/bezel/baguette.
    method: 'hand' or 'wax'
    Returns: {cost_per_stone_usd, total_usd, setting_type, stone_count, method}
    """
    # Normalize GemLens setting names to chart keys
    raw = setting_type.lower().strip()
    raw = raw.replace(" setting", "").replace("-setting", "")
    SETTING_MAP = {
        "prong/claw": "prong", "prong claw": "prong", "claw": "prong",
        "prong": "prong", "pave": "pave", "micro pave": "micro_pave",
        "micro-pave": "micro_pave", "micropave": "micro_pave",
        "channel": "channel", "bezel": "bezel", "flush": "flush",
        "nick": "nick", "baguette": "baguette", "princess": "princess",
        "taper": "taper", "pressure": "pressure", "invisible": "princess_invisible",
        "miracle": "preset_miracle", "center stone": "center_stone",
        "pointer": "pointer",
    }
    stype = SETTING_MAP.get(raw, raw.replace(" ", "_").replace("/", "_"))
    charges = GOLD_SETTING_CHARGES if metal.lower() == "gold" else SILVER_SETTING_CHARGES

    # Handle size variants
    size_variant_types = ["baguette", "princess", "taper", "channel", "bezel", "flush", "nick"]
    for svt in size_variant_types:
        if svt in stype and "_small" not in stype and "_large" not in stype:
            suffix = "_small" if mm_size <= 2.0 else "_large"
            stype = svt + suffix
            break

    # Handle center stone
    if "center" in stype and "_small" not in stype and "_large" not in stype:
        stype = "center_stone_small" if mm_size <= 3.0 else "center_stone_large"

    # Handle pointer
    if "pointer" in stype and "_small" not in stype and "_large" not in stype:
        stype = "pointer_small"  # default to small

    entry = charges.get(stype, {})
    if not entry:
        # Try fuzzy match
        for key in charges:
            if stype.split("_")[0] in key:
                entry = charges[key]
                break

    rate = entry.get(method) or entry.get("hand") or entry.get("wax") or 0
    total = rate * stone_count

    return {
        "cost_per_stone_usd": rate,
        "total_usd": round(total, 2),
        "setting_type": stype,
        "stone_count": stone_count,
        "method": method,
    }


def get_diamond_rate_by_sieve(mm_size: float = 0, sieve: str = "",
                               cut: str = "full", color: str = "white") -> dict:
    """
    Look up diamond rate (USD/ct) by mm size or sieve.
    cut: 'full' or 'single'
    color: 'white' or 'ttlb'
    Returns: {rate_usd_ct, fraction, mm, sieve, cut, color, quality}
    """
    best = None
    best_diff = 999

    for row in DIAMOND_RATES_SIEVE:
        fraction, mm, sv, fc_w, fc_t, sc_w, sc_t = row

        # Match by mm (closest)
        if mm_size > 0:
            diff = abs(mm - mm_size)
            if diff < best_diff:
                best_diff = diff
                best = row

        # Match by sieve (exact substring)
        if sieve and sieve in sv:
            best = row
            break

    if not best:
        # Default: middle of range
        best = DIAMOND_RATES_SIEVE[7]  # 1.40mm Star

    fraction, mm, sv, fc_w, fc_t, sc_w, sc_t = best

    if cut.lower() in ("single", "sc", "single_cut"):
        rate = sc_w if color.lower() == "white" else sc_t
        cut_label = "Single Cut"
    else:
        rate = fc_w if color.lower() == "white" else fc_t
        cut_label = "Full Cut"

    if rate is None:
        # Single cut not available for this size, fall back to full cut
        rate = fc_w if color.lower() == "white" else fc_t
        cut_label = "Full Cut (SC N/A)"

    color_label = "White" if color.lower() == "white" else "TTLB"

    return {
        "rate_usd_ct": rate,
        "fraction": fraction,
        "mm": mm,
        "sieve": sv,
        "cut": cut_label,
        "color": color_label,
        "quality": "I1",
    }


def get_diamond_rate_by_grade(color: str, clarity: str) -> float:
    """
    Look up diamond rate per carat (INR) from color/clarity grade.
    Returns rate_inr_ct (float).
    """
    if not color and not clarity:
        return DIAMOND_FALLBACK_RATE

    color_upper = color.upper().replace(" ", "") if color else ""
    clarity_upper = clarity.upper().replace(" ", "") if clarity else ""

    # Exact match
    if (color_upper, clarity_upper) in DIAMOND_RATES_PER_CT:
        return DIAMOND_RATES_PER_CT[(color_upper, clarity_upper)]

    # Fuzzy: try matching color with any clarity containing our clarity
    for (c, cl), rate in DIAMOND_RATES_PER_CT.items():
        if c == color_upper and (cl in clarity_upper or clarity_upper in cl):
            return rate

    # Fuzzy: try broader color match
    for (c, cl), rate in DIAMOND_RATES_PER_CT.items():
        if any(ch in color_upper for ch in c.split("-")) and any(ch in clarity_upper for ch in cl.split("-")):
            return rate

    return DIAMOND_FALLBACK_RATE


def mm_to_sieve(mm_size: float) -> str:
    """Convert mm size to closest sieve range string for round diamonds."""
    if mm_size <= 0:
        return ""
    best_row = None
    best_diff = 999
    for row in DIAMOND_RATES_SIEVE:
        diff = abs(row[1] - mm_size)
        if diff < best_diff:
            best_diff = diff
            best_row = row
    return best_row[2] if best_row else ""


def get_extras_cost(jewelry_type: str, metal: str = "gold",
                    two_tone: bool = False, rhodium: bool = False,
                    stamping: bool = True, solder: bool = True,
                    special_finish: bool = False,
                    weight_grams: float = 0) -> dict:
    """Calculate additional charges (two-tone, rhodium, stamping, solder, etc.)."""
    extras = GOLD_EXTRAS if metal.lower() == "gold" else SILVER_EXTRAS
    jtype = jewelry_type.lower().strip()
    total = 0.0
    breakdown = []

    if two_tone:
        c = extras.get("two_tone", 0)
        total += c
        breakdown.append(("Two-tone casting", c))

    if rhodium:
        if "bangle" in jtype or "bracelet" in jtype:
            key = "rhodium_bangle_large" if weight_grams > 10 else "rhodium_bangle_small"
        else:
            key = f"rhodium_{jtype}" if f"rhodium_{jtype}" in extras else "rhodium_ring"
        c = extras.get(key, 2.50)
        total += c
        breakdown.append(("Rhodium", c))

    if stamping:
        key = f"stamping_{jtype}" if f"stamping_{jtype}" in extras else "stamping_ring"
        c = extras.get(key, 0.50)
        total += c
        breakdown.append(("Stamping", c))

    if solder:
        c = extras.get("solder", 0.50)
        total += c
        breakdown.append(("Solder", c))

    if special_finish:
        c = extras.get("special_finish", 1.00)
        total += c
        breakdown.append(("Special finish", c))

    return {"total_usd": round(total, 2), "breakdown": breakdown}


# ══════════════════════════════════════════════════════════════════
# LIVE RATE FETCHERS
# ══════════════════════════════════════════════════════════════════

async def _fetch_gold_and_forex() -> dict:
    """Fetch live gold USD/oz, silver USD/oz, and USD/INR forex rate."""
    result = {"gold_usd_oz": 0, "silver_usd_oz": 0, "usd_inr": DEFAULT_USD_INR}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            gold_resp = await client.get("https://api.gold-api.com/price/XAU")
            if gold_resp.status_code == 200:
                result["gold_usd_oz"] = gold_resp.json().get("price", 0)

            silver_resp = await client.get("https://api.gold-api.com/price/XAG")
            if silver_resp.status_code == 200:
                result["silver_usd_oz"] = silver_resp.json().get("price", 0)

            forex_resp = await client.get("https://open.er-api.com/v6/latest/USD")
            if forex_resp.status_code == 200:
                result["usd_inr"] = forex_resp.json().get("rates", {}).get("INR", DEFAULT_USD_INR)
    except Exception as e:
        logger.warning(f"Rate fetch error: {e}")
    return result


def _gold_rate_per_gram(gold_usd_oz: float, usd_inr: float, karat: str = "22K") -> float:
    """Convert gold USD/oz to INR/gram at given karat."""
    if not gold_usd_oz:
        return 0
    # India retail premium: import duty + GST + margin ~ 6.9%
    gold_24k_inr_gm = (gold_usd_oz * usd_inr * 1.069) / TROY_OZ_TO_GRAM
    purity = PURITY_MULTIPLIERS.get(karat.upper(), 0.916)
    return gold_24k_inr_gm * purity


def _silver_rate_per_gram(silver_usd_oz: float, usd_inr: float) -> float:
    """Convert silver USD/oz to INR/gram. Silver is always 999 purity in India."""
    if not silver_usd_oz:
        return 0
    # India retail premium for silver ~ 5%
    return (silver_usd_oz * usd_inr * 1.05) / TROY_OZ_TO_GRAM


# ══════════════════════════════════════════════════════════════════
# STONE COST CALCULATOR
# ══════════════════════════════════════════════════════════════════

def _calculate_stone_costs(stone_grid: list, usd_inr: float,
                           user_stone_rates: dict = None,
                           metal: str = "gold") -> dict:
    """
    Calculate total stone cost from a GemLens stone_grid.
    Priority: user custom rate > sieve lookup > grade lookup > fallback.
    Returns: {total_inr, total_usd, stones: [...], total_setting_usd}
    """
    if not stone_grid:
        return {"total_inr": 0, "total_usd": 0, "stones": [], "total_setting_usd": 0}

    total_inr = 0.0
    total_setting_usd = 0.0
    stones_priced = []

    for s in stone_grid:
        stone_type = str(s.get("stone_type", "diamond")).lower()
        qty = int(s.get("quantity", 1) or 1)
        mm = float(s.get("mm_size", 0) or 0)
        sieve = str(s.get("sieve_size", "") or "")
        total_ct = float(s.get("total_weight", 0) or 0)
        wt_pc = float(s.get("weight_per_piece", 0) or 0)
        grade = str(s.get("quality_grade", "") or "")
        setting_type = str(s.get("setting_type", "prong") or "prong")

        if total_ct <= 0 and wt_pc > 0:
            total_ct = wt_pc * qty

        stone_cost_inr = 0
        rate_source = "none"

        if "diamond" in stone_type:
            # Priority 1: User's custom stone rate
            if user_stone_rates and sieve and sieve in user_stone_rates:
                rate_ct = user_stone_rates[sieve]
                stone_cost_inr = rate_ct * total_ct
                rate_source = "user_custom"
            # Priority 2: Sieve/mm lookup (USD -> INR)
            elif mm > 0 or sieve:
                dr = get_diamond_rate_by_sieve(mm_size=mm, sieve=sieve)
                rate_usd_ct = dr.get("rate_usd_ct", 0)
                stone_cost_inr = rate_usd_ct * total_ct * usd_inr
                rate_source = f"sieve:{dr.get('sieve', '')}"
            # Priority 3: Grade lookup (INR)
            elif grade:
                parts = [p.strip() for p in grade.upper().split("/")]
                color = parts[0] if len(parts) >= 1 else ""
                clarity = parts[1] if len(parts) >= 2 else ""
                rate_inr_ct = get_diamond_rate_by_grade(color, clarity)
                stone_cost_inr = rate_inr_ct * total_ct
                rate_source = "grade"
            # Fallback
            elif total_ct > 0:
                stone_cost_inr = DIAMOND_FALLBACK_RATE * total_ct
                rate_source = "fallback"

        # Setting charges
        setting = get_setting_cost(setting_type, qty, mm_size=mm, metal=metal)
        total_setting_usd += setting["total_usd"]

        total_inr += stone_cost_inr
        stones_priced.append({
            "stone_type": stone_type,
            "qty": qty,
            "mm": mm,
            "sieve": sieve,
            "total_ct": total_ct,
            "grade": grade,
            "cost_inr": round(stone_cost_inr, 0),
            "rate_source": rate_source,
            "setting_usd": setting["total_usd"],
            "setting_type": setting["setting_type"],
        })

    return {
        "total_inr": round(total_inr, 0),
        "total_usd": round(total_inr / usd_inr, 2) if usd_inr else 0,
        "stones": stones_priced,
        "total_setting_usd": round(total_setting_usd, 2),
    }


# ══════════════════════════════════════════════════════════════════
# MASTER FUNCTION — Full Jewelry Cost Calculator
# ══════════════════════════════════════════════════════════════════

async def calculate_full_jewelry_cost(
    db: AsyncSession = None,
    user_id: str = None,
    weight_grams: float = 0,
    karat: str = "22K",
    jewelry_type: str = "ring",
    metal: str = "gold",
    stone_grid: list = None,
    model: str = "setting_charges",  # setting_charges | gram_wise | plain_gold
    margin_pct: float = 0,
    finishing: dict = None,  # {rhodium: True, stamping: True, ...}
) -> dict:
    """
    Calculate complete jewelry cost with all components.
    Returns a dict with full breakdown + formatted text summary.
    """
    from ..models import UserMemory

    finishing = finishing or {}
    karat = karat.upper().strip()
    if not karat.endswith("K"):
        karat = karat + "K"

    # ── Fetch live rates ──────────────────────────────────────────
    rates = await _fetch_gold_and_forex()
    gold_usd_oz = rates["gold_usd_oz"]
    silver_usd_oz = rates["silver_usd_oz"]
    usd_inr = rates["usd_inr"]

    if metal.lower() == "silver":
        metal_rate = _silver_rate_per_gram(silver_usd_oz, usd_inr)
        karat = "999"  # Silver is always 999 purity
    else:
        metal_rate = _gold_rate_per_gram(gold_usd_oz, usd_inr, karat)

    # ── Get user's custom making% and stone rates from UserMemory ──
    making_pct = 12.0  # default
    user_stone_rates = {}

    if db and user_id:
        try:
            result = await db.execute(
                select(UserMemory).where(UserMemory.user_id == user_id)
            )
            memories = result.scalars().all()
            for mem in memories:
                key_lower = (mem.key or "").lower()
                value = mem.value or ""
                # Making percentage
                if "making" in key_lower:
                    try:
                        making_pct = float(re.search(r"[\d.]+", value).group())
                    except Exception:
                        pass
                # Custom stone rates (e.g., key="stone_rate_+2.0-3.0", value="450")
                if "stone_rate" in key_lower:
                    sieve_key = key_lower.replace("stone_rate_", "").replace("stone_rate", "").strip()
                    try:
                        user_stone_rates[sieve_key] = float(value)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"UserMemory read error: {e}")

    # ── Metal cost ────────────────────────────────────────────────
    metal_cost = weight_grams * metal_rate if weight_grams and metal_rate else 0

    # ── Metal loss ────────────────────────────────────────────────
    loss_pct = GOLD_LOSS_PCT if metal.lower() == "gold" else SILVER_LOSS_PCT
    metal_loss = metal_cost * (loss_pct / 100)

    # ── Making charges ────────────────────────────────────────────
    making_charge = metal_cost * (making_pct / 100)

    # ── GST 3% on (metal + making) ───────────────────────────────
    gst = (metal_cost + making_charge) * (GST_PCT / 100)

    # ── Model-specific calculations ───────────────────────────────
    labor_info = {"cost_usd": 0, "cost_inr": 0, "tier_desc": "N/A"}
    extras_info = {"total_usd": 0, "total_inr": 0, "breakdown": []}
    stone_info = {"total_inr": 0, "total_usd": 0, "stones": [], "total_setting_usd": 0}
    setting_cost_inr = 0

    if model == "setting_charges":
        # Full itemized model
        labor = get_labor_cost(jewelry_type, weight_grams, metal)
        labor_info = {
            "cost_usd": labor["cost_usd"],
            "cost_inr": round(labor["cost_usd"] * usd_inr, 0),
            "tier_desc": labor["tier_desc"],
            "unit": labor["unit"],
        }

        extras = get_extras_cost(
            jewelry_type, metal,
            two_tone=finishing.get("two_tone", False),
            rhodium=finishing.get("rhodium", False),
            stamping=finishing.get("stamping", True),
            solder=finishing.get("solder", True),
            special_finish=finishing.get("special_finish", False),
            weight_grams=weight_grams,
        )
        extras_info = {
            "total_usd": extras["total_usd"],
            "total_inr": round(extras["total_usd"] * usd_inr, 0),
            "breakdown": extras["breakdown"],
        }

        if stone_grid:
            stone_info = _calculate_stone_costs(stone_grid, usd_inr, user_stone_rates, metal)
            setting_cost_inr = round(stone_info["total_setting_usd"] * usd_inr, 0)

    elif model == "gram_wise":
        # Gramwise model: flat per-gram rate (includes loss)
        gw_rate = GRAMWISE_DEFAULTS["gold_per_gram_inr"]
        labor_info = {
            "cost_usd": round(gw_rate * weight_grams / usd_inr, 2),
            "cost_inr": round(gw_rate * weight_grams, 0),
            "tier_desc": f"Rs {gw_rate}/gm x {weight_grams:.1f}g (gramwise)",
            "unit": "per_gm",
        }
        # Gramwise includes loss, so zero it
        metal_loss = 0

    elif model == "plain_gold":
        # Plain gold model: metal + flat %
        pct = PLAIN_GOLD_DEFAULTS["domestic_pct"]
        making_charge = metal_cost * (pct / 100)
        making_pct = pct
        gst = (metal_cost + making_charge) * (GST_PCT / 100)

    # ── Grand total ───────────────────────────────────────────────
    grand_total_inr = (
        metal_cost
        + metal_loss
        + making_charge
        + gst
        + labor_info.get("cost_inr", 0)
        + extras_info.get("total_inr", 0)
        + setting_cost_inr
        + stone_info.get("total_inr", 0)
    )

    # Apply margin
    if margin_pct > 0:
        grand_total_inr *= (1 + margin_pct / 100)

    grand_total_usd = round(grand_total_inr / usd_inr, 2) if usd_inr else 0

    # ── Build result dict ─────────────────────────────────────────
    result = {
        "jewelry_type": jewelry_type,
        "metal": metal,
        "karat": karat,
        "weight_grams": weight_grams,
        "model": model,

        # Rates
        "gold_rate_per_gram": round(metal_rate, 0),
        "gold_usd_oz": gold_usd_oz,
        "usd_inr": usd_inr,

        # Metal
        "metal_cost": round(metal_cost, 0),
        "metal_loss_pct": loss_pct,
        "metal_loss": round(metal_loss, 0),

        # Making
        "making_pct": making_pct,
        "making_charge": round(making_charge, 0),

        # GST
        "gst_pct": GST_PCT,
        "gst": round(gst, 0),

        # Labor
        "labor": labor_info,

        # Extras
        "extras": extras_info,

        # Setting
        "setting_cost_inr": setting_cost_inr,

        # Stones
        "stones": stone_info,
        "has_stones": bool(stone_grid and len(stone_grid) > 0),

        # Total
        "margin_pct": margin_pct,
        "grand_total_inr": round(grand_total_inr, 0),
        "grand_total_usd": grand_total_usd,
    }

    # ── Formatted text summary for WhatsApp ───────────────────────
    result["formatted"] = _format_whatsapp_summary(result)

    logger.info(
        f"Pricing: {karat} {metal} {jewelry_type} {weight_grams}g = "
        f"INR {grand_total_inr:,.0f} (model={model})"
    )

    return result


def _format_whatsapp_summary(r: dict) -> str:
    """Build a concise WhatsApp-formatted pricing summary."""
    karat = r["karat"]
    jtype = r["jewelry_type"].title()
    weight = r["weight_grams"]
    metal = r["metal"].title()
    usd_inr = r["usd_inr"] or DEFAULT_USD_INR

    lines = [f"*{karat} {metal} {jtype} — {weight}g*\n"]

    # Metal section
    lines.append("\U0001f4b0 *Metal*")
    if r["gold_rate_per_gram"]:
        rate_label = "Silver" if metal.lower() == "silver" else karat
        lines.append(f"Rate: \u20b9{r['gold_rate_per_gram']:,.0f}/gm ({rate_label} live)")
    lines.append(f"Metal: \u20b9{r['metal_cost']:,.0f}")
    if r["metal_loss"]:
        lines.append(f"Loss ({r['metal_loss_pct']:.0f}%): \u20b9{r['metal_loss']:,.0f}")
    lines.append(f"Making ({r['making_pct']:.0f}%): \u20b9{r['making_charge']:,.0f}")
    lines.append(f"GST ({r['gst_pct']:.0f}%): \u20b9{r['gst']:,.0f}")

    # Labor section
    if r["labor"]["cost_inr"]:
        lines.append(f"\n\U0001f527 *Labor*")
        lines.append(f"Casting/Filing: ${r['labor']['cost_usd']:.2f} (\u20b9{r['labor']['cost_inr']:,.0f})")
        if r["labor"].get("tier_desc"):
            lines.append(f"  {r['labor']['tier_desc']}")

    # Extras
    if r["extras"]["total_inr"]:
        for name, cost_usd in r["extras"]["breakdown"]:
            lines.append(f"  {name}: ${cost_usd:.2f} (\u20b9{cost_usd * usd_inr:,.0f})")

    # Stones section
    if r["has_stones"]:
        lines.append(f"\n\U0001f48e *Stones*")
        for sp in r["stones"].get("stones", []):
            lines.append(
                f"  {sp['stone_type'].title()} {sp.get('sieve') or ''} "
                f"x{sp['qty']} = \u20b9{sp['cost_inr']:,.0f}"
            )
        if r["setting_cost_inr"]:
            lines.append(f"  Setting: \u20b9{r['setting_cost_inr']:,.0f}")
        lines.append(f"  Stone total: \u20b9{r['stones']['total_inr']:,.0f}")
    else:
        lines.append(f"\n\U0001f48e *Stones*")
        lines.append("(Photo bhejo ya weight batao for stone pricing)")

    # Grand total
    lines.append(f"\n{'━' * 17}")
    lines.append(f"*TOTAL: \u20b9{r['grand_total_inr']:,.0f}* (${r['grand_total_usd']:,.0f})")
    lines.append(f"{'━' * 17}")
    lines.append('Making % change karna ho toh bolo: "making 16%"')

    return "\n".join(lines)
