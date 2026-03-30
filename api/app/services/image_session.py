"""
Image Session — Sam NEVER forgets an image. EVER.

When a user sends an image, Sam stores it permanently in the DB.
Every subsequent render, edit, enhance creates a NEW version
linked to the original. The user can switch topics, come back
hours later, and Sam still knows exactly which image, which
version, what changes were made.

This is the memory that makes Sam smarter than any agent.

Chain: original → render1 → render2 (changed stone) → render3 (engraving)
Each step stored. User can say "show me the original" or
"go back to the sapphire version" and Sam knows.
"""

import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from ..database import Base
from ..models import Conversation

logger = logging.getLogger("samva.image_session")


# ── Image Session Table ──────────────────────────────────────────

class ImageSession(Base):
    """Persistent image storage — every image, every version, forever."""
    __tablename__ = "image_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    session_tag = Column(String(50), nullable=False)    # "active", "photo_1", "render_2"
    image_base64 = Column(Text, nullable=False)          # Full base64 data
    description = Column(Text, nullable=True)             # What this image is / what was done
    source = Column(String(50), default="upload")         # upload, render, enhance, ad, vto, gemlens
    parent_id = Column(Integer, nullable=True)             # Previous version in chain
    is_active = Column(Boolean, default=True)              # Current active image
    created_at = Column(DateTime, default=func.now())


# ── Core Functions ───────────────────────────────────────────────

async def store_image(
    db: AsyncSession, user_id: str, image_base64: str,
    description: str = "", source: str = "upload",
) -> int:
    """Store an image. Mark as active. Returns the image session ID."""
    # Deactivate previous active images
    result = await db.execute(
        select(ImageSession).where(
            ImageSession.user_id == user_id, ImageSession.is_active == True
        )
    )
    for old in result.scalars().all():
        old.is_active = False

    img = ImageSession(
        user_id=user_id,
        session_tag="active",
        image_base64=image_base64,
        description=description,
        source=source,
        is_active=True,
    )
    db.add(img)
    await db.flush()
    await db.commit()
    logger.info(f"[{user_id}] Image stored: id={img.id}, source={source}")
    return img.id


async def store_version(
    db: AsyncSession, user_id: str, image_base64: str,
    description: str, source: str, parent_id: int = None,
) -> int:
    """Store a new version (render, enhance, etc.) linked to parent."""
    # Deactivate previous active
    result = await db.execute(
        select(ImageSession).where(
            ImageSession.user_id == user_id, ImageSession.is_active == True
        )
    )
    for old in result.scalars().all():
        old.is_active = False

    img = ImageSession(
        user_id=user_id,
        session_tag="active",
        image_base64=image_base64,
        description=description,
        source=source,
        parent_id=parent_id,
        is_active=True,
    )
    db.add(img)
    await db.flush()
    await db.commit()
    logger.info(f"[{user_id}] Version stored: id={img.id}, source={source}, parent={parent_id}")
    return img.id


async def get_active_image(db: AsyncSession, user_id: str) -> dict:
    """Get the current active image for this user. Returns {id, base64, description, source} or empty."""
    result = await db.execute(
        select(ImageSession).where(
            ImageSession.user_id == user_id, ImageSession.is_active == True
        ).order_by(ImageSession.created_at.desc()).limit(1)
    )
    img = result.scalar_one_or_none()
    if not img:
        return {}

    return {
        "id": img.id,
        "base64": img.image_base64,
        "description": img.description,
        "source": img.source,
        "parent_id": img.parent_id,
    }


async def get_image_history(db: AsyncSession, user_id: str, limit: int = 10) -> list:
    """Get all images for this user, newest first."""
    result = await db.execute(
        select(ImageSession).where(ImageSession.user_id == user_id)
        .order_by(ImageSession.created_at.desc()).limit(limit)
    )
    return [
        {"id": img.id, "description": img.description, "source": img.source, "created_at": str(img.created_at)}
        for img in result.scalars().all()
    ]


async def get_image_by_id(db: AsyncSession, user_id: str, image_id: int) -> dict:
    """Get a specific image by ID."""
    result = await db.execute(
        select(ImageSession).where(
            ImageSession.user_id == user_id, ImageSession.id == image_id
        )
    )
    img = result.scalar_one_or_none()
    if not img:
        return {}
    return {"id": img.id, "base64": img.image_base64, "description": img.description, "source": img.source}


async def has_active_image(db: AsyncSession, user_id: str) -> bool:
    """Check if user has an active image in context."""
    result = await db.execute(
        select(ImageSession).where(
            ImageSession.user_id == user_id, ImageSession.is_active == True
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


# ── Image-aware message detection ────────────────────────────────

# Only SPECIFIC image-editing words — NOT generic words like "gold", "price"
IMAGE_CONTEXT_WORDS = {
    "render", "render karo", "enhance", "enhance karo", "catalog shot",
    "try on", "tryon", "try on dikhao",
    "change the stone", "change stone", "change metal", "swap stone",
    "add engraving", "engrave", "engraving",
    "bom sheet", "bill of material",
    "show original", "original dikhao", "pehle wala", "pehle wala dikhao",
    "previous version", "go back",
    "white gold mein", "rose gold mein", "yellow gold mein",
    "render in", "change to",
    "ad banao", "make ad", "instagram ad",
    "360 view", "four angles", "all angles",
    "badlo", "modify design",
}


def is_image_context_message(text: str) -> bool:
    """Check if this message is specifically about editing/processing an image in context.
    Uses multi-word phrases to avoid false matches on common words."""
    if not text:
        return False
    lower = text.lower()
    return any(w in lower for w in IMAGE_CONTEXT_WORDS)
