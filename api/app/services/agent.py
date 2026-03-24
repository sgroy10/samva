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

logger = logging.getLogger("samva.agent")


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
                    "\u20b9999/month — all features included."
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

        # Network permission response (right after onboarding asks)
        # Check if user hasn't set permission yet (None means just asked)
        if soul.network_permission is None or (soul.onboarding_complete and not soul.network_permission):
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

        # Email connect command: "connect email user@gmail.com password123"
        if lower.startswith("connect email "):
            parts = text.strip().split(None, 3)  # connect email addr pass
            if len(parts) >= 4:
                email_addr = parts[2]
                password = parts[3]
                reply = await email_draft.connect_email(db, user_id, email_addr, password)
                db.add(Conversation(user_id=user_id, role="user", content="[connect email]"))
                db.add(Conversation(user_id=user_id, role="assistant", content=reply))
                await db.commit()
                return {"reply": reply, "actions": []}

        # Gold rate fast-path — no AI cost for common rate queries
        gold_triggers = {"gold", "gold rate", "gold rates", "gold price", "rates", "rate",
                         "sona", "sona ka bhav", "bhav", "aaj ka rate", "current gold",
                         "rates dikhao", "silver", "silver rate", "silver price", "gold brief"}
        if lower in gold_triggers or (lower.startswith("gold") and len(lower) < 20):
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

        # Active user - detect intent
        intent_data = await _detect_intent(text, image_base64, user_id)
        intent = intent_data.get("intent", "chat")
        logger.info(f"Intent for {user_id}: {intent} (confidence: {intent_data.get('confidence', 0)})")

        # Save user message
        db.add(Conversation(user_id=user_id, role="user", content=text or "[media]"))
        await db.commit()

        # Route to skill
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
            return await tag_confidence(
                raw_reply, soul.system_prompt[:300], user_id,
                language=soul.language_preference or "auto",
            )

    except Exception as e:
        logger.error(f"Skill error ({intent}) for {user_id}: {e}", exc_info=True)
        system = await _build_system_prompt(db, user_id, user, soul)
        return await call_gemini(system, text, user_id=user_id)


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

    except Exception as e:
        logger.error(f"Alert check error for {user_id}: {e}", exc_info=True)

    return alerts
