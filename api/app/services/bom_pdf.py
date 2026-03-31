"""
BOM PDF Generator — creates professional Bill of Materials PDF.
Based on JewelClaw's bom_pdf_service.py but simplified for Samva.
Uses fpdf2 to generate PDF, returns as base64 for WhatsApp.
"""

import io
import base64
import logging
from datetime import datetime
from fpdf import FPDF

logger = logging.getLogger("samva.bom_pdf")


def _safe(text) -> str:
    """Strip non-latin-1 characters for PDF rendering."""
    if not text:
        return ""
    text = str(text)
    text = text.replace("\u20b9", "Rs").replace("\u2192", "->").replace("\u2022", "*")
    return text.encode("latin-1", errors="replace").decode("latin-1")


class SamvaBomPDF(FPDF):
    def __init__(self, title="Bill of Materials"):
        super().__init__()
        self.title_text = title
        self.report_date = datetime.now().strftime("%d %b %Y")

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 8, "Samva", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 4, _safe(self.title_text), new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 4, f"Generated: {self.report_date}", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Samva BOM Report | Page {self.page_no()}", align="C")


def generate_bom_pdf(
    item_name: str = "Jewelry Item",
    metal_info: dict = None,
    stones: list = None,
    gold_rate_per_gram: float = 0,
    making_charge_pct: float = 12,
    weight_grams: float = 0,
) -> str:
    """
    Generate a BOM PDF and return as base64 string.
    """
    pdf = SamvaBomPDF(f"Bill of Materials - {_safe(item_name)}")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Item name
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, _safe(item_name), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Metal details
    if metal_info:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "METAL", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        metal_type = metal_info.get("type", "Gold")
        karat = metal_info.get("karat", "22K")
        pdf.cell(60, 7, f"Type: {_safe(metal_type)} {_safe(karat)}")
        if weight_grams:
            pdf.cell(60, 7, f"Weight: {weight_grams}g")
        pdf.ln(7)

        if gold_rate_per_gram > 0 and weight_grams > 0:
            metal_cost = gold_rate_per_gram * weight_grams
            making = metal_cost * (making_charge_pct / 100)
            pdf.cell(60, 7, f"Gold Rate: Rs {gold_rate_per_gram:,.0f}/gm")
            pdf.cell(60, 7, f"Metal Cost: Rs {metal_cost:,.0f}")
            pdf.ln(7)
            pdf.cell(60, 7, f"Making ({making_charge_pct}%): Rs {making:,.0f}")
            pdf.cell(60, 7, f"Metal Total: Rs {metal_cost + making:,.0f}")
            pdf.ln(7)
        pdf.ln(4)

    # Stone inventory
    if stones and len(stones) > 0:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "STONES", new_x="LMARGIN", new_y="NEXT")

        # Table header
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(240, 240, 240)
        cols = [("Stone", 35), ("Shape", 25), ("Size", 20), ("Carat", 20), ("Color", 15), ("Clarity", 15), ("Qty", 10)]
        for name, w in cols:
            pdf.cell(w, 7, name, border=1, fill=True)
        pdf.ln(7)

        # Table rows
        pdf.set_font("Helvetica", "", 9)
        for s in stones:
            pdf.cell(35, 6, _safe(s.get("stone_type", "")), border=1)
            pdf.cell(25, 6, _safe(s.get("shape", "")), border=1)
            pdf.cell(20, 6, _safe(s.get("size_mm", "")), border=1)
            pdf.cell(20, 6, _safe(s.get("estimated_carat", "")), border=1)
            pdf.cell(15, 6, _safe(s.get("color_grade", "")), border=1)
            pdf.cell(15, 6, _safe(s.get("clarity_grade", "")), border=1)
            pdf.cell(10, 6, str(s.get("quantity", 1)), border=1)
            pdf.ln(6)
        pdf.ln(4)

    # Total
    if gold_rate_per_gram > 0 and weight_grams > 0:
        metal_cost = gold_rate_per_gram * weight_grams
        making = metal_cost * (making_charge_pct / 100)
        total = metal_cost + making

        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"ESTIMATED TOTAL: Rs {total:,.0f}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 6, "(Stone charges extra. Based on live gold rate.)", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    # Generate base64
    try:
        buffer = io.BytesIO()
        pdf.output(buffer)
        pdf_bytes = buffer.getvalue()
        b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        logger.info(f"BOM PDF generated: {len(pdf_bytes)} bytes")
        return b64
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return ""
