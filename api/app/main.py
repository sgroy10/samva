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


@app.post("/signup")
async def handle_signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    """Collect phone, create user, and optionally create Razorpay order."""
    # Check if user already exists
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

        # Create soul placeholder
        soul = AgentSoul(user_id=user_id)
        db.add(soul)

        # Create session health entry
        sh = SessionHealth(user_id=user_id)
        db.add(sh)

        await db.commit()

    # Create Razorpay order if configured
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        try:
            import httpx
            auth = (settings.razorpay_key_id, settings.razorpay_key_secret)
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.razorpay.com/v1/orders",
                    auth=auth,
                    json={
                        "amount": 99900,  # 999 INR in paise
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
            # Skip payment on error
            return {"userId": user_id, "skipPayment": True}
    else:
        # No Razorpay configured — skip payment
        return {"userId": user_id, "skipPayment": True}


@app.post("/payment/verify")
async def handle_payment_verify(
    req: PaymentVerifyRequest, db: AsyncSession = Depends(get_db)
):
    """Verify Razorpay payment signature and activate user."""
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
    if user:
        user.razorpay_id = req.razorpay_payment_id
        user.paid_until = datetime.now() + timedelta(days=30)
        user.plan = "standard"
        await db.commit()

    return {"verified": True}


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
