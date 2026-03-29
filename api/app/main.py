import logging
import uuid
import hashlib
import hmac
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .config import settings
from .database import get_db, init_db
from .models import User, AgentSoul, EnterpriseInquiry, SessionHealth
from .services.agent import process_message, check_alerts
from .services.onboarding import send_first_message

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("samva.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Samva API starting...")
    await init_db()
    logger.info("Database initialized")
    yield
    logger.info("Samva API shutting down")


app = FastAPI(title="Samva Core API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response Models ---

class MessageRequest(BaseModel):
    text: Optional[str] = ""
    userId: str
    messageType: Optional[str] = "text"
    imageBase64: Optional[str] = None
    audioBase64: Optional[str] = None
    senderJid: Optional[str] = None


class OnboardRequest(BaseModel):
    userId: str
    phone: Optional[str] = ""
    pushName: Optional[str] = ""


class AlertCheckRequest(BaseModel):
    userId: str


class SignupRequest(BaseModel):
    phone: str
    name: Optional[str] = ""


class PaymentVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    userId: str


class EnterpriseRequest(BaseModel):
    name: str
    phone: str
    company: Optional[str] = ""
    system_needed: Optional[str] = ""


# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok", "service": "samva-api"}


@app.post("/message")
async def handle_message(req: MessageRequest, db: AsyncSession = Depends(get_db)):
    """Main message handler — routes through agent."""
    result = await process_message(
        db=db,
        user_id=req.userId,
        text=req.text or "",
        message_type=req.messageType or "text",
        image_base64=req.imageBase64,
        audio_base64=req.audioBase64,
        sender_jid=req.senderJid,
    )

    # If user sent a voice note, Sam replies with a voice note too
    if req.audioBase64 and result.get("reply") and not result["reply"].startswith("__IMAGE__"):
        try:
            from .services.llm import text_to_speech
            from .services.language import get_user_languages
            langs = await get_user_languages(db, req.userId)
            voice_lang = langs.get("voice", "english")
            audio_b64 = await text_to_speech(result["reply"], req.userId, voice_lang)
            if audio_b64:
                result["audio"] = {"data": audio_b64, "mimetype": "audio/mp4"}
        except Exception as e:
            logger.error(f"TTS for voice reply failed: {e}")

    return result


@app.post("/onboard")
async def handle_onboard(req: OnboardRequest, db: AsyncSession = Depends(get_db)):
    """Called when a new user first connects via WhatsApp."""
    messages = await send_first_message(db, req.userId, req.phone, req.pushName)
    return {"messages": messages, "count": len(messages)}


@app.post("/alerts/check")
async def handle_alerts(req: AlertCheckRequest, db: AsyncSession = Depends(get_db)):
    """Check for proactive alerts (called by bridge every 15 min)."""
    alerts = await check_alerts(db, req.userId)
    return {"alerts": alerts, "count": len(alerts)}


def _is_admin_phone(phone: str) -> bool:
    """Check if this phone number is the admin."""
    admin = settings.admin_phone.replace("+", "").replace(" ", "")
    clean = phone.replace("+", "").replace(" ", "")
    if not admin:
        return False
    return clean.endswith(admin) or admin.endswith(clean)


@app.post("/signup")
async def handle_signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    """Collect phone, create user. Admin gets free access, others pay."""
    result = await db.execute(select(User).where(User.phone == req.phone))
    existing = result.scalar_one_or_none()

    if existing:
        user_id = existing.id
    else:
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            phone=req.phone,
            name=req.name or "",
            status="onboarding",
        )
        db.add(user)
        db.add(AgentSoul(user_id=user_id))
        db.add(SessionHealth(user_id=user_id))
        await db.commit()

    # Admin bypass — free access, no payment
    if _is_admin_phone(req.phone):
        result2 = await db.execute(select(User).where(User.id == user_id))
        admin_user = result2.scalar_one_or_none()
        if admin_user:
            admin_user.plan = "admin"
            admin_user.paid_until = datetime(2099, 12, 31)
            await db.commit()
        logger.info(f"Admin signup: {req.phone} -> {user_id}")
        return {"userId": user_id, "skipPayment": True, "admin": True}

    # Create Razorpay order for paying users
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.razorpay.com/v1/orders",
                    auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
                    json={
                        "amount": 29900,
                        "currency": "INR",
                        "receipt": f"samva_{user_id[:8]}",
                        "notes": {"userId": user_id, "phone": req.phone},
                    },
                )
                resp.raise_for_status()
                order = resp.json()

            return {
                "userId": user_id,
                "orderId": order["id"],
                "amount": 299,
                "razorpayKey": settings.razorpay_key_id,
            }
        except Exception as e:
            logger.error(f"Razorpay order creation failed: {e}")
            return {"userId": user_id, "skipPayment": True}
    else:
        return {"userId": user_id, "skipPayment": True}


@app.post("/payment/verify")
async def handle_payment_verify(
    req: PaymentVerifyRequest, db: AsyncSession = Depends(get_db)
):
    """Verify Razorpay payment, activate user, send WhatsApp + email confirmation."""
    if not settings.razorpay_key_secret:
        return {"verified": True}

    # Verify signature
    message = f"{req.razorpay_order_id}|{req.razorpay_payment_id}"
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    if expected != req.razorpay_signature:
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # Update user
    result = await db.execute(select(User).where(User.id == req.userId))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    paid_until = datetime.now() + timedelta(days=30)
    user.razorpay_id = req.razorpay_payment_id
    user.paid_until = paid_until
    user.plan = "standard"
    await db.commit()

    # Build WhatsApp confirmation message
    paid_until_str = paid_until.strftime("%d %b %Y")
    whatsapp_msg = (
        "\u2705 *Payment received! Welcome to Samva.*\n\n"
        "Your Sam is now being set up. You'll receive a QR code "
        "to scan with WhatsApp in the next 30 seconds.\n\n"
        f"Subscription: \u20b9299/month\n"
        f"Valid until: {paid_until_str}\n"
        f"Receipt: {req.razorpay_payment_id}\n\n"
        "Questions? Email hello@samva.in"
    )

    return {
        "verified": True,
        "whatsappMessage": whatsapp_msg,
        "userId": req.userId,
        "paidUntil": paid_until_str,
    }


class RenewRequest(BaseModel):
    userId: str


@app.post("/renew")
async def handle_renew(req: RenewRequest, db: AsyncSession = Depends(get_db)):
    """Renew subscription — extends paid_until by 30 days from current expiry."""
    result = await db.execute(select(User).where(User.id == req.userId))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Admin never needs to renew
    if user.plan == "admin":
        return {"skipPayment": True, "admin": True}

    if settings.razorpay_key_id and settings.razorpay_key_secret:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.razorpay.com/v1/orders",
                    auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
                    json={
                        "amount": 29900,
                        "currency": "INR",
                        "receipt": f"renew_{req.userId[:8]}",
                        "notes": {"userId": req.userId, "type": "renewal"},
                    },
                )
                resp.raise_for_status()
                order = resp.json()

            return {
                "userId": req.userId,
                "orderId": order["id"],
                "amount": 299,
                "razorpayKey": settings.razorpay_key_id,
            }
        except Exception as e:
            logger.error(f"Renewal order failed: {e}")
            raise HTTPException(status_code=500, detail="Payment setup failed")
    else:
        return {"skipPayment": True}


@app.post("/payment/renew-verify")
async def handle_renew_verify(
    req: PaymentVerifyRequest, db: AsyncSession = Depends(get_db)
):
    """Verify renewal payment — extend from current paid_until, not from today."""
    if settings.razorpay_key_secret:
        message = f"{req.razorpay_order_id}|{req.razorpay_payment_id}"
        expected = hmac.new(
            settings.razorpay_key_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        if expected != req.razorpay_signature:
            raise HTTPException(status_code=400, detail="Invalid payment signature")

    result = await db.execute(select(User).where(User.id == req.userId))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Extend from current paid_until (not today) so users don't lose days
    base_date = user.paid_until if user.paid_until and user.paid_until > datetime.now() else datetime.now()
    user.paid_until = base_date + timedelta(days=30)
    user.status = "active"
    user.razorpay_id = req.razorpay_payment_id
    await db.commit()

    paid_until_str = user.paid_until.strftime("%d %b %Y")
    return {
        "verified": True,
        "paidUntil": paid_until_str,
        "whatsappMessage": (
            f"\u2705 *Subscription renewed!*\n\n"
            f"Valid until: {paid_until_str}\n"
            f"Sam is back and ready to help!"
        ),
    }


@app.post("/enterprise")
async def handle_enterprise(
    req: EnterpriseRequest, db: AsyncSession = Depends(get_db)
):
    """Save enterprise inquiry."""
    inquiry = EnterpriseInquiry(
        name=req.name,
        phone=req.phone,
        company=req.company,
        system_needed=req.system_needed,
    )
    db.add(inquiry)
    await db.commit()
    return {"status": "ok"}


# --- Chat Intelligence ---

@app.post("/messages/batch")
async def receive_chat_batch(req: dict, db: AsyncSession = Depends(get_db)):
    """Receives all WhatsApp chats uploaded by bridge every 15 min."""
    from .services.chat_intelligence import store_message_batch, analyze_new_messages
    user_id = req.get("userId", "")
    messages = req.get("messages", [])
    if not user_id or not messages:
        return {"stored": 0}

    await store_message_batch(db, user_id, messages)
    insights = await analyze_new_messages(db, user_id)
    return {"stored": len(messages), "insights": len(insights)}


# --- Inbox Endpoints ---

class InboxStoreRequest(BaseModel):
    userId: str
    chatId: str
    chatName: Optional[str] = ""
    senderName: Optional[str] = ""
    senderId: Optional[str] = ""
    content: str
    fromMe: Optional[bool] = False
    timestamp: Optional[int] = 0


@app.post("/inbox/store")
async def store_inbox(req: InboxStoreRequest, db: AsyncSession = Depends(get_db)):
    """Store a WhatsApp message to Sam's inbox."""
    from .services.inbox import store_message
    await store_message(
        db, req.userId, req.chatId, req.chatName,
        req.senderName, req.senderId, req.content,
        req.fromMe, req.timestamp or int(datetime.now().timestamp()),
    )
    return {"stored": True}


@app.post("/cron/auto-reply")
async def handle_auto_reply(db: AsyncSession = Depends(get_db)):
    """Check for customers waiting 2+ hours. Auto-reply on behalf of owner."""
    from .services.inbox import check_auto_reply_needed
    result = await db.execute(select(User).where(User.status == "active"))
    users = result.scalars().all()

    all_replies = []
    for user in users:
        replies = await check_auto_reply_needed(db, user.id)
        for r in replies:
            r["user_id"] = user.id
        all_replies.extend(replies)

    return {"auto_replies": all_replies, "count": len(all_replies)}


# --- Voice Endpoints (Twilio webhooks) ---

@app.post("/voice/answer")
async def voice_answer(request: Request):
    """Twilio webhook — incoming call. Sam answers and listens."""
    from .services.voice import generate_answer_twiml, identify_caller

    form = await request.form()
    caller = form.get("From", "")
    logger.info(f"[Voice] Incoming call from {caller}")

    # Try to identify the caller
    caller_info = await identify_caller(caller)
    name = caller_info.get("name", "there")

    twiml = generate_answer_twiml(name)
    return Response(content=twiml, media_type="application/xml")


@app.post("/voice/process")
async def voice_process(request: Request):
    """Twilio webhook — user spoke. Transcribe + Sam responds."""
    from .services.voice import generate_response_twiml, generate_error_twiml, identify_caller, process_speech

    form = await request.form()
    speech_text = form.get("SpeechResult", "")
    caller = form.get("From", "")
    confidence = form.get("Confidence", "0")

    logger.info(f"[Voice] Speech from {caller}: '{speech_text}' (confidence: {confidence})")

    if not speech_text:
        return Response(
            content=generate_response_twiml("Samajh nahi aaya. Phir se boliye?"),
            media_type="application/xml",
        )

    try:
        # Identify caller
        caller_info = await identify_caller(caller)
        user_id = caller_info.get("user_id")
        language = caller_info.get("language", "hi")

        if not user_id:
            # Unknown caller — still respond with general Sam
            from .services.llm import call_gemini
            reply = await call_gemini(
                "You are Sam, a helpful WhatsApp assistant. Someone called you. Answer their question concisely. Speak in Hindi or English based on what they said.",
                speech_text,
            )
        else:
            # Known user — full Sam with Soul context
            reply = await process_speech(user_id, speech_text)

        # Pick language for TTS
        lang_code = "hi-IN"
        if language in ("english",):
            lang_code = "en-IN"

        twiml = generate_response_twiml(reply, lang_code)
        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        logger.error(f"[Voice] Process error: {e}", exc_info=True)
        return Response(content=generate_error_twiml(), media_type="application/xml")


@app.post("/voice/call")
async def voice_outbound(
    phone: str = Form(...),
    message: str = Form(...),
):
    """Make an outbound call from Sam. Admin only."""
    from .services.voice import make_outbound_call
    result = await make_outbound_call(phone, message)
    return result


# --- Cron Endpoints (called by bridge scheduler) ---

@app.post("/cron/check-subscriptions")
async def handle_check_subscriptions(db: AsyncSession = Depends(get_db)):
    """Daily 10am IST — pause expired users + warn 3-day-before users."""
    now = datetime.now()
    three_days = now + timedelta(days=3)
    notifications = []

    # 1. Expired users — pause them
    expired_result = await db.execute(
        select(User).where(
            User.paid_until < now,
            User.status == "active",
            User.plan != "admin",
        )
    )
    expired_users = expired_result.scalars().all()

    for user in expired_users:
        user.status = "paused"
        expired_date = user.paid_until.strftime("%d %b %Y") if user.paid_until else "?"
        notifications.append({
            "user_id": user.id,
            "message": (
                f"Your Samva subscription expired on {expired_date}. "
                f"Sam is paused.\n\n"
                f"Renew at samva.in/renew?id={user.id} to continue.\n"
                f"\u20b9299/month."
            ),
        })
        logger.info(f"[Subscription] Paused expired user: {user.id}")

    # 2. Users expiring in 3 days — send warning
    warning_result = await db.execute(
        select(User).where(
            User.paid_until >= now,
            User.paid_until <= three_days,
            User.status == "active",
            User.plan != "admin",
        )
    )
    warning_users = warning_result.scalars().all()

    for user in warning_users:
        expiry_date = user.paid_until.strftime("%d %b %Y") if user.paid_until else "?"
        notifications.append({
            "user_id": user.id,
            "message": (
                f"\u23f0 *Sam reminder* -- your subscription renews in 3 days "
                f"on {expiry_date}.\n\n"
                f"\u20b9299 will be charged if auto-pay is set up, "
                f"or renew manually at samva.in/renew?id={user.id}"
            ),
        })

    await db.commit()

    return {
        "expired": len(expired_users),
        "warned": len(warning_users),
        "notifications": notifications,
    }


@app.post("/cron/soul-evolution")
async def handle_soul_evolution(db: AsyncSession = Depends(get_db)):
    """Sunday 11pm IST — evolve all active users' Souls."""
    from .services.soul_evolution import run_soul_evolution_for_all
    evolved = await run_soul_evolution_for_all(db)
    return {"evolved": len(evolved), "users": evolved}


@app.post("/cron/network-match")
async def handle_network_match(db: AsyncSession = Depends(get_db)):
    """Sunday 11pm IST (after soul evolution) — match network profiles."""
    from .services.network import run_network_matching
    matches = await run_network_matching(db)
    return {"matches": len(matches), "notifications": matches}


@app.post("/cron/evolution-notify")
async def handle_evolution_notify(
    db: AsyncSession = Depends(get_db)
):
    """Monday 9am IST — send evolution messages to users."""
    from .services.soul_evolution import get_evolution_message
    from .models import User
    result = await db.execute(select(User).where(User.status == "active"))
    users = result.scalars().all()

    messages = []
    for user in users:
        msg = await get_evolution_message(db, user.id)
        if msg:
            messages.append({"user_id": user.id, "message": msg})

    return {"count": len(messages), "messages": messages}


@app.post("/cron/urgent-escalations")
async def handle_urgent_escalations(db: AsyncSession = Depends(get_db)):
    """Every 15 min — check urgent reminders, call users who haven't responded."""
    from .services.reminders import check_urgent_escalations
    from .services.voice import make_outbound_call

    calls = await check_urgent_escalations(db)
    results = []
    for call in calls:
        result = await make_outbound_call(call["phone"], call["message"])
        results.append({
            "user_id": call["user_id"],
            "phone": call["phone"],
            "success": result.get("success", False),
        })
        logger.info(f"[Urgent] Called {call['phone']}: {result}")

    return {"calls_made": len(results), "results": results}


@app.post("/cron/morning-brief-voice")
async def handle_morning_brief_voice(db: AsyncSession = Depends(get_db)):
    """
    Morning brief as voice note — send gold brief as audio to jeweller users.
    Called by bridge cron at user's chosen brief time.
    Returns list of {user_id, text, audio_base64} for bridge to send as voice notes.
    """
    from .services.gold import should_get_gold_brief, get_gold_brief, mark_brief_sent
    from .services.llm import text_to_speech

    result_list = await db.execute(select(User).where(User.status == "active"))
    users = result_list.scalars().all()

    briefs = []
    for user in users:
        try:
            # Gold brief for jewellers
            brief_text = ""
            if await should_get_gold_brief(db, user.id):
                brief_text = await get_gold_brief(db, user.id)
                if brief_text:
                    await mark_brief_sent(db, user.id)

            # Inbox summary for ALL users
            from .services.inbox import get_morning_inbox_summary
            inbox_summary = await get_morning_inbox_summary(db, user.id)

            # Email summary
            from .services.email_service import get_morning_email_summary
            email_summary = await get_morning_email_summary(db, user.id)

            # Combine
            full_brief = (brief_text or "") + (inbox_summary or "") + (email_summary or "")
            if full_brief.strip():
                audio_b64 = await text_to_speech(full_brief, user.id)
                briefs.append({
                    "user_id": user.id,
                    "text": full_brief,
                    "audio": {"data": audio_b64, "mimetype": "audio/mp4"} if audio_b64 else None,
                })
        except Exception as e:
            logger.error(f"Morning brief voice error for {user.id}: {e}")

    return {"count": len(briefs), "briefs": briefs}


# --- Admin Auth + Dashboard ---

@app.post("/admin/login")
async def admin_login(req: dict):
    if req.get("email") == settings.admin_email and req.get("password") == settings.admin_password:
        return {"success": True}
    raise HTTPException(status_code=401, detail="Wrong credentials")


@app.get("/admin")
async def admin_page():
    from fastapi.responses import FileResponse
    import os
    admin_path = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "admin.html")
    if not os.path.exists(admin_path):
        admin_path = "/app/web/public/admin.html"
    return FileResponse(admin_path)


@app.get("/admin/dashboard")
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Dashboard stats."""
    from sqlalchemy import func, text as sql_text
    from .models import Conversation

    total = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active = (await db.execute(select(func.count(User.id)).where(User.status == "active"))).scalar() or 0

    # Messages today
    try:
        msgs_today = (await db.execute(
            select(func.count(Conversation.id)).where(sql_text("created_at >= CURRENT_DATE"))
        )).scalar() or 0
    except Exception:
        msgs_today = 0

    return {
        "total_users": total,
        "active_users": active,
        "messages_today": msgs_today,
        "api_cost_today": 0,
        "api_cost_month": 0,
    }


@app.get("/admin/users-list")
async def admin_users_list(request: Request, db: AsyncSession = Depends(get_db)):
    """List all users."""
    from .models import AgentSoul
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()

    user_list = []
    for u in users:
        soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == u.id))
        soul = soul_result.scalar_one_or_none()
        user_list.append({
            "name": u.name or "",
            "phone": u.phone or "",
            "status": u.status or "",
            "plan": u.plan or "",
            "business_type": soul.business_type if soul else "",
            "paid_until": u.paid_until.strftime("%d %b %Y") if u.paid_until else "",
        })

    return {"users": user_list, "count": len(user_list)}


# --- Admin Skills Endpoints ---

@app.get("/admin/skills")
async def admin_skills(userId: str, db: AsyncSession = Depends(get_db)):
    """Show all custom skills built for a user. For debugging."""
    from .models import UserSkill
    result = await db.execute(
        select(UserSkill).where(UserSkill.user_id == userId).order_by(UserSkill.created_at.desc())
    )
    skills = result.scalars().all()

    return {
        "userId": userId,
        "count": len(skills),
        "skills_summary": f"{sum(1 for s in skills if s.is_active)} active, {sum(1 for s in skills if not s.is_active)} inactive",
        "skills": [
            {
                "skill_name": s.skill_name,
                "description": s.description,
                "api_url": s.api_url,
                "trigger_keywords": s.trigger_keywords,
                "test_passed": s.test_passed,
                "test_result": s.test_result,
                "is_active": s.is_active,
                "build_log": s.build_log,
                "code_preview": (s.python_code or "")[:300],
                "created_at": str(s.created_at),
            }
            for s in skills
        ],
    }


@app.delete("/admin/skills/{skill_name}")
async def admin_delete_skill(skill_name: str, userId: str, db: AsyncSession = Depends(get_db)):
    """Delete a user's custom skill. For debugging/fixing broken skills."""
    from .models import UserSkill
    from sqlalchemy import delete
    result = await db.execute(
        delete(UserSkill).where(
            UserSkill.user_id == userId, UserSkill.skill_name == skill_name
        )
    )
    await db.commit()
    return {"deleted": skill_name, "rows": result.rowcount}


@app.get("/admin/skills/all")
async def admin_all_skills(db: AsyncSession = Depends(get_db)):
    """Overview of ALL custom skills across ALL users. Admin dashboard."""
    from .models import UserSkill
    from sqlalchemy import func

    # All skills
    result = await db.execute(
        select(UserSkill).order_by(UserSkill.created_at.desc())
    )
    skills = result.scalars().all()

    # Stats
    total = len(skills)
    active = sum(1 for s in skills if s.is_active)
    failed = sum(1 for s in skills if not s.is_active)
    unique_users = len(set(s.user_id for s in skills))

    # Group by user
    by_user = {}
    for s in skills:
        if s.user_id not in by_user:
            by_user[s.user_id] = []
        by_user[s.user_id].append({
            "skill_name": s.skill_name,
            "description": s.description,
            "api_url": s.api_url,
            "is_active": s.is_active,
            "test_passed": s.test_passed,
            "test_result": (s.test_result or "")[:100],
            "created_at": str(s.created_at),
        })

    return {
        "stats": {
            "total_skills": total,
            "active": active,
            "failed": failed,
            "unique_users": unique_users,
            "pass_rate": f"{(active/total*100):.0f}%" if total > 0 else "N/A",
        },
        "prebuilt_available": list(PREBUILT_SKILLS_NAMES),
        "by_user": by_user,
    }


# Import prebuilt skill names for admin view
try:
    from .services.skill_builder import PREBUILT_SKILLS
    PREBUILT_SKILLS_NAMES = list(PREBUILT_SKILLS.keys())
except Exception:
    PREBUILT_SKILLS_NAMES = []
