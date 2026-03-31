"""
THE ORCHESTRATOR — Sam's brain above all skills.

Every message flows through here. The orchestrator decides:
1. Which skill handles this? (prebuilt → custom-built → intent-based)
2. Which LLM for this task? (Flash for chat, Pro for vision, Sonnet for code)
3. Should Sam build a new skill? (background, never blocks)

The user never sees routing decisions. They just talk. Sam figures out everything.

Flow:
  message → orchestrator → [prebuilt? custom? intent?] → execute → respond
                          → [build new skill in background if needed]
"""

import logging
import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import AgentSoul, User, Conversation, UserMemory
from ..config import settings
from . import prebuilt_skills
from . import skill_builder
from .llm import call_gemini, call_gemini_json, transcribe_audio
from .confidence import tag_confidence

logger = logging.getLogger("samva.orchestrator")

# ── LLM Models Available via OpenRouter ──────────────────────────

MODELS = {
    "flash": "google/gemini-2.5-flash",          # Fast, cheap — chat, intent, simple tasks
    "pro": "google/gemini-2.5-pro-preview",       # Complex reasoning, vision, medical
    "sonnet": "anthropic/claude-sonnet-4",    # Best code generation
    "haiku": "anthropic/claude-haiku-4-5-20251001",  # Fast classification
}


async def call_llm(
    model_key: str,
    system_prompt: str,
    user_message: str,
    image_base64: str = None,
    max_tokens: int = 800,
    user_id: str = "",
) -> str:
    """Call any LLM via OpenRouter. Model selected by orchestrator."""
    import httpx

    model = MODELS.get(model_key, settings.samva_model)

    messages = [{"role": "system", "content": system_prompt}]
    if image_base64:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_message or "Analyze this image."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            ],
        })
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
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            logger.info(f"[{model_key}] Reply for {user_id}: {reply[:80]}...")
            return reply.strip()
    except Exception as e:
        logger.error(f"[{model_key}] LLM error for {user_id}: {e}")
        # Fallback to default model
        if model_key != "flash":
            logger.info(f"Falling back to flash for {user_id}")
            return await call_gemini(system_prompt, user_message, image_base64, max_tokens, user_id)
        return "Sorry, I'm having a brief moment. Try again?"


# ── Orchestrator Core ────────────────────────────────────────────

async def orchestrate(
    db: AsyncSession,
    user_id: str,
    user: User,
    soul: AgentSoul,
    text: str,
    message_type: str = "text",
    image_base64: str = None,
) -> str:
    """
    The main orchestration function. Called by agent.py after
    onboarding, subscription, and fast-command checks.

    Returns the final reply string.
    """
    business_type = soul.business_type or ""
    text_lower = (text or "").lower().strip()

    # ── LAYER 0: Image Memory — Sam NEVER forgets an image ─────
    from . import image_session

    # If user sent a NEW image — store it permanently
    if image_base64:
        img_id = await image_session.store_image(db, user_id, image_base64, source="upload")
        logger.info(f"[{user_id}] Image stored: session {img_id}")

    # If message references an image (render, change, enhance, etc.)
    # but NO new image was sent — load the active image from DB
    if not image_base64 and image_session.is_image_context_message(text):
        active = await image_session.get_active_image(db, user_id)
        if active:
            image_base64 = active["base64"]
            logger.info(f"[{user_id}] Loaded active image from session (id={active['id']}, source={active['source']})")

    # ── LAYER 1: Prebuilt Skills (instant, no AI cost for routing) ──
    # Check keyword match against the prebuilt library
    context = await _build_context(db, user_id, image_base64)
    prebuilt_result = await prebuilt_skills.find_and_execute(text, business_type, context)

    if prebuilt_result:
        # PDF response — send as document
        if prebuilt_result.startswith("__PDF__"):
            logger.info(f"[{user_id}] Prebuilt returned PDF")
            return prebuilt_result

        # Image response — store the result as new version + send to user
        if prebuilt_result.startswith("__IMAGE__"):
            img_data = prebuilt_result.replace("__IMAGE__", "")
            if img_data:
                # Get parent image ID
                active = await image_session.get_active_image(db, user_id)
                parent_id = active.get("id") if active else None
                # Store render/enhance result as new version
                await image_session.store_version(
                    db, user_id, img_data,
                    description=text or "Generated image",
                    source="render",
                    parent_id=parent_id,
                )
                logger.info(f"[{user_id}] Render stored as new version")
            return prebuilt_result

        # User needs to send a photo first — BUT only if the query is actually about images
        if prebuilt_result == "__NEED_IMAGE__":
            image_words = ["photo", "image", "picture", "scan", "enhance", "render", "ad banao", "try on"]
            if any(w in text_lower for w in image_words):
                return "Photo bhejo — main analyze kar dungi!"
            # Not an image query — skip this skill, let others handle it
            prebuilt_result = None

        # LLM signals — skill needs specialized LLM processing
        if prebuilt_result and (prebuilt_result.startswith("__LLM_") or prebuilt_result.startswith("__")):
            reply = await _handle_llm_signal(db, user_id, user, soul, text, prebuilt_result, image_base64)
            if reply:
                return reply

        # Direct prebuilt result — return it
        elif prebuilt_result:
            logger.info(f"[{user_id}] Prebuilt skill answered")
            return prebuilt_result

    # ── LAYER 2: Custom-built Skills (user-specific, from self-builder) ──
    custom_result = await skill_builder.execute_user_skill(db, user_id, text)
    if custom_result:
        logger.info(f"[{user_id}] Custom skill answered")
        return custom_result

    # ── LAYER 3: Image Routing (pick the right vision model) ──────
    if image_base64:
        return await _handle_image(db, user_id, user, soul, text, image_base64, business_type)

    # ── LAYER 2.3: Confirm pending reply / email send ────────
    # Auto-expire old pending records (older than 1 hour)
    from ..models import PendingReply, PendingEmailDraft
    from sqlalchemy import delete as sql_delete
    from datetime import timedelta
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    await db.execute(sql_delete(PendingReply).where(PendingReply.created_at < one_hour_ago))
    await db.execute(sql_delete(PendingEmailDraft).where(PendingEmailDraft.created_at < one_hour_ago))
    await db.commit()
    from . import inbox
    from . import email_service as email_svc
    # Check if user is responding to a behavior proposal
    from . import pattern_watcher
    proposal_response = await pattern_watcher.handle_proposal_response(db, user_id, text)
    if proposal_response:
        return proposal_response

    confirm_words = {"haan", "ha", "yes", "send", "bhej", "bhejo", "ok", "theek", "sure"}
    cancel_words = {"nahi", "nai", "no", "cancel", "mat", "ruk"}

    if text_lower.strip() in confirm_words:
        # Check pending chat reply (DB-backed, survives restarts)
        if await inbox.has_pending_reply(db, user_id):
            send_data = await inbox.confirm_and_send_reply(db, user_id)
            if send_data:
                import httpx as hx
                try:
                    async with hx.AsyncClient(timeout=10.0) as client:
                        await client.post(f"{settings.bridge_url}/send-to-chat", json={
                            "userId": user_id,
                            "chatJid": send_data["chat_id"],
                            "text": send_data["text"],
                        })
                    return f"Reply sent to {send_data['customer_name']} \u2705"
                except Exception as e:
                    return f"Send failed: {str(e)[:50]}. Try again."

        # Check pending email draft (DB-backed)
        if await email_svc.has_pending_draft(db, user_id):
            return await email_svc.confirm_send_email(db, user_id)

    if text_lower.strip() in cancel_words:
        if await inbox.has_pending_reply(db, user_id):
            await inbox.cancel_pending_reply(db, user_id)
            return "Reply cancel kar diya."
        if await email_svc.has_pending_draft(db, user_id):
            await email_svc.cancel_pending_draft(db, user_id)
            return "Draft cancel."

    # ── LAYER 2.4: Image history commands ──────────────────────
    show_original = any(w in text_lower for w in ["show original", "original dikhao", "pehle wala",
                                                     "previous version", "go back", "first image"])
    if show_original:
        active = await image_session.get_active_image(db, user_id)
        if active and active.get("parent_id"):
            parent = await image_session.get_image_by_id(db, user_id, active["parent_id"])
            if parent and parent.get("base64"):
                return f"__IMAGE__{parent['base64']}"

        history = await image_session.get_image_history(db, user_id)
        if history:
            lines = ["*Image history:*\n"]
            for h in history:
                lines.append(f"  {h['source']}: {h['description'] or 'no description'}")
            return "\n".join(lines)
        return "Koi image history nahi hai."

    # ── LAYER 2.5: Inbox / Chat Intelligence ────────────────────
    from . import chat_intelligence
    inbox_triggers = ["check messages", "messages dikhao", "inbox", "unread",
                       "kaun aaya", "notifications", "messages", "message check",
                       "kaun kaun aaya", "new messages", "koi message aaya",
                       "urgent kya hai", "important messages"]
    if any(kw in text_lower for kw in inbox_triggers):
        return await chat_intelligence.get_chat_summary(db, user_id)

    # Reply to someone from inbox: "Priya ko reply karo", "tell Ahmed..."
    reply_patterns = ["reply karo", "ko bolo", "ko batao", "tell ", "reply to "]
    if any(p in text_lower for p in reply_patterns):
        # Extract contact name and instruction
        for p in reply_patterns:
            if p in text_lower:
                parts = text_lower.split(p, 1)
                contact = parts[0].strip().split()[-1] if parts[0].strip() else ""
                instruction = parts[1].strip() if len(parts) > 1 else ""
                if contact:
                    return await inbox.draft_reply(db, user_id, contact, instruction)

    # ── LAYER 2.7: Email intelligence ──────────────────────────
    from . import email_service
    email_triggers = ["check mail", "check my mail", "check email", "my mail", "emails",
                       "mail dikhao", "email dikhao", "mail check", "inbox mail",
                       "connect email", "gmail guide", "app password", "gmail setup",
                       "email kaise connect", "how to connect email",
                       "summarize mail", "email summary", "mail summary", "important mail"]
    if any(kw in text_lower for kw in email_triggers) or text_lower.startswith("connect email"):
        return await email_service.handle_email_command(db, user_id, text)

    # ── LAYER 3.5: Let intent-based skills through ───────────────
    # These MUST go to agent.py's intent detection, not prebuilt
    intent_keywords = [
        "remind", "yaad", "reminder", "set reminder",
        "email", "mail", "bhejo", "send email",
        "meeting", "note", "meeting note", "just had a meeting", "met with",
        "contact", "number", "ka number", "phone number",
        "business card", "scanned a card",
        "teach me", "learn a", "learn to", "word of the day", "practice ",
        "teach me a", "teach me one", "teach me basic", "teach me how",
        "sikhao", "seekho", "padhao",
    ]
    if any(kw in text_lower for kw in intent_keywords):
        return ""  # Let agent.py handle via intent detection

    # ── LAYER 4: General Chat ────────────────────────────────────
    system = await _build_system_prompt(db, user_id, user, soul)
    reply = await call_gemini(system, text, user_id=user_id)

    # ── LAYER 5: Background Skill Builder ────────────────────────
    soul_prompt = soul.system_prompt or ""
    asyncio.create_task(_maybe_build_bg(user_id, text, reply, soul_prompt))

    return reply


# ── LLM Signal Handler ───────────────────────────────────────────

async def _handle_llm_signal(
    db: AsyncSession, user_id: str, user: User, soul: AgentSoul,
    text: str, signal: str, image_base64: str = None,
) -> str:
    """Handle __LLM_*__ signals from prebuilt skills that need specialized LLM processing."""

    system = await _build_system_prompt(db, user_id, user, soul)

    if signal == "__LLM_NUTRITION__":
        return await call_llm(
            "flash",
            system + "\n\nYou are a nutrition expert. Estimate calories, protein, carbs, fat for the food described. Be specific with numbers. Keep it short for WhatsApp.",
            text, user_id=user_id, max_tokens=400,
        )

    if signal == "__LLM_MEDICAL_VISION__" and image_base64:
        return await call_llm(
            "pro",
            "You are a medical image analysis assistant. Analyze this medical image (Xray, scan, report) and describe findings. Be thorough but concise. Always add disclaimer: 'This is AI analysis — consult your doctor for diagnosis.'",
            text or "Analyze this medical image.",
            image_base64=image_base64, user_id=user_id, max_tokens=600,
        )

    if signal == "__LLM_INVOICE__":
        return await call_llm(
            "flash",
            system + "\n\nDraft a professional invoice or quotation based on the user's description. Format it cleanly for WhatsApp. Include: item, quantity, rate, total, taxes if mentioned.",
            text, user_id=user_id, max_tokens=600,
        )

    if signal == "__LLM_PANCHANG__":
        return await call_llm(
            "flash",
            "You are a Vedic astrology expert. Provide today's Panchang based on your knowledge. Include: Tithi, Nakshatra, Yoga, Karana, Rahu Kaal. Be accurate for Indian Standard Time. Keep it WhatsApp-friendly.",
            text, user_id=user_id, max_tokens=400,
        )

    if signal == "__LLM_KUNDLI__":
        return await call_llm(
            "flash",
            "You are a Vedic astrology expert. Based on the birth details provided, describe the key aspects of the person's kundli — Lagna (ascendant), Moon sign, key planetary placements, and any notable yogas. Be specific and warm.",
            text, user_id=user_id, max_tokens=600,
        )

    if signal.startswith("__LLM_HOROSCOPE__"):
        rashi = signal.replace("__LLM_HOROSCOPE__", "")
        from datetime import datetime
        today = datetime.now().strftime("%d %b %Y")
        return await call_llm(
            "flash",
            f"You are a Vedic astrologer. Give today's ({today}) horoscope for {rashi} (rashifal). Include: career, health, relationships, lucky color/number. Be warm, positive but honest. Match user's language. Keep it short for WhatsApp.",
            f"Today's rashifal for {rashi}", user_id=user_id, max_tokens=300,
        )

    if signal.startswith("__LLM_MUHURAT__"):
        event = signal.replace("__LLM_MUHURAT__", "")
        return await call_llm(
            "flash",
            f"You are a Vedic astrology expert. Suggest the next 2-3 auspicious dates/times (shubh muhurat) for {event}. Consider current month's tithi, nakshatra, and planetary positions. Be specific with dates. Keep it WhatsApp-friendly.",
            f"Shubh muhurat for {event}", user_id=user_id, max_tokens=400,
        )

    if signal == "__LLM_VASTU__":
        return await call_llm(
            "flash",
            system + "\n\nYou are a Vastu Shastra expert. Answer the user's Vastu question with specific, practical advice about directions, placements, colors, and remedies. Keep it actionable.",
            text, user_id=user_id, max_tokens=400,
        )

    if signal == "__LLM_PLANETS__":
        return await call_llm(
            "flash",
            "You are a Vedic astrologer. Describe the current approximate planetary positions (graha sthiti) based on your knowledge of planetary cycles. Mention any retrograde planets. Note that exact positions may vary slightly.",
            text, user_id=user_id, max_tokens=400,
        )

    return ""


# ── Image Routing ────────────────────────────────────────────────

async def _handle_image(
    db: AsyncSession, user_id: str, user: User, soul: AgentSoul,
    text: str, image_base64: str, business_type: str,
) -> str:
    """Route image to the right handler based on vertical and content."""

    # Jewelry vertical: try GemLens first for jewelry photos
    if prebuilt_skills.get_user_vertical(business_type) == "jewelry":
        context = {"image_base64": image_base64}
        gemlens_result = await prebuilt_skills.gemlens_analyze("", context)
        if gemlens_result and not gemlens_result.startswith("__"):
            return gemlens_result

    # Health vertical: medical images get Pro Vision
    if prebuilt_skills.get_user_vertical(business_type) == "health":
        q = (text or "").lower()
        if any(w in q for w in ["xray", "x-ray", "scan", "mri", "ct", "report", "medical"]):
            return await call_llm(
                "pro",
                "You are a medical image analysis assistant. Analyze this image thoroughly. Describe findings clearly. Add disclaimer: 'This is AI analysis — consult your doctor.'",
                text or "Analyze this medical image.",
                image_base64=image_base64, user_id=user_id, max_tokens=600,
            )

    # Food photo detection — calorie counting
    q = (text or "").lower()
    food_words = ["food", "lunch", "dinner", "breakfast", "khana", "meal", "kha",
                   "calorie", "calories", "nutrition", "snack", "nashta"]
    if any(w in q for w in food_words) or not text:
        # Try food analysis first — if no text caption, could be food
        from .personality import analyze_food_photo
        food_result = await analyze_food_photo(image_base64, user_id)
        if food_result and "calorie" in food_result.lower():
            return food_result

    # General image analysis — use Flash with Soul + personality context
    system = await _build_system_prompt(db, user_id, user, soul)
    return await call_gemini(
        system + "\n\nThe user sent an image. Analyze it helpfully. If it looks like food, estimate calories. If it's a product, describe it. Be warm and conversational.",
        text or "What do you see?",
        image_base64=image_base64,
        user_id=user_id,
    )


# ── Context Builder ──────────────────────────────────────────────

async def _build_context(db: AsyncSession, user_id: str, image_base64: str = None) -> dict:
    """Build context dict for prebuilt skills — includes user memory and image."""
    mem_result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id)
    )
    memories = mem_result.scalars().all()

    return {
        "user_id": user_id,
        "image_base64": image_base64,
        "user_memory": [{"key": m.key, "value": m.value} for m in memories],
    }


async def _build_system_prompt(
    db: AsyncSession, user_id: str, user: User, soul: AgentSoul
) -> str:
    """Build the full system prompt — same as agent.py but accessible from orchestrator."""
    name = user.name or "this user"

    mem_result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id)
    )
    memories = mem_result.scalars().all()
    memory_text = "\n".join([f"- {m.key}: {m.value}" for m in memories]) if memories else "None yet."

    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .limit(20)
    )
    conversations = conv_result.scalars().all()
    conv_text = "\n".join(
        [f"{c.role}: {c.content}" for c in reversed(list(conversations))]
    ) if conversations else "No recent conversation."

    now = datetime.now().strftime("%d %b %Y, %I:%M %p IST")

    from .personality import PERSONALITY_LAYER
    from . import image_session

    # Check if user has an active image in context
    image_context = ""
    active_img = await image_session.get_active_image(db, user_id)
    if active_img:
        history = await image_session.get_image_history(db, user_id, limit=5)
        history_text = "\n".join(f"  - {h['source']}: {h['description']}" for h in history if h.get('description'))
        image_context = f"""

IMAGE IN CONTEXT:
You have an active image from the user (source: {active_img['source']}).
Description: {active_img.get('description', 'User uploaded image')}
Image history (most recent first):
{history_text}

IMPORTANT: The user may reference this image — "render it", "change the stone",
"enhance it", "make an ad". You KNOW what image they mean. Don't ask "which image?"
If they switch topics and come back — you still remember the image.
Say "show me the original" or "pehle wala dikhao" to recall previous versions."""

    return f"""You are Sam -- a personal WhatsApp assistant for {name}.
{PERSONALITY_LAYER}
{image_context}

ABOUT {name.upper()}:
{soul.system_prompt or 'Still learning about this user.'}

LANGUAGE RULE (STRICTLY FOLLOW):
User's chosen language: {soul.language_preference or 'english'}
You MUST respond in {soul.language_preference or 'english'}. ALWAYS.
Do NOT switch to Hindi unless user writes in Hindi first.
If user chose English — respond in English.
If user chose Tamil — respond in Tamil.
If user chose Gujarati — respond in Gujarati.
NEVER assume Hindi is the default. Respect the user's choice.

YOUR RULES:
- Never make unauthorized commitments on behalf of {name}
- When unsure, ask rather than guess
- Keep responses SHORT -- this is WhatsApp, not email

YOUR MEMORY:
{memory_text}

RECENT CONVERSATION:
{conv_text}

Current time: {now}"""


# ── Background Skill Builder ────────────────────────────────────

async def _maybe_build_bg(user_id: str, text: str, reply: str, soul_prompt: str):
    """Background: detect if Sam should build a new skill for this user."""
    try:
        from ..database import async_session
        async with async_session() as db:
            notification = await skill_builder.maybe_build_skill(
                db, user_id, text, reply, soul_prompt
            )
            if notification:
                db.add(Conversation(user_id=user_id, role="assistant", content=notification))
                await db.commit()
                logger.info(f"[{user_id}] SKILL BUILT: {notification[:80]}")
    except Exception as e:
        logger.error(f"[{user_id}] Background skill build error: {e}", exc_info=True)
