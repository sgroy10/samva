"""
Document Generator — Sam creates real documents.

"Make a PDF of today's gold rates" → actual PDF
"Client ke liye quotation banao" → actual PDF
"Weekly report PDF bhejo" → actual PDF
"Invoice bana do" → actual PDF

Uses fpdf2 (already installed for BOM PDFs).
Returns base64-encoded PDF for WhatsApp delivery.
"""

import logging
import base64
import io
from datetime import datetime
import pytz
from fpdf import FPDF
from sqlalchemy.ext.asyncio import AsyncSession
from .llm import call_gemini_json

logger = logging.getLogger("samva.doc_generator")
IST = pytz.timezone("Asia/Kolkata")

# Document type triggers
DOC_TRIGGERS = {
    "gold_report": ["gold report", "gold pdf", "gold rates pdf", "sona ka report"],
    "invoice": ["invoice bana", "bill bana", "invoice create", "invoice generate"],
    "quotation": ["quotation bana", "quote bana", "quotation for", "estimate bana"],
    "report": ["report bana", "weekly report", "monthly report", "summary pdf"],
    "letter": ["letter bana", "letter likh", "formal letter", "notice bana"],
}


def detect_doc_request(text: str) -> str:
    """Detect if user wants a document generated."""
    text_lower = text.lower()
    for doc_type, triggers in DOC_TRIGGERS.items():
        if any(t in text_lower for t in triggers):
            return doc_type
    return ""


async def generate_document(
    db: AsyncSession, user_id: str, doc_type: str, text: str, user_name: str = ""
) -> tuple:
    """Generate a PDF document. Returns (base64_pdf, description)."""
    logger.info(f"[{user_id}] Generating document: {doc_type}")

    now = datetime.now(IST)

    if doc_type == "gold_report":
        return await _generate_gold_report(db, user_id, user_name, now)
    elif doc_type == "invoice":
        return await _generate_invoice(db, user_id, text, user_name, now)
    elif doc_type == "quotation":
        return await _generate_quotation(db, user_id, text, user_name, now)
    elif doc_type == "report":
        return await _generate_summary_report(db, user_id, user_name, now)
    elif doc_type == "letter":
        return await _generate_letter(db, user_id, text, user_name, now)
    return ("", "")


async def _generate_gold_report(db, user_id, user_name, now) -> tuple:
    """Generate a gold rates PDF report."""
    from .gold import _fetch_prices

    prices = await _fetch_prices()
    if not prices:
        return ("", "")

    pdf = FPDF()
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 15, "SAMVA - Gold Rate Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"Generated: {now.strftime('%d %B %Y, %I:%M %p IST')}", new_x="LMARGIN", new_y="NEXT", align="C")
    if user_name:
        pdf.cell(0, 6, f"For: {user_name}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)

    # Rates table
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(255, 107, 53)  # Samva orange
    pdf.set_text_color(255, 255, 255)
    pdf.cell(60, 10, "Metal", fill=True, align="C")
    pdf.cell(60, 10, "Rate (INR/gm)", fill=True, align="C")
    pdf.cell(60, 10, "Rate (INR/10gm)", fill=True, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 11)

    rates = [
        ("Gold 24K", prices.get("gold_24k", 0)),
        ("Gold 22K", prices.get("gold_22k", 0)),
        ("Gold 18K", prices.get("gold_18k", 0)),
        ("Gold 14K", prices.get("gold_14k", 0)),
        ("Silver", prices.get("silver", 0)),
        ("Platinum", prices.get("platinum", 0)),
    ]

    for i, (name, rate) in enumerate(rates):
        if rate:
            fill = i % 2 == 0
            if fill:
                pdf.set_fill_color(245, 245, 245)
            pdf.cell(60, 10, name, fill=fill, align="C")
            pdf.cell(60, 10, f"Rs {rate:,.2f}", fill=fill, align="C")
            pdf.cell(60, 10, f"Rs {rate * 10:,.2f}", fill=fill, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 6, "Powered by Samva AI - samva.in", align="C")

    # Convert to base64
    buf = io.BytesIO()
    pdf.output(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    return (b64, f"Gold Rate Report - {now.strftime('%d %b %Y')}")


async def _generate_invoice(db, user_id, text, user_name, now) -> tuple:
    """Generate an invoice PDF using LLM to extract details."""
    data = await call_gemini_json(
        """Extract invoice details from this text. Return JSON:
{
    "client_name": "client name",
    "items": [{"description": "item", "qty": 1, "rate": 0, "amount": 0}],
    "total": 0,
    "notes": "any special notes"
}""",
        text, user_id=user_id,
    )

    if not data or "error" in data:
        return ("", "")

    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "INVOICE", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Date: {now.strftime('%d %B %Y')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"From: {user_name or 'Samva User'}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"To: {data.get('client_name', 'Client')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # Items table
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(255, 107, 53)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(80, 8, "Description", fill=True)
    pdf.cell(25, 8, "Qty", fill=True, align="C")
    pdf.cell(35, 8, "Rate", fill=True, align="C")
    pdf.cell(40, 8, "Amount", fill=True, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    for item in data.get("items", []):
        pdf.cell(80, 8, str(item.get("description", "")))
        pdf.cell(25, 8, str(item.get("qty", 1)), align="C")
        pdf.cell(35, 8, f"Rs {item.get('rate', 0):,.0f}", align="C")
        pdf.cell(40, 8, f"Rs {item.get('amount', 0):,.0f}", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(140, 10, "TOTAL:", align="R")
    pdf.cell(40, 10, f"Rs {data.get('total', 0):,.0f}", new_x="LMARGIN", new_y="NEXT", align="C")

    if data.get("notes"):
        pdf.ln(6)
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, f"Notes: {data['notes']}")

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 6, "Generated by Samva AI - samva.in", align="C")

    buf = io.BytesIO()
    pdf.output(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    return (b64, f"Invoice - {data.get('client_name', 'Client')} - {now.strftime('%d %b')}")


async def _generate_quotation(db, user_id, text, user_name, now) -> tuple:
    """Generate a quotation PDF."""
    data = await call_gemini_json(
        """Extract quotation details. Return JSON:
{
    "client_name": "name",
    "items": [{"description": "item", "qty": 1, "rate": 0, "amount": 0}],
    "total": 0,
    "validity": "7 days",
    "terms": "any terms"
}""",
        text, user_id=user_id,
    )

    if not data or "error" in data:
        return ("", "")

    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "QUOTATION", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Date: {now.strftime('%d %B %Y')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"From: {user_name or 'Samva User'}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"To: {data.get('client_name', 'Client')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Valid for: {data.get('validity', '7 days')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(255, 107, 53)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(80, 8, "Description", fill=True)
    pdf.cell(25, 8, "Qty", fill=True, align="C")
    pdf.cell(35, 8, "Rate", fill=True, align="C")
    pdf.cell(40, 8, "Amount", fill=True, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    for item in data.get("items", []):
        pdf.cell(80, 8, str(item.get("description", "")))
        pdf.cell(25, 8, str(item.get("qty", 1)), align="C")
        pdf.cell(35, 8, f"Rs {item.get('rate', 0):,.0f}", align="C")
        pdf.cell(40, 8, f"Rs {item.get('amount', 0):,.0f}", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(140, 10, "TOTAL:", align="R")
    pdf.cell(40, 10, f"Rs {data.get('total', 0):,.0f}", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 6, "Generated by Samva AI - samva.in", align="C")

    buf = io.BytesIO()
    pdf.output(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    return (b64, f"Quotation - {data.get('client_name', 'Client')}")


async def _generate_summary_report(db, user_id, user_name, now) -> tuple:
    """Generate a weekly/monthly summary report."""
    from ..models import Conversation, UserMemory
    from datetime import timedelta

    cutoff = now - timedelta(days=7)
    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.created_at >= cutoff)
    )
    conversations = conv_result.scalars().all()

    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "SAMVA - Weekly Activity Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Period: {cutoff.strftime('%d %b')} - {now.strftime('%d %b %Y')}", new_x="LMARGIN", new_y="NEXT", align="C")
    if user_name:
        pdf.cell(0, 6, f"User: {user_name}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(8)

    # Stats
    user_msgs = len([c for c in conversations if c.role == "user"])
    sam_msgs = len([c for c in conversations if c.role == "assistant"])

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Activity Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Total messages: {len(conversations)}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Your messages: {user_msgs}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Sam's responses: {sam_msgs}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Average per day: {len(conversations) // 7}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 6, "Generated by Samva AI - samva.in", align="C")

    buf = io.BytesIO()
    pdf.output(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    return (b64, f"Weekly Report - {now.strftime('%d %b %Y')}")


async def _generate_letter(db, user_id, text, user_name, now) -> tuple:
    """Generate a formal letter using LLM."""
    from .llm import call_gemini

    letter_text = await call_gemini(
        "Write a formal letter based on the user's request. Keep it professional and concise. Include date, proper salutation, body, and closing.",
        text, user_id=user_id, max_tokens=600,
    )

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)

    # Simple text wrapping
    for line in letter_text.split("\n"):
        if line.strip():
            pdf.multi_cell(0, 6, line.strip())
        else:
            pdf.ln(4)

    buf = io.BytesIO()
    pdf.output(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    return (b64, f"Letter - {now.strftime('%d %b %Y')}")
