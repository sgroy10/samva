import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from ..models import Contact
from .llm import call_gemini_json, call_gemini

logger = logging.getLogger("samva.contacts")


async def process_business_card(
    db: AsyncSession, user_id: str, image_base64: str
) -> str:
    """OCR a business card image and save the contact."""
    extracted = await call_gemini_json(
        """Extract all information from this business card image.
Return JSON:
{
    "full_name": "",
    "company": "",
    "designation": "",
    "phone": "",
    "email": "",
    "address": "",
    "website": "",
    "other_phones": [],
    "other_emails": []
}
Extract everything visible. If a field is not present, use empty string.""",
        "Extract business card details from this image.",
        image_base64=image_base64,
        user_id=user_id,
    )

    if "error" in extracted:
        return "I couldn't read that card clearly. Could you take another photo with better lighting?"

    name = extracted.get("full_name", "Unknown")
    company = extracted.get("company", "")
    phone = extracted.get("phone", "")
    email = extracted.get("email", "")

    # Check if contact already exists
    if name and name != "Unknown":
        existing = await db.execute(
            select(Contact).where(
                Contact.user_id == user_id,
                Contact.full_name == name,
            )
        )
        if existing.scalar_one_or_none():
            return f"{name} is already in your contacts. Want me to update their info?"

    # Save contact
    contact = Contact(
        user_id=user_id,
        full_name=name,
        company=company,
        designation=extracted.get("designation", ""),
        phone=phone,
        email=email,
        address=extracted.get("address", ""),
        website=extracted.get("website", ""),
        source="card",
    )
    db.add(contact)
    await db.commit()

    # Format response
    lines = [f"Saved \u2713 *{name}*"]
    if company:
        lines.append(f"\ud83c\udfe2 {company}")
    if extracted.get("designation"):
        lines.append(f"\ud83d\udcbc {extracted['designation']}")
    if phone:
        lines.append(f"\ud83d\udcde {phone}")
    if email:
        lines.append(f"\u2709\ufe0f {email}")

    lines.append("\nTag? (client / supplier / partner / personal)")

    return "\n".join(lines)


async def lookup_contact(db: AsyncSession, user_id: str, query: str) -> str:
    """Look up a contact by name, company, or other fields."""
    # Extract search term
    search_term = query.strip()

    # Simple search across multiple fields
    result = await db.execute(
        select(Contact).where(
            Contact.user_id == user_id,
            or_(
                Contact.full_name.ilike(f"%{search_term}%"),
                Contact.company.ilike(f"%{search_term}%"),
                Contact.designation.ilike(f"%{search_term}%"),
                Contact.phone.ilike(f"%{search_term}%"),
                Contact.email.ilike(f"%{search_term}%"),
                Contact.tag.ilike(f"%{search_term}%"),
            ),
        )
    )
    contacts = result.scalars().all()

    if not contacts:
        # Try with Gemini to extract the actual search intent
        extracted = await call_gemini_json(
            'Extract the person/company name being searched for. Return: {"search": "the name or term"}',
            query,
            user_id=user_id,
        )
        term = extracted.get("search", search_term)

        result = await db.execute(
            select(Contact).where(
                Contact.user_id == user_id,
                or_(
                    Contact.full_name.ilike(f"%{term}%"),
                    Contact.company.ilike(f"%{term}%"),
                ),
            )
        )
        contacts = result.scalars().all()

    if not contacts:
        return f"No contacts found for \"{search_term}\". Try a different name?"

    if len(contacts) == 1:
        c = contacts[0]
        lines = [f"*{c.full_name}*"]
        if c.company:
            lines.append(f"\ud83c\udfe2 {c.company}")
        if c.designation:
            lines.append(f"\ud83d\udcbc {c.designation}")
        if c.phone:
            lines.append(f"\ud83d\udcde {c.phone}")
        if c.email:
            lines.append(f"\u2709\ufe0f {c.email}")
        if c.address:
            lines.append(f"\ud83d\udccd {c.address}")
        if c.tag:
            lines.append(f"\ud83c\udff7\ufe0f {c.tag}")
        if c.notes:
            lines.append(f"\ud83d\udcdd {c.notes}")
        return "\n".join(lines)

    # Multiple results
    lines = [f"Found {len(contacts)} contacts:"]
    for c in contacts[:10]:
        detail = f"*{c.full_name}*"
        if c.company:
            detail += f" \u2014 {c.company}"
        if c.phone:
            detail += f" | {c.phone}"
        lines.append(detail)

    return "\n".join(lines)
