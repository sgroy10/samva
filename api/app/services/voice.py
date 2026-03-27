"""
Sam Voice Service — Twilio-powered voice calls.

User calls Sam's number → Sam answers → user speaks →
Sam transcribes → processes → speaks back. In any language.

Flow:
  Incoming call → /voice/answer (TwiML greeting)
  → User speaks → /voice/process (transcribe + Sam responds)
  → Loop until hangup
"""

import logging
import base64
import httpx
from ..config import settings
from .llm import call_gemini

logger = logging.getLogger("samva.voice")


def generate_answer_twiml(user_name: str = "there") -> str:
    """Generate TwiML for answering an incoming call."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Google.hi-IN-Wavenet-A" language="hi-IN">
        Namaste {user_name}! Main Sam hoon, aapki personal assistant.
        Boliye, main sun rahi hoon.
    </Say>
    <Gather input="speech" timeout="5" speechTimeout="auto"
            language="hi-IN" action="/voice/process" method="POST">
        <Say voice="Google.hi-IN-Wavenet-A" language="hi-IN">
        </Say>
    </Gather>
    <Say voice="Google.hi-IN-Wavenet-A" language="hi-IN">
        Koi jawab nahi aaya. Phir se try karein. Alvida!
    </Say>
</Response>"""


def generate_response_twiml(reply_text: str, language: str = "hi-IN") -> str:
    """Generate TwiML that speaks Sam's reply and listens for next input."""
    # Pick voice based on language
    voice = "Google.hi-IN-Wavenet-A"
    if language.startswith("en"):
        voice = "Google.en-IN-Wavenet-A"
    elif language.startswith("gu"):
        voice = "Google.hi-IN-Wavenet-A"  # Gujarati fallback to Hindi

    # Clean text for TwiML (remove markdown, emojis that TTS can't speak)
    clean = reply_text.replace("*", "").replace("_", "").replace("`", "")
    clean = clean.replace("₹", "rupees ").replace("→", "").replace("━", "")
    clean = clean.replace("▸", "").replace("↑", "up ").replace("↓", "down ")
    # Truncate for voice — keep it short
    if len(clean) > 500:
        clean = clean[:500] + "... aur bhi details WhatsApp pe bhej rahi hoon."

    # Escape XML special chars
    clean = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="{voice}" language="{language}">
        {clean}
    </Say>
    <Gather input="speech" timeout="5" speechTimeout="auto"
            language="{language}" action="/voice/process" method="POST">
        <Say voice="{voice}" language="{language}">
            Aur kuch poochna hai?
        </Say>
    </Gather>
    <Say voice="{voice}" language="{language}">
        Theek hai, alvida! WhatsApp pe milte hain.
    </Say>
</Response>"""


def generate_error_twiml() -> str:
    """TwiML for error/fallback."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Google.hi-IN-Wavenet-A" language="hi-IN">
        Maaf kijiye, abhi kuch problem aa rahi hai.
        WhatsApp pe message karein, main wahan jawab dungi.
    </Say>
</Response>"""


async def identify_caller(phone: str) -> dict:
    """Look up a caller by phone number in the database."""
    from ..database import async_session
    from ..models import User, AgentSoul
    from sqlalchemy import select

    # Clean phone — remove +, spaces
    clean = phone.replace("+", "").replace(" ", "").replace("-", "")
    # Try matching last 10 digits
    last10 = clean[-10:] if len(clean) >= 10 else clean

    async with async_session() as db:
        # Search users by phone
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            if not user.phone:
                continue
            user_clean = user.phone.replace("+", "").replace(" ", "")
            if user_clean.endswith(last10) or last10.endswith(user_clean[-10:]):
                # Found the user — get their soul
                soul_result = await db.execute(
                    select(AgentSoul).where(AgentSoul.user_id == user.id)
                )
                soul = soul_result.scalar_one_or_none()
                return {
                    "user_id": user.id,
                    "name": user.name or "there",
                    "language": soul.language_preference if soul else "hi",
                    "business_type": soul.business_type if soul else "",
                    "found": True,
                }

    return {"user_id": None, "name": "there", "language": "hi", "found": False}


async def process_speech(user_id: str, speech_text: str) -> str:
    """Process spoken input through Sam's orchestrator and return text reply."""
    if not speech_text or not speech_text.strip():
        return "Samajh nahi aaya. Phir se boliye?"

    from ..database import async_session
    from .agent import process_message

    async with async_session() as db:
        result = await process_message(
            db=db,
            user_id=user_id,
            text=speech_text,
            message_type="text",
        )
        return result.get("reply", "Maaf kijiye, jawab nahi mil raha.")


async def make_outbound_call(to_phone: str, message: str) -> dict:
    """Make an outbound call from Sam to a user. Used for urgent alerts."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return {"error": "Twilio not configured"}

    # Clean text for TwiML
    clean = message.replace("*", "").replace("_", "").replace("`", "")
    clean = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Google.hi-IN-Wavenet-A" language="hi-IN">
        {clean[:500]}
    </Say>
    <Pause length="1"/>
    <Say voice="Google.hi-IN-Wavenet-A" language="hi-IN">
        Yeh Sam thi, aapki Samva assistant. WhatsApp pe milte hain.
    </Say>
</Response>"""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Calls.json",
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                data={
                    "To": to_phone,
                    "From": settings.twilio_phone_number,
                    "Twiml": twiml,
                },
            )
            if resp.status_code in (200, 201):
                call_data = resp.json()
                logger.info(f"Outbound call to {to_phone}: {call_data.get('sid')}")
                return {"success": True, "call_sid": call_data.get("sid")}
            else:
                logger.error(f"Outbound call failed: {resp.status_code} {resp.text[:200]}")
                return {"error": f"Call failed: {resp.status_code}"}
    except Exception as e:
        logger.error(f"Outbound call error: {e}")
        return {"error": str(e)}
