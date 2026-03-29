"""
Sam's Language Intelligence.

sam_says() — translates any hardcoded string to user's language.
Caches translations. Popular languages pre-translated.
Default fallback: English.

Voice language separate from text language.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import AgentSoul

logger = logging.getLogger("samva.language")

# Translation cache: (text_hash, lang) -> translated text
_cache = {}

# Pre-translated common phrases for popular languages
PRE_TRANSLATED = {
    "Bhejun? (haan/nahi)": {
        "english": "Shall I send? (yes/no)",
        "hindi": "Bhejun? (haan/nahi)",
        "gujarati": "Moklun? (haa/na)",
        "bengali": "Pathabo? (hyan/na)",
        "tamil": "Anuppava? (aam/illai)",
        "telugu": "Pampanaa? (avunu/kaadu)",
        "malayalam": "Ayakkatte? (athe/venda)",
        "marathi": "Pathavu? (ho/nahi)",
    },
    "Kisi ko reply karna hai? Naam batao.": {
        "english": "Want to reply to anyone? Tell me the name.",
        "hindi": "Kisi ko reply karna hai? Naam batao.",
        "gujarati": "Koine reply karvu chhe? Naam kaho.",
        "bengali": "Kaauke reply korte chao? Naam bolo.",
        "tamil": "Yarukkaavathu reply pannanuma? Per sollunga.",
        "telugu": "Evariki reply cheyalaa? Peru cheppandi.",
        "malayalam": "Aarkkenkkilum reply cheyyanamo? Peru parayoo.",
        "marathi": "Konala reply karaycha? Nav sanga.",
    },
    "Photo bhejo — main analyze kar dungi!": {
        "english": "Send me a photo — I'll analyze it!",
        "hindi": "Photo bhejo — main analyze kar dungi!",
        "gujarati": "Photo moklo — hun analyze kari daish!",
        "bengali": "Photo pathao — ami analyze kore debo!",
        "tamil": "Photo anuppunga — naan analyze panren!",
        "telugu": "Photo pampandi — nenu analyze chesta!",
        "malayalam": "Photo ayakkoo — njan analyze cheyyaam!",
        "marathi": "Photo pathva — mi analyze karte!",
    },
}

LANGUAGE_NAMES = {
    "english": "English",
    "hindi": "Hindi",
    "hinglish": "Hindi + English mix",
    "gujarati": "Gujarati",
    "bengali": "Bengali / Bangla",
    "tamil": "Tamil",
    "telugu": "Telugu",
    "malayalam": "Malayalam",
    "marathi": "Marathi",
    "kannada": "Kannada",
    "punjabi": "Punjabi",
    "odia": "Odia",
    "assamese": "Assamese",
    "urdu": "Urdu",
}


async def get_user_languages(db: AsyncSession, user_id: str) -> dict:
    """Get user's text and voice language preferences."""
    result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = result.scalar_one_or_none()
    if not soul:
        return {"text": "english", "voice": "english"}
    return {
        "text": soul.language_preference or "english",
        "voice": soul.voice_language or soul.language_preference or "english",
    }


async def sam_says(text: str, user_id: str, db: AsyncSession = None) -> str:
    """
    Translate a hardcoded Sam message to the user's language.
    Uses pre-translated cache for popular phrases.
    Falls back to Gemini translation.
    Caches results so each string is translated only once per language.
    """
    if not db:
        return text  # No DB context — return as-is

    langs = await get_user_languages(db, user_id)
    target_lang = langs["text"]

    # English or auto — return as-is (most strings are English/Hindi mix)
    if target_lang in ("english", "auto", "hinglish", "hindi"):
        return text

    # Check pre-translated
    if text in PRE_TRANSLATED:
        translated = PRE_TRANSLATED[text].get(target_lang)
        if translated:
            return translated

    # Check cache
    cache_key = (hash(text), target_lang)
    if cache_key in _cache:
        return _cache[cache_key]

    # Live translation via Gemini
    try:
        from .llm import call_gemini
        translated = await call_gemini(
            f"Translate this to {LANGUAGE_NAMES.get(target_lang, target_lang)}. "
            f"Keep the formatting (*, _, emojis). Return ONLY the translation, nothing else.",
            text,
            user_id=user_id,
            max_tokens=300,
        )
        if translated and len(translated) > 5:
            _cache[cache_key] = translated
            return translated
    except Exception as e:
        logger.error(f"Translation error: {e}")

    return text  # Fallback — return original


def get_language_question() -> str:
    """The onboarding language question."""
    return (
        "Aapko kis language mein baat karni hai?\n\n"
        "Examples:\n"
        "\u2022 English only\n"
        "\u2022 Hindi\n"
        "\u2022 Hindi + English (Hinglish)\n"
        "\u2022 Gujarati\n"
        "\u2022 Bengali\n"
        "\u2022 Tamil + English\n"
        "\u2022 Telugu\n"
        "\u2022 Malayalam\n"
        "\u2022 Marathi\n"
        "\u2022 Kannada\n"
        "\u2022 Punjabi\n\n"
        "Jo bhi comfortable ho — batao!"
    )


def get_voice_language_question() -> str:
    """The onboarding voice language question."""
    return (
        "Voice notes mein kaunsi language sunna pasand karoge?\n\n"
        "Sam voice notes mein baat karegi — aapki language mein!\n\n"
        "Same as chat language? Ya kuch aur?\n"
        "Example: chat English mein, voice Hindi mein"
    )


def normalize_language(text: str) -> str:
    """Extract language name from user's response."""
    lower = text.lower().strip()

    # Direct matches
    for lang_key, lang_name in LANGUAGE_NAMES.items():
        if lang_key in lower or lang_name.lower() in lower:
            return lang_key

    # Common variations
    if "bangla" in lower:
        return "bengali"
    if "mix" in lower or "dono" in lower:
        return "hinglish"
    if any(w in lower for w in ["same", "wahi", "same as chat"]):
        return "same"

    # Default
    return "english"
