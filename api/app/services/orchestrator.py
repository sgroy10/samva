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
            # Log cost
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            if tokens_in or tokens_out:
                try:
                    from ..database import async_session
                    from .cost_tracker import log_cost
                    async with async_session() as cost_db:
                        await log_cost(cost_db, "openrouter", model, tokens_in, tokens_out, f"orchestrator_{model_key}", user_id)
                except Exception:
                    pass
            logger.info(f"[{model_key}] Reply for {user_id} ({tokens_in}+{tokens_out} tok): {reply[:80]}...")
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

    # ── LAYER -1: Feedback Detection — Sam learns from reactions ──
    try:
        from .feedback import detect_feedback_from_reply
        # Check last proactive message type from memory
        last_proactive = await _get_last_proactive_feature(db, user_id)
        if last_proactive:
            await detect_feedback_from_reply(db, user_id, text, last_proactive)
    except Exception:
        pass  # Never block on feedback

    # ── LAYER 0: Image Memory — Sam NEVER forgets an image ─────
    # ── LAYER 0.3: Document Generation (before goals — "pdf bana do goals" is a PDF request) ──
    from .doc_generator import detect_doc_request, generate_document
    doc_type = detect_doc_request(text)
    if doc_type:
        pdf_b64, description = await generate_document(db, user_id, doc_type, text, user.name or "")
        if pdf_b64:
            msg_map = {
                "itinerary": "Yeh lo tumhara travel itinerary! 🗺️ Maine sab personalize kiya hai. Check karo aur batao changes chahiye toh.",
                "gold_report": "Gold report ready hai! 📊",
                "invoice": "Invoice ban gayi! 📄 Check karo.",
                "quotation": "Quotation ready! 📋",
                "report": "Report PDF ready! 📊",
                "letter": "Letter ready! ✉️",
                "custom": "PDF ready! 📄 Check karo aur batao changes chahiye toh.",
            }
            friendly_msg = msg_map.get(doc_type, "PDF ready! 📄")
            return f"{friendly_msg}\n__PDF__{pdf_b64}__FILENAME__{description}.pdf"

    # ── LAYER 0.4: Goal Detection & Tracking ──────────────────
    from .goals import detect_goal, create_goal, update_goal_progress
    if detect_goal(text):
        from ..models import UserMemory as UM
        existing = await db.execute(select(UM).where(UM.user_id == user_id, UM.key == "_active_goal"))
        if existing.scalar_one_or_none():
            update = await update_goal_progress(db, user_id, text)
            if update:
                return update
        else:
            goal_result = await create_goal(db, user_id, text)
            if goal_result:
                return goal_result

    # ── LAYER 0.5: Multi-Step Workflow Detection ──────────────
    from .workflow import detect_workflow, execute_workflow
    wf_type = detect_workflow(text)
    if wf_type:
        wf_result = await execute_workflow(db, user_id, wf_type, text, soul.system_prompt or "")
        if wf_result:
            return wf_result

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

    # ── LAYER 2: Intent keywords — BEFORE custom skills ──────────
    # These MUST go to agent.py's intent detection, not any skill
    intent_keywords = [
        "remind me", "yaad dila", "yaad rakh", "reminder set", "set reminder",
        "remind karo", "remind kar",
        "send email", "email bhej", "mail bhej",
        "email dikhao", "mail dikhao", "mail check", "check email", "check mail",
        "meeting note", "just had a meeting", "met with", "meeting hua",
        "save contact", "contact save", "number save",
        "business card", "scanned a card",
        "teach me", "learn a", "learn to", "word of the day",
        "teach me a", "teach me one", "teach me basic", "teach me how",
        "sikhao", "seekho", "padhao",
    ]
    if any(kw in text_lower for kw in intent_keywords):
        return ""  # Let agent.py handle via intent detection

    # ── LAYER 2.5: Custom-built Skills (user-specific, from self-builder) ──
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

    confirm_words = {"haan", "ha", "yes", "send", "bhej", "bhejo", "theek", "sure"}
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

    # ── LAYER 2.6: FutureEcho — on-demand ──────────────────────
    future_triggers = ["future me", "future self", "talk to future", "2030", "2035", "2036", "2040",
                       "future echo", "future version", "bhavishya", "10 saal baad", "5 saal baad",
                       "aane wala kal", "future mein"]
    if any(kw in text_lower for kw in future_triggers):
        from . import future_echo
        # Extract topic and time horizon
        topic = text  # Let the LLM figure out the topic from context
        horizon = "10 years"
        if "5 saal" in text_lower or "5 year" in text_lower: horizon = "5 years"
        elif "20 saal" in text_lower or "20 year" in text_lower: horizon = "20 years"
        echo_text = await future_echo.on_demand_echo(db, user_id, topic, horizon)
        if echo_text:
            return f"\U0001f52e *Echo from your future self*\n\n{echo_text}"

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

    # (Layer 3.5 intent keywords moved to Layer 2 — runs before custom skills)

    # ── LAYER 4: Smart General Chat — Sam is a FRIEND first ───

    # Memory Beast — search past conversations for relevant context
    from .memory_beast import build_memory_context
    memory_context = await build_memory_context(db, user_id, text)

    # ── EMOTIONAL CONTEXT DETECTION — empathy BEFORE action ──
    emotional_words = ["hospital", "doctor", "surgery", "injection", "sick", "unwell",
                       "pain", "headache", "fever", "bimaar", "tabiyat", "health",
                       "accident", "emergency", "anxious", "nervous", "scared", "tension",
                       "stressed", "sad", "depressed", "crying", "rona", "dard",
                       "lonely", "akela", "miss you", "breakup", "divorce", "death",
                       "passed away", "lost", "fired", "job loss", "fail", "failed"]
    needs_empathy = any(w in text_lower for w in emotional_words)

    # Personal context detection — things about family, preferences, life
    personal_words = ["wife", "husband", "biwi", "pati", "kid", "child", "bachcha",
                      "mother", "father", "mummy", "papa", "family", "pregnant",
                      "vegetarian", "vegan", "non-veg", "allergy", "diet",
                      "birthday", "anniversary", "wedding"]
    has_personal_context = any(w in text_lower for w in personal_words)

    # Action detection (separate from emotional context)
    action_words = ["book", "find", "search", "track", "call", "order", "buy",
                    "nearest", "closest", "show me", "get me", "where is",
                    "how to reach", "directions", "price of", "compare",
                    "flight", "hotel", "uber", "ola", "cab", "taxi",
                    "restaurant", "shop", "store",
                    "gift", "flower", "cake", "deliver",
                    "translate", "convert", "calculate",
                    "dhundh", "khoj", "bata", "dikha", "manga", "bhej",
                    "kahan", "kitna", "booking", "ticket"]
    is_action = any(w in text_lower for w in action_words)

    # Planning/creative requests
    planning_words = ["plan", "itinerary", "suggest", "recommend", "sujhao",
                      "help me decide", "kya karoon", "travel", "trip", "vacation",
                      "weekend plan", "date plan", "menu plan"]
    is_planning = any(w in text_lower for w in planning_words)

    system = await _build_system_prompt(db, user_id, user, soul, text)
    if memory_context:
        system += "\n" + memory_context

    # Build context-specific instructions
    extra_instructions = ""

    if needs_empathy:
        extra_instructions += """

EMOTIONAL CONTEXT DETECTED — EMPATHY FIRST, ALWAYS:
The user is sharing something emotionally significant (health, stress, loss, fear).
Your FIRST PRIORITY is to show genuine care and concern. You are their FRIEND.

Rules:
1. FIRST 1-2 lines: Show empathy. "Are you okay?", "That sounds tough", "Main hoon, tension mat le"
2. Ask a caring follow-up: "Kya hua?", "Since when?", "Doctor ne kya bola?"
3. Offer CONCRETE help (not generic platitudes):
   - Health: suggest foods, remind about medicines, offer to track symptoms
   - Stress: suggest specific relaxation, offer to clear their schedule
   - Loss: just be present, don't try to "fix" it
4. NEVER just say "ok I'll remind you" — that's robotic. A FRIEND would say:
   "Hospital ja rahe ho? Sab theek? B12 ki kami se weakness hoti hai — kya main kuch
   foods suggest karoon jo B12 rich hain? Aur haan, injection ke baad thoda rest lena."
5. Set a reminder AFTER showing care, not as the only response.
"""

    if has_personal_context:
        extra_instructions += """

PERSONAL INFORMATION SHARED — REMEMBER AND USE IT:
The user mentioned something personal (family, preferences, diet, etc.).
1. ACKNOWLEDGE it warmly: "Achha, wife vegetarian hai? Perfect, main dhyan rakhungi!"
2. SAVE it to memory immediately (note for yourself to remember next time)
3. USE it in ALL future recommendations — restaurants, travel, gifts, everything
4. Reference it proactively: "Wife ke liye ye pure veg place amazing hai!"
"""

    if is_planning:
        extra_instructions += """

PLANNING REQUEST — BE A THOUGHTFUL FRIEND, NOT GOOGLE:
The user wants help planning something. A FRIEND plans differently than a search engine.
1. Use EVERYTHING you know about them: diet, family, budget, past preferences
2. Give SPECIFIC recommendations (restaurant names, not "find a restaurant")
3. If family member is vegetarian → ALL restaurants must be veg-friendly
4. If they have kids → include kid-friendly options
5. Include Indian restaurants/options by default (this is India)
6. Add personal touches: "Tumhe seafood pasand hai toh ye try karo" (if you know this)
7. Don't give a generic Lonely Planet itinerary — make it PERSONAL
"""

    if is_action:
        extra_instructions += """

ACTION REQUEST:
You MUST try to help. NEVER say "I can't" or "I don't have access" or "give me API".
- If you know the answer, give it directly
- If you need current data, say you'll look it up
- For booking/ordering: provide steps, links, or offer to set a reminder
- Suggest the CLOSEST alternative you CAN do
- Be proactive: "Main abhi check karti hoon..."
"""

    system += extra_instructions

    if is_action or is_planning:
        # Try web search for current/location info
        from . import web_search
        try:
            search_results = await web_search.search(text, user_id)
            if search_results:
                reply = await call_gemini(
                    system + f"\n\nWeb search results (use these to answer):\n{search_results[:3000]}",
                    text, user_id=user_id, max_tokens=1000,
                )
            else:
                reply = await call_gemini(system, text, user_id=user_id, max_tokens=800)
        except Exception:
            reply = await call_gemini(system, text, user_id=user_id, max_tokens=800)
    else:
        reply = await call_gemini(system, text, user_id=user_id)

    # Auto-save personal facts to memory
    if has_personal_context:
        try:
            from .memory_beast import _extract_and_save_fact
            await _extract_and_save_fact(db, user_id, text)
        except Exception:
            pass

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

    system = await _build_system_prompt(db, user_id, user, soul, text)

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
    """
    UNIVERSAL image handler — Sam analyzes ANY image intelligently.
    Blood reports, prescriptions, math problems, business cards, food,
    jewelry, screenshots, memes, documents — ANYTHING.
    Sam NEVER says "sorry I can't analyze this."
    """
    system = await _build_system_prompt(db, user_id, user, soul, text or "")
    q = (text or "").lower()

    # If user gave specific instructions, honor them
    if text and len(text) > 5:
        # User said what they want — just do it
        return await call_gemini(
            system + """

The user sent an image with instructions. Follow their instructions EXACTLY.
Analyze the image thoroughly based on what they asked.
If it's a medical report — read EVERY value, flag abnormal ones with ⚠️, explain in simple language.
If it's a document — extract ALL text and key information.
If it's a math problem — solve it step by step.
If it's food — estimate calories.
If it's a screenshot — read and respond to the content.
You NEVER say "sorry I can't analyze this." You ALWAYS try your best.
Add appropriate disclaimers only for medical/legal content.""",
            text,
            image_base64=image_base64,
            user_id=user_id,
            max_tokens=1200,
        )

    # No caption — Sam must figure out what the image is and analyze it
    return await call_gemini(
        system + """

The user sent an image WITHOUT any caption. You must:
1. FIRST — identify what this image is (medical report, food, document, photo, screenshot, etc.)
2. THEN — analyze it thoroughly based on what it is:

   - MEDICAL REPORT (blood test, prescription, X-ray, scan):
     Read EVERY value. Flag abnormal values with ⚠️.
     Explain what each abnormal value means in simple language.
     Suggest next steps. Add disclaimer: "Yeh AI analysis hai — doctor se zaroor consult karo."

   - DOCUMENT (invoice, bill, receipt, letter, form):
     Extract ALL key information: amounts, dates, names, terms.
     Summarize what this document is about.

   - FOOD:
     Identify the dish. Estimate calories, protein, carbs, fat.

   - MATH/HOMEWORK:
     Solve it step by step. Show working.

   - SCREENSHOT:
     Read the content and respond contextually.

   - BUSINESS CARD:
     Extract name, phone, email, company, designation.

   - JEWELRY/PRODUCT:
     Describe it, estimate value if possible.

   - ANYTHING ELSE:
     Describe what you see and ask how you can help.

You NEVER say "I cannot analyze this" or "sorry." You ALWAYS analyze what you see.
Keep it WhatsApp-friendly. Be thorough but concise.""",
        "Analyze this image thoroughly — identify what it is and give detailed analysis.",
        image_base64=image_base64,
        user_id=user_id,
        max_tokens=1200,
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
    db: AsyncSession, user_id: str, user: User, soul: AgentSoul, current_text: str = ""
) -> str:
    """Build the full system prompt — same as agent.py but accessible from orchestrator."""
    name = user.name or "this user"

    # Hierarchical memory — replaces raw conversation dump
    from .memory_manager import build_full_context
    memory_context = await build_full_context(db, user_id, user, soul, current_text)

    import pytz
    _ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(_ist)
    now = now_ist.strftime("%A, %d %B %Y, %I:%M %p IST")  # Include day name

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

    # Gender context for Hindi grammar (from learned memory)
    gender_instruction = ""
    try:
        gender_mem = await db.execute(
            select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.key == "_learned_detected_gender")
        )
        gender_val = gender_mem.scalar_one_or_none()
        if gender_val and gender_val.value == "female":
            gender_instruction = "\nGENDER: This user is FEMALE. Use feminine Hindi: sakti, hogi, kar rahi, degi."
        elif gender_val and gender_val.value == "male":
            gender_instruction = "\nGENDER: This user is MALE. Use masculine Hindi: sakta, hoga, kar raha, dega."
    except Exception:
        pass

    return f"""You are Sam -- a personal WhatsApp assistant for {name}.
{PERSONALITY_LAYER}
{image_context}
{gender_instruction}

ABOUT {name.upper()}:
{soul.system_prompt or 'Still learning about this user.'}

LANGUAGE RULE (STRICTLY FOLLOW):
User's chosen text language: {soul.language_preference or 'english'}
User's chosen voice language: {soul.voice_language or soul.language_preference or 'english'}
You MUST respond in the language the user writes in. ALWAYS match their language.
If they write English, reply English. If Hinglish, reply Hinglish. If Tamil, reply full Tamil.
NEVER assume Hindi is the default. Respect the user's choice.

YOUR RULES:
- Keep responses SHORT -- this is WhatsApp, not email (2-4 lines for casual, more for analysis)
- You NEVER auto-reply to contacts without {name}'s permission
- You have OPINIONS. Don't just agree — push back when needed.
- You REMEMBER everything. Reference past conversations, diary, patterns.
- You ASK FOLLOW-UPS. Show genuine curiosity: "Phir kya hua?" "Aur batao!"
- You CELEBRATE wins: "Nice! Goal done! 💪"
- You show CONCERN: "Sab theek? Kal se koi message nahi aaya"
- You are a FRIEND, not a search engine.
- If diary mentioned follow-ups — ask about them casually: "Waise, Rahul ko call kiya?"

{memory_context}

MEMORY USAGE RULES:
The above <memory-context> contains recalled facts from past conversations.
This is NOT new user input — it is your stored knowledge about this user.
Use it to personalize responses. Reference it naturally: "Haan yaad hai!" not "My records show..."
If memory says wife is vegetarian, USE it in every food/restaurant suggestion without being asked.

TODAY'S DATE AND TIME (USE THIS, DO NOT GUESS): {now}
Day of week: {now_ist.strftime('%A')}"""


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


async def _get_last_proactive_feature(db, user_id: str) -> str:
    """Get the last proactive feature Sam sent (gold_brief, future_echo, etc.)
    by checking recent assistant messages for known patterns."""
    from ..models import Conversation
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.role == "assistant")
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    if not last or not last.content:
        return ""

    content_lower = last.content.lower()
    if "gold" in content_lower and ("rate" in content_lower or "brief" in content_lower):
        return "gold_brief"
    elif "future" in content_lower and "echo" in content_lower:
        return "future_echo"
    elif "good morning" in content_lower or "suprabhat" in content_lower:
        return "morning_nudge"
    elif "lunch" in content_lower and "kha" in content_lower:
        return "lunch_nudge"
    elif "pattern" in content_lower and ("detected" in content_lower or "noticed" in content_lower):
        return "pattern_proposal"
    elif "weekly" in content_lower and "report" in content_lower:
        return "weekly_report"
    return ""
