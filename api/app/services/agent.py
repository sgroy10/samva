import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import AgentSoul, User, Conversation, UserMemory
from .llm import call_gemini, call_gemini_json, transcribe_audio
from .onboarding import handle_onboarding
from . import gold, stocks, email_draft, meeting, contacts, reminders, web_search
from .confidence import tag_confidence
from . import network as network_svc
from . import skill_builder

logger = logging.getLogger("samva.agent")


def _sanitize_for_db(text: str) -> str:
    """Remove surrogate characters that PostgreSQL/asyncpg rejects."""
    if not text:
        return ""
    # Encode to utf-8, replacing surrogates, then decode back
    return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


HELP_TEXT = """👋 *I'm Sam — here's everything I can do:*

━━━━━━━━━━━━━━━━━━━━━━━━━━

💬 *Chat* — Ask me anything. I know your business, your preferences, your context.

📧 *Email*
• "Check my mail" — I read and summarize your inbox
• Voice note or type anything → I draft a professional email → you confirm → I send it
• To connect: send "connect email your@email.com password"

📸 *Business Card* — Photo any card, I extract and save the contact forever.
• "Vikram ka number?" — I find it instantly

🎙️ *Meeting Notes* — Send a voice note after any meeting.
• I transcribe, structure who/what/price/next-steps, save contacts, set reminders, email you a summary.

⏰ *Reminders*
• "Remind me tomorrow 9am to call Ramesh"
• "Mummy ka birthday 14 April — hamesha yaad dilana"
• Works: daily, weekly, monthly, yearly

📊 *Gold Brief* (for jewellers)
• Every morning at 9am: 24K, 22K, 18K, silver, international prices, buy/hold view

📈 *Stocks*
• "Watch Reliance" — I track it
• "Alert me when TCS crosses 4000" — I notify you
• "My stocks" — I show your watchlist with live prices

🔍 *Web Search* — "What's the weather in Mumbai?" "RBI repo rate?"

🧠 *Memory* — "My COD charge is ₹50" — I remember permanently. Never ask twice.

━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 *Tips:*
• Talk in any language — Hindi, English, Gujarati, Tamil, anything
• Send voice notes — I understand speech
• I learn from every conversation — the more you use me, the better I get

Type *help* anytime to see this again."""


INTENT_PROMPT = """You are an intent classifier for Sam, a WhatsApp personal assistant.
Classify the user's message into ONE intent:

- chat: general conversation, questions, advice
- email_read: wants to check/read emails
- email_send: wants to send/compose an email
- email_draft_confirm: confirming to send a drafted email (yes/send/bhej do/haan)
- email_draft_cancel: cancelling a drafted email (no/cancel/mat bhejo/nahi)
- business_card: sent a photo of a business card to save
- meeting_note: voice note or text describing a meeting/conversation they just had
- reminder_set: wants to set a reminder or alarm
- contact_lookup: looking up a saved contact
- web_search: needs current/live information from the web
- memory_update: telling Sam to remember something specific
- image_general: sent a general image (not business card)
- stock_watch: wants to add/remove stocks to watchlist
- stock_check: wants current stock prices or portfolio status
- gold_rate: asking about gold price, silver price, rates, sona ka bhav, current gold, aaj ka rate

Return JSON: {"intent": "the_intent", "confidence": 0.0-1.0}
If image is present and looks like a business card, use "business_card".
If image is present but not a card, use "image_general".
If it's a voice transcription about a meeting, use "meeting_note".
If asking about gold/silver/rates, ALWAYS use gold_rate."""


async def process_message(
    db: AsyncSession,
    user_id: str,
    text: str,
    message_type: str = "text",
    image_base64: str = None,
    audio_base64: str = None,
    sender_jid: str = None,
) -> dict:
    """Main message handler. Routes to appropriate skill."""
    try:
        # Get user
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"reply": "I don't recognize this session. Please sign up at samva.in", "actions": []}

        # Subscription check — paused users can't use Sam (admin exempt)
        if user.status == "paused" and user.plan != "admin":
            return {
                "reply": (
                    "Your Samva subscription has expired. Sam is paused.\n\n"
                    f"Renew at samva.in/renew?id={user_id} to continue using Sam.\n"
                    "\u20b9299/month — all features included."
                ),
                "actions": [],
            }

        # Get soul
        result = await db.execute(
            select(AgentSoul).where(AgentSoul.user_id == user_id)
        )
        soul = result.scalar_one_or_none()

        # Handle audio transcription
        original_text = text
        if audio_base64:
            transcription = await transcribe_audio(audio_base64, user_id)
            if transcription:
                text = transcription
                logger.info(f"Transcribed audio for {user_id}: {text[:100]}")
            else:
                return {"reply": "I couldn't understand that voice note. Could you try again or type it out?", "actions": []}

        # Check if still onboarding
        if not soul or not soul.onboarding_complete:
            if not text:
                return {"reply": "Send me a text or voice message to get started!", "actions": []}

            # Save user message
            db.add(Conversation(user_id=user_id, role="user", content=text))
            await db.commit()

            reply = await handle_onboarding(db, user_id, text)

            # Save assistant reply
            db.add(Conversation(user_id=user_id, role="assistant", content=reply))
            await db.commit()

            return {"reply": reply, "actions": []}

        # Fast commands — no AI cost
        lower = (text or "").strip().lower()

        # Language change — user can switch anytime
        from .language import normalize_language, LANGUAGE_NAMES
        lang_triggers = ["change language", "language change", "switch language",
                          "speak in", "talk in", "baat karo", "mein baat karo",
                          "change to english", "change to hindi", "english mein",
                          "hindi mein", "gujarati mein", "tamil mein", "telugu mein",
                          "malayalam mein", "bengali mein", "marathi mein",
                          "set language", "my language"]
        if any(t in lower for t in lang_triggers):
            # Extract the language
            new_lang = normalize_language(text)
            if new_lang and new_lang != "same":
                from sqlalchemy import update as sql_update
                await db.execute(
                    sql_update(AgentSoul).where(AgentSoul.user_id == user_id)
                    .values(language_preference=new_lang)
                )
                await db.commit()
                lang_name = LANGUAGE_NAMES.get(new_lang, new_lang)
                reply = f"Language changed to *{lang_name}*! \u2705\n\nFrom now on, I'll talk to you in {lang_name}."
                # Also ask about voice language
                reply += f"\n\nVoice notes bhi {lang_name} mein? Ya kuch aur?"
            else:
                from .language import get_language_question
                reply = get_language_question()
            db.add(Conversation(user_id=user_id, role="user", content=text))
            db.add(Conversation(user_id=user_id, role="assistant", content=reply))
            await db.commit()
            return {"reply": reply, "actions": []}

        # Voice language change
        voice_triggers = ["voice language", "voice mein", "voice note language",
                           "awaaz mein", "bolne ki language", "speak language"]
        if any(t in lower for t in voice_triggers):
            new_lang = normalize_language(text)
            if new_lang and new_lang != "same":
                from sqlalchemy import update as sql_update
                await db.execute(
                    sql_update(AgentSoul).where(AgentSoul.user_id == user_id)
                    .values(voice_language=new_lang)
                )
                await db.commit()
                lang_name = LANGUAGE_NAMES.get(new_lang, new_lang)
                reply = f"Voice notes ab *{lang_name}* mein! \u2705"
            else:
                from .language import get_voice_language_question
                reply = get_voice_language_question()
            db.add(Conversation(user_id=user_id, role="user", content=text))
            db.add(Conversation(user_id=user_id, role="assistant", content=reply))
            await db.commit()
            return {"reply": reply, "actions": []}

        # "Call me" — user wants Sam to call them immediately
        call_triggers = {"call me", "mujhe call karo", "call karo", "urgent call",
                          "phone karo", "ring me", "call kar", "mujhe phone karo"}
        if lower in call_triggers:
            user_phone = user.phone if user.phone and user.phone.startswith("+") else f"+91{user.phone}" if user.phone else None
            if user_phone:
                from .voice import make_outbound_call
                call_result = await make_outbound_call(
                    user_phone,
                    "Namaste! Main Sam hoon, aapki Samva assistant. Aapne mujhe call karne ko bola tha. Boliye, kya madad chahiye?",
                )
                if call_result.get("success"):
                    reply = "Call aa rahi hai aapke phone pe! \U0001f4de"
                else:
                    reply = "Call nahi lag paayi. WhatsApp pe baat karte hain."
            else:
                reply = "Aapka phone number nahi mila. Pehle apna number save karo."
            db.add(Conversation(user_id=user_id, role="user", content=text))
            db.add(Conversation(user_id=user_id, role="assistant", content=reply))
            await db.commit()
            return {"reply": reply, "actions": []}

        # Network permission response — ONLY if the last Sam message was the permission question
        # Check recent conversation to see if Sam just asked about network
        from sqlalchemy import desc as sql_desc
        last_sam = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id, Conversation.role == "assistant"
            ).order_by(sql_desc(Conversation.created_at)).limit(1)
        )
        last_msg = last_sam.scalar_one_or_none()
        if last_msg and "connect kar sakti hoon" in (last_msg.content or ""):
            perm_reply = await network_svc.handle_permission_response(db, user_id, text)
            if perm_reply:
                # If they said yes, next message will be their need/offer profile
                db.add(Conversation(user_id=user_id, role="user", content=text))
                db.add(Conversation(user_id=user_id, role="assistant", content=perm_reply))
                await db.commit()
                return {"reply": perm_reply, "actions": []}

        # Network profile save (user describing their need/offer after saying yes)
        if soul.network_permission is True:
            from ..models import NetworkConnection
            nc_result = await db.execute(
                select(NetworkConnection).where(
                    NetworkConnection.user_id == user_id,
                    NetworkConnection.is_active == True,
                )
            )
            if not nc_result.scalar_one_or_none():
                # No profile yet — this message might be their need/offer description
                if len(text) > 15 and any(w in lower for w in ["chahiye", "need", "offer", "karti", "karta", "dhundh", "looking", "provide", "supply"]):
                    reply = await network_svc.save_network_profile(db, user_id, text)
                    db.add(Conversation(user_id=user_id, role="user", content=text))
                    db.add(Conversation(user_id=user_id, role="assistant", content=reply))
                    await db.commit()
                    return {"reply": reply, "actions": []}

        # Email commands handled by orchestrator's email_service (not the old email_draft)
        # "connect email" passes through to orchestrator layer 2.7

        # Gold brief control — stop/start/change time
        if lower in ("stop gold brief", "stop brief", "no gold brief", "band karo brief",
                      "unsubscribe gold", "stop daily brief", "daily brief band karo"):
            from sqlalchemy import update as sql_update
            await db.execute(
                sql_update(AgentSoul).where(AgentSoul.user_id == user_id)
                .values(daily_brief_enabled=False)
            )
            await db.commit()
            reply = "Gold brief band kar diya. Ab 9 AM pe nahi aayega.\n\nKabhi bhi 'start gold brief' bolo toh phir se chalu ho jayega."
            db.add(Conversation(user_id=user_id, role="user", content=text))
            db.add(Conversation(user_id=user_id, role="assistant", content=reply))
            await db.commit()
            return {"reply": reply, "actions": []}

        if lower in ("start gold brief", "start brief", "gold brief chalu karo",
                      "subscribe gold", "start daily brief", "brief chalu karo"):
            from sqlalchemy import update as sql_update
            await db.execute(
                sql_update(AgentSoul).where(AgentSoul.user_id == user_id)
                .values(daily_brief_enabled=True)
            )
            await db.commit()
            reply = "Gold brief chalu! Roz subah aapko rates milenge.\n\nTime change karna ho toh bolo: 'brief 8am' ya 'brief 7:30am'"
            db.add(Conversation(user_id=user_id, role="user", content=text))
            db.add(Conversation(user_id=user_id, role="assistant", content=reply))
            await db.commit()
            return {"reply": reply, "actions": []}

        # Change brief time — "brief 8am", "gold brief 7:30am", "brief time 10am"
        import re
        brief_time_match = re.match(r"(?:gold\s+)?brief\s+(?:time\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)", lower)
        if brief_time_match:
            import datetime as dt
            h = int(brief_time_match.group(1))
            m = int(brief_time_match.group(2) or 0)
            ampm = brief_time_match.group(3)
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            new_time = dt.time(h, m)
            from sqlalchemy import update as sql_update
            await db.execute(
                sql_update(AgentSoul).where(AgentSoul.user_id == user_id)
                .values(daily_brief_time=new_time, daily_brief_enabled=True)
            )
            await db.commit()
            display = f"{h if h <= 12 else h-12}:{str(m).zfill(2)} {'AM' if h < 12 else 'PM'}"
            reply = f"Done! Gold brief ab roz *{display}* pe aayega."
            db.add(Conversation(user_id=user_id, role="user", content=text))
            db.add(Conversation(user_id=user_id, role="assistant", content=reply))
            await db.commit()
            return {"reply": reply, "actions": []}

        # Gold rate fast-path — ONLY exact matches, not partial word matches
        gold_triggers = {"gold", "gold rate", "gold rates", "gold price", "rates", "rate",
                         "sona", "sona ka bhav", "bhav", "aaj ka rate", "current gold",
                         "rates dikhao", "silver rate", "silver price", "gold brief",
                         "gold today", "how much is gold"}
        if lower in gold_triggers:
            reply = await gold.get_gold_brief(db, user_id)
            if reply:
                db.add(Conversation(user_id=user_id, role="user", content=text))
                db.add(Conversation(user_id=user_id, role="assistant", content=reply))
                await db.commit()
                return {"reply": reply, "actions": []}

        if lower in ("help", "menu", "commands", "kya kar sakti ho", "kya kya kar sakti ho", "what can you do"):
            db.add(Conversation(user_id=user_id, role="user", content=text))
            db.add(Conversation(user_id=user_id, role="assistant", content=HELP_TEXT))
            await db.commit()
            return {"reply": HELP_TEXT, "actions": []}

        # ══════════════════════════════════════════════════════════
        # THE ORCHESTRATOR — routes everything
        # Prebuilt skills → custom skills → image routing → LLM chat
        # All invisible to the user. Sam just works.
        # ══════════════════════════════════════════════════════════
        from .orchestrator import orchestrate

        # Save user message
        db.add(Conversation(user_id=user_id, role="user", content=text or "[media]"))
        await db.commit()

        # Orchestrate
        reply = await orchestrate(db, user_id, user, soul, text, message_type, image_base64)

        # Handle dedicated skills that orchestrator doesn't cover
        # (email, meeting notes, reminders, contacts — these need DB writes)
        if not reply:
            intent_data = await _detect_intent(text, image_base64, user_id)
            intent = intent_data.get("intent", "chat")
            logger.info(f"Intent fallback for {user_id}: {intent}")
            reply = await _route_skill(db, user_id, user, soul, intent, text, image_base64)

        # Save assistant reply
        db.add(Conversation(user_id=user_id, role="assistant", content=reply))
        await db.commit()

        return {"reply": reply, "actions": []}

    except Exception as e:
        logger.error(f"Error processing message for {user_id}: {e}", exc_info=True)
        return {"reply": "Something went wrong on my end. Let me try again in a moment.", "actions": []}


async def _detect_intent(text: str, image_base64: str = None, user_id: str = "") -> dict:
    """Detect message intent using Gemini."""
    extra = ""
    if image_base64:
        extra = " [Image attached]"
    if not text and image_base64:
        text = "[User sent an image]"

    result = await call_gemini_json(
        INTENT_PROMPT,
        f"User message: {text}{extra}",
        image_base64=image_base64,
        user_id=user_id,
    )

    if "error" in result:
        return {"intent": "image_general" if image_base64 else "chat", "confidence": 0.5}
    return result


async def _build_system_prompt(
    db: AsyncSession, user_id: str, user: User, soul: AgentSoul
) -> str:
    """Build the full system prompt for Sam."""
    name = user.name or "this user"

    # Get memories
    mem_result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id)
    )
    memories = mem_result.scalars().all()
    memory_text = "\n".join([f"- {m.key}: {m.value}" for m in memories]) if memories else "None yet."

    # Get recent conversations
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

    return f"""You are Sam \u2014 a personal WhatsApp assistant for {name}.

YOUR IDENTITY: You are warm, helpful, concise, and match the user's language automatically. You respond in short WhatsApp-friendly messages. Never send walls of text.

ABOUT {name.upper()}:
{soul.system_prompt or 'Still learning about this user.'}

YOUR RULES:
- Never make unauthorized commitments on behalf of {name}
- When unsure, ask {name} before responding to others
- Keep responses SHORT \u2014 this is WhatsApp, not email
- Match the user's language (Hindi, English, Gujarati, etc.)
- Use emojis sparingly and naturally

YOUR MEMORY:
{memory_text}

RECENT CONVERSATION:
{conv_text}

Current time: {now}"""


async def _route_skill(
    db: AsyncSession,
    user_id: str,
    user: User,
    soul: AgentSoul,
    intent: str,
    text: str,
    image_base64: str = None,
) -> str:
    """Route to the appropriate skill handler."""
    try:
        if intent == "business_card" and image_base64:
            return await contacts.process_business_card(db, user_id, image_base64)

        elif intent == "image_general" and image_base64:
            system = await _build_system_prompt(db, user_id, user, soul)
            return await call_gemini(
                system + "\n\nThe user sent an image. Analyze it and respond helpfully based on who they are.",
                text or "What do you see?",
                image_base64=image_base64,
                user_id=user_id,
            )

        elif intent == "meeting_note":
            return await meeting.process_meeting_note(db, user_id, text)

        elif intent == "reminder_set":
            return await reminders.create_reminder(db, user_id, text)

        elif intent == "contact_lookup":
            return await contacts.lookup_contact(db, user_id, text)

        elif intent == "email_send":
            return await email_draft.draft_email(db, user_id, text)

        elif intent == "email_draft_confirm":
            return await email_draft.confirm_send(db, user_id)

        elif intent == "email_draft_cancel":
            return await email_draft.cancel_draft(user_id)

        elif intent == "email_read":
            return await email_draft.read_emails(db, user_id)

        elif intent == "memory_update":
            return await _update_memory(db, user_id, text)

        elif intent == "stock_watch":
            return await stocks.add_to_watchlist(db, user_id, text)

        elif intent == "stock_check":
            return await stocks.get_watchlist_brief(db, user_id)

        elif intent == "gold_rate":
            return await gold.get_gold_brief(db, user_id)

        elif intent == "web_search":
            # Real web search via Playwright, then summarize with Gemini
            search_results = await web_search.search(text, user_id)
            if search_results:
                system = await _build_system_prompt(db, user_id, user, soul)
                return await call_gemini(
                    system + "\n\nYou searched the web for the user. Summarize these search results concisely for WhatsApp. Give the key answer first, then details. Cite sources if relevant.",
                    f"User asked: {text}\n\nWeb search results:\n{search_results[:3000]}",
                    user_id=user_id,
                )
            else:
                # Playwright failed — fallback to Gemini knowledge
                system = await _build_system_prompt(db, user_id, user, soul)
                return await call_gemini(
                    system + "\n\nThe user is asking about current/live information. Answer to the best of your knowledge. Mention if data may not be current.",
                    text,
                    user_id=user_id,
                )

        else:
            # General chat — with confidence tagging
            system = await _build_system_prompt(db, user_id, user, soul)
            raw_reply = await call_gemini(system, text, user_id=user_id)
            reply = await tag_confidence(
                raw_reply, soul.system_prompt[:300], user_id,
                language=soul.language_preference or "auto",
            )
            return reply

    except Exception as e:
        logger.error(f"Skill error ({intent}) for {user_id}: {e}", exc_info=True)
        system = await _build_system_prompt(db, user_id, user, soul)
        return await call_gemini(system, text, user_id=user_id)


# Dead code removed — skill building is handled by orchestrator._maybe_build_bg


async def _update_memory(db: AsyncSession, user_id: str, text: str) -> str:
    """Extract and save a memory from the user's message."""
    extracted = await call_gemini_json(
        """Extract what the user wants you to remember.
Return JSON: {"key": "short_key_name", "value": "the value to remember"}
Examples:
- "Remember my wife's name is Priya" -> {"key": "wife_name", "value": "Priya"}
- "Our shop closes at 8pm" -> {"key": "shop_closing_time", "value": "8:00 PM"}""",
        text,
        user_id=user_id,
    )

    if "error" in extracted:
        return "I'll remember that! But could you tell me more specifically what to note down?"

    key = extracted.get("key", "")
    value = extracted.get("value", "")

    if not key or not value:
        return "Could you be more specific about what you'd like me to remember?"

    # Upsert memory
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == key
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = value
    else:
        db.add(UserMemory(user_id=user_id, key=key, value=value))

    await db.commit()
    return f"Noted! I'll remember: {key} = {value}"


async def check_alerts(db: AsyncSession, user_id: str) -> list[str]:
    """Check for proactive alerts (reminders, stock alerts, etc.)."""
    alerts = []

    try:
        # Check due reminders
        reminder_alerts = await reminders.check_due_reminders(db, user_id)
        alerts.extend(reminder_alerts)

        # Check stock alerts
        stock_alerts = await stocks.check_alerts(db, user_id)
        alerts.extend(stock_alerts)

        # Check if 9am gold brief is needed (jeweller users only, once per day)
        if await gold.should_get_gold_brief(db, user_id):
            brief = await gold.get_gold_brief(db, user_id)
            if brief:
                alerts.append(brief)
                await gold.mark_brief_sent(db, user_id)

        # Check gold price change alerts (jeweller users, every 15-min cron)
        price_alert = await gold.check_price_alerts(db, user_id)
        if price_alert:
            alerts.append(price_alert)

        # Chat intelligence — urgent message insights
        from .chat_intelligence import get_undelivered_insights
        chat_alert = await get_undelivered_insights(db, user_id)
        if chat_alert:
            alerts.append(chat_alert)

        # Personality nudges — lunch, evening, water, motivation, festivals
        from .personality import get_proactive_nudges
        nudges = await get_proactive_nudges(db, user_id)
        alerts.extend(nudges)

    except Exception as e:
        logger.error(f"Alert check error for {user_id}: {e}", exc_info=True)

    return alerts
