import httpx
import json
import logging
from ..config import settings

logger = logging.getLogger("samva.llm")


async def call_gemini(
    system_prompt: str,
    user_message: str,
    image_base64: str = None,
    max_tokens: int = 800,
    user_id: str = "",
) -> str:
    """Call Gemini 2.5 Flash via OpenRouter. Supports text + vision."""
    if not settings.openrouter_api_key:
        return "I'm having trouble connecting right now. Please try again in a moment."

    messages = [{"role": "system", "content": system_prompt}]

    if image_base64:
        content = [
            {"type": "text", "text": user_message or "What do you see in this image?"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
            },
        ]
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_message})

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://samva.in",
                    "X-Title": "Samva",
                },
                json={
                    "model": settings.samva_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            logger.info(f"LLM reply for {user_id}: {reply[:100]}...")
            return reply.strip()
    except Exception as e:
        logger.error(f"LLM error for {user_id}: {e}")
        return "Sorry, I'm having a brief moment. Try again?"


async def call_gemini_json(
    system_prompt: str,
    user_message: str,
    image_base64: str = None,
    user_id: str = "",
    max_tokens: int = 800,
) -> dict:
    """Call Gemini and parse response as JSON."""
    raw = await call_gemini(
        system_prompt, user_message, image_base64=image_base64,
        user_id=user_id, max_tokens=max_tokens,
    )

    # Strip markdown code blocks
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"JSON parse error for {user_id}: {text[:200]}")
        return {"error": "parse_error", "raw": raw}


async def text_to_speech(text: str, user_id: str = "", voice_language: str = "auto") -> str:
    """
    Convert text to speech using OpenAI GPT Audio Mini via OpenRouter.
    Best natural voice in the industry. Multilingual. Warm and friendly.
    voice_language: user's chosen language for voice notes.
    Returns base64-encoded audio, or empty string on failure.
    """
    if not settings.openrouter_api_key:
        return ""

    # Clean for speech
    clean = text.replace("*", "").replace("_", "").replace("`", "")
    clean = clean.replace("\u20b9", "rupees ").replace("\u2192", "")
    clean = clean.replace("\u2501", "").replace("\u25b8", "")
    clean = clean.replace("\u2191", " up ").replace("\u2193", " down ")
    clean = clean.replace("---", "").replace("___", "").replace("\n\n\n", "\n")
    if len(clean) > 500:
        clean = clean[:500] + "... baaki details text mein bhej rahi hoon."

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://samva.in",
                },
                json={
                    "model": "openai/gpt-audio-mini",
                    "messages": [
                        {
                            "role": "system",
                            "content": f"You are Sam, a warm and caring personal assistant. Read the text aloud in a friendly, natural tone. SPEAK IN {voice_language.upper() if voice_language != 'auto' else 'the same language as the text'}. Be warm, expressive, like talking to a close friend. NOT robotic."
                        },
                        {"role": "user", "content": f"Read this aloud in {voice_language if voice_language != 'auto' else 'the appropriate language'}:\n\n{clean}"}
                    ],
                    "modalities": ["text", "audio"],
                    "audio": {"voice": "shimmer", "format": "mp3"},
                    "max_tokens": 1000,
                },
            )

            if resp.status_code != 200:
                logger.error(f"TTS OpenAI error {resp.status_code}: {resp.text[:200]}")
                # Fallback to Gemini TTS
                return await _gemini_tts(clean, user_id)

            data = resp.json()

            # Extract audio from OpenAI response
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            audio = message.get("audio", {})
            audio_data = audio.get("data", "")

            if audio_data:
                logger.info(f"TTS (OpenAI) for {user_id}: {len(audio_data)} chars")
                return audio_data

            logger.warning(f"TTS: no audio in OpenAI response for {user_id}")
            return await _gemini_tts(clean, user_id)

    except Exception as e:
        logger.error(f"TTS OpenAI error for {user_id}: {e}")
        return await _gemini_tts(clean, user_id)


async def _gemini_tts(clean: str, user_id: str = "") -> str:
    """Fallback TTS using Gemini. Used when OpenAI fails."""
    if not settings.gemini_api_key:
        return ""

    has_hindi = any(ord(c) > 0x0900 and ord(c) < 0x097F for c in clean)
    has_hindi_words = any(w in clean.lower() for w in ["hai", "hoon", "karo", "hain", "nahi", "aaj"])
    voice = "Kore" if (has_hindi or has_hindi_words) else "Aoede"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": f"Read naturally like a warm friend:\n\n{clean}"}]}],
                    "generationConfig": {
                        "response_modalities": ["AUDIO"],
                        "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": voice}}}
                    }
                },
            )
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            for part in parts:
                inline = part.get("inlineData", {})
                if inline.get("mimeType", "").startswith("audio/"):
                    logger.info(f"TTS (Gemini fallback) for {user_id}")
                    return inline.get("data", "")
        return ""
    except Exception as e:
        logger.error(f"Gemini TTS fallback error: {e}")
        return ""


async def transcribe_audio(audio_base64: str, user_id: str = "") -> str:
    """Transcribe audio using Gemini API directly (not OpenRouter)."""
    if not settings.gemini_api_key:
        # Fallback: use OpenRouter with audio description
        return await call_gemini(
            "Transcribe this audio message accurately. Return ONLY the transcription, nothing else.",
            "Please transcribe the attached audio.",
            user_id=user_id,
        )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": "Transcribe this audio accurately. Return ONLY the transcription text, nothing else."},
                                {
                                    "inline_data": {
                                        "mime_type": "audio/ogg",
                                        "data": audio_base64,
                                    }
                                },
                            ]
                        }
                    ]
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            logger.info(f"Transcription for {user_id}: {text[:100]}...")

            # Validate — reject garbled or too-short transcriptions
            words = text.split()
            if len(words) < 2:
                logger.warning(f"Transcription too short for {user_id}: '{text}'")
                return ""
            # Check for obvious garbled output
            garbled_signals = ["[inaudible]", "[music]", "[silence]", "...", "hmm"]
            if any(g in text.lower() for g in garbled_signals) and len(words) < 5:
                logger.warning(f"Garbled transcription for {user_id}: '{text}'")
                return ""

            return text
    except Exception as e:
        logger.error(f"Transcription error for {user_id}: {e}")
        return ""
