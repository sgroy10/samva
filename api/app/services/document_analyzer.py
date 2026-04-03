"""
Document Analyzer — Sam reads any document you send.
PDFs (blood reports, invoices, contracts), images of documents, etc.
Uses Gemini's native multimodal understanding.
"""

import logging
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import settings
from ..models import AgentSoul, UserMemory
from .llm import call_gemini

logger = logging.getLogger("samva.document")


async def analyze_document(
    db: AsyncSession, user_id: str, soul: AgentSoul,
    text: str, document_base64: str,
) -> str:
    """
    Analyze any document using Gemini's native PDF/document understanding.
    Gemini 2.5 Flash can read PDFs directly as inline_data.
    """
    if not settings.gemini_api_key:
        return "Document analysis is temporarily unavailable. Try again later."

    # Detect document type from content or user's message
    user_query = text or "Analyze this document in detail"
    query_lower = user_query.lower()

    # Build context-aware analysis prompt based on document type
    if any(w in query_lower for w in ["blood", "test", "report", "lab", "pathology", "medical", "health", "xray", "scan", "prescription"]):
        analysis_type = "medical"
        system = _medical_prompt(soul)
    elif any(w in query_lower for w in ["invoice", "bill", "receipt", "gst", "tax", "quotation", "estimate"]):
        analysis_type = "financial"
        system = _financial_prompt(soul)
    elif any(w in query_lower for w in ["contract", "agreement", "legal", "terms", "policy"]):
        analysis_type = "legal"
        system = _legal_prompt(soul)
    else:
        analysis_type = "general"
        system = _general_prompt(soul)

    logger.info(f"[{user_id}] Analyzing document (type: {analysis_type})")

    try:
        # Use Gemini API directly — it can read PDFs natively
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": [{
                        "parts": [
                            {"text": f"{system}\n\nUser's question: {user_query}"},
                            {
                                "inline_data": {
                                    "mime_type": "application/pdf",
                                    "data": document_base64,
                                }
                            },
                        ]
                    }],
                    "generationConfig": {
                        "maxOutputTokens": 1500,
                        "temperature": 0.4,
                    },
                },
            )
            data = resp.json()

            if "error" in data:
                logger.error(f"Gemini document error: {data['error']}")
                # Fallback: try as image (maybe it's a photo of a document)
                return await _fallback_image_analysis(user_id, soul, user_query, document_base64)

            reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()

            # Log cost
            try:
                from ..database import async_session
                from .cost_tracker import log_cost
                usage = data.get("usageMetadata", {})
                tokens_in = usage.get("promptTokenCount", 0)
                tokens_out = usage.get("candidatesTokenCount", 0)
                async with async_session() as cost_db:
                    await log_cost(cost_db, "gemini_document", "gemini-2.5-flash", tokens_in, tokens_out, f"document_{analysis_type}", user_id)
            except Exception:
                pass

            logger.info(f"[{user_id}] Document analyzed ({analysis_type}): {reply[:100]}...")
            return reply

    except Exception as e:
        logger.error(f"Document analysis error for {user_id}: {e}", exc_info=True)
        # Fallback to image analysis
        return await _fallback_image_analysis(user_id, soul, user_query, document_base64)


async def _fallback_image_analysis(user_id, soul, query, base64_data):
    """Fallback: treat document as image and analyze via OpenRouter."""
    try:
        name = soul.system_prompt[:200] if soul else ""
        return await call_gemini(
            f"You are Sam, a personal assistant. Analyze this document/image thoroughly.\nUser context: {name}",
            query or "Analyze this document in detail.",
            image_base64=base64_data,
            user_id=user_id,
            max_tokens=1200,
        )
    except Exception as e:
        logger.error(f"Fallback analysis failed: {e}")
        return "I couldn't read this document. Can you try sending it as a photo/screenshot instead?"


def _medical_prompt(soul):
    name = soul.system_prompt[:300] if soul and soul.system_prompt else ""
    return f"""You are Sam, a personal health assistant analyzing a medical document.

User context: {name}

ANALYZE THIS MEDICAL REPORT THOROUGHLY:
1. **What test is this?** (blood test, urine, X-ray, ECG, etc.)
2. **Key findings** — list every parameter with its value and normal range
3. **What's ABNORMAL?** — highlight anything outside normal range with ⚠️
4. **What does it mean?** — explain in simple language what the abnormal values indicate
5. **Action items** — what should the person do next? (see doctor, dietary changes, lifestyle, retest)
6. **Positive notes** — what's looking good? Reassure where appropriate.

RULES:
- Be thorough but use simple language — this is WhatsApp, not a medical journal
- Always add disclaimer: "This is AI analysis — please consult your doctor for medical advice"
- Use emojis sparingly for readability
- If you see critical values (very high/low), flag them prominently
- Match the user's language preference"""


def _financial_prompt(soul):
    name = soul.system_prompt[:300] if soul and soul.system_prompt else ""
    return f"""You are Sam, a business assistant analyzing a financial document.

User context: {name}

ANALYZE THIS DOCUMENT:
1. **Document type** — invoice, bill, receipt, quotation, tax form?
2. **Key amounts** — total, taxes, discounts, due date
3. **Important details** — vendor/buyer, items, quantities, rates
4. **GST/Tax breakdown** if applicable
5. **Action needed** — payment due? Discrepancy? Anything to flag?

Keep it concise for WhatsApp. Highlight the most important numbers."""


def _legal_prompt(soul):
    name = soul.system_prompt[:300] if soul and soul.system_prompt else ""
    return f"""You are Sam, an assistant analyzing a legal/contract document.

User context: {name}

ANALYZE THIS DOCUMENT:
1. **What type of document?** — contract, agreement, notice, policy?
2. **Key terms** — obligations, deadlines, penalties, payment terms
3. **Red flags** ⚠️ — unfavorable clauses, hidden fees, unusual terms
4. **Summary** — what this document means in plain language
5. **Action** — should user sign? What to negotiate? What to clarify?

Add disclaimer: "This is AI analysis — consult a lawyer for legal advice."
Keep it WhatsApp-friendly."""


def _general_prompt(soul):
    name = soul.system_prompt[:300] if soul and soul.system_prompt else ""
    return f"""You are Sam, a personal assistant analyzing a document.

User context: {name}

Read this document carefully and provide:
1. **What is this?** — type and purpose of the document
2. **Key information** — most important facts, numbers, dates
3. **Summary** — brief plain-language summary
4. **Action items** — what should the user do with this?

Keep it concise for WhatsApp. Use bullet points."""
