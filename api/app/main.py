import logging
import uuid
import hashlib
import hmac
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
                        "amount": 99900,
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
                "amount": 999,
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
        f"Subscription: \u20b9999/month\n"
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
                        "amount": 99900,
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
                "amount": 999,
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
                f"\u20b9999/month."
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
                f"\u20b9999 will be charged if auto-pay is set up, "
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
