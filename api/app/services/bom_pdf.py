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
    totals: dict = None,
) -> str:
    """
    Generate a BOM PDF and return as base64 string.
    Handles both GemLens stone_grid format and simple stone_inventory format.
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
        pdf.set_fill_color(245, 240, 225)
        pdf.cell(0, 8, "METAL DETAILS", new_x="LMARGIN", new_y="NEXT", fill=True)
        pdf.set_font("Helvetica", "", 10)
        metal_type = metal_info.get("type", "Gold")
        karat = metal_info.get("karat", "22K")
        color = metal_info.get("color", "")
        color_str = f" ({color})" if color else ""
        pdf.cell(90, 7, f"Type: {_safe(metal_type)} {_safe(karat)}{_safe(color_str)}")
        if weight_grams:
            pdf.cell(90, 7, f"Weight: {weight_grams:.1f}g")
        pdf.ln(7)

        if gold_rate_per_gram > 0:
            pdf.cell(90, 7, f"Live Gold Rate: Rs {gold_rate_per_gram:,.0f}/gm ({_safe(karat)})")
            pdf.ln(7)
            if weight_grams > 0:
                metal_cost = gold_rate_per_gram * weight_grams
                making = metal_cost * (making_charge_pct / 100)
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(60, 7, f"Metal Cost: Rs {metal_cost:,.0f}")
                pdf.cell(60, 7, f"Making ({making_charge_pct}%): Rs {making:,.0f}")
                pdf.cell(60, 7, f"Metal Total: Rs {metal_cost + making:,.0f}")
                pdf.set_font("Helvetica", "", 10)
                pdf.ln(7)
        pdf.ln(4)

    # Stone grid table (GemLens format: sieve, mm, weight_per_piece, quantity, total_weight, quality_grade)
    if stones and len(stones) > 0:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_fill_color(245, 240, 225)
        pdf.cell(0, 8, "STONE INVENTORY", new_x="LMARGIN", new_y="NEXT", fill=True)

        # Table header — handles both formats
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(235, 230, 215)
        has_sieve = any(s.get("sieve_size") for s in stones)
        if has_sieve:
            cols = [("Stone", 28), ("Shape", 22), ("Sieve", 20), ("MM", 18), ("Ct/Pc", 18), ("Qty", 14), ("Total Ct", 20), ("Grade", 30)]
        else:
            cols = [("Stone", 35), ("Shape", 25), ("Size", 20), ("Carat", 20), ("Color", 15), ("Clarity", 15), ("Qty", 12)]
        for name, w in cols:
            pdf.cell(w, 7, name, border=1, fill=True, align="C")
        pdf.ln(7)

        # Table rows
        pdf.set_font("Helvetica", "", 8)
        total_stones = 0
        for s in stones:
            if has_sieve:
                wt_pc = s.get("weight_per_piece", "")
                wt_str = f"{float(wt_pc):.3f}" if wt_pc and str(wt_pc).replace('.','').isdigit() else str(wt_pc or "-")
                total_wt = s.get("total_weight", "")
                total_str = f"{float(total_wt):.3f}" if total_wt and str(total_wt).replace('.','').isdigit() else str(total_wt or "-")
                qty = s.get("quantity", 0)
                total_stones += int(qty) if qty else 0
                pdf.cell(28, 6, _safe(str(s.get("stone_type", "-"))), border=1, align="C")
                pdf.cell(22, 6, _safe(str(s.get("shape", "-"))), border=1, align="C")
                pdf.cell(20, 6, _safe(str(s.get("sieve_size", "-"))), border=1, align="C")
                pdf.cell(18, 6, _safe(str(s.get("mm_size", "-"))), border=1, align="C")
                pdf.cell(18, 6, _safe(wt_str), border=1, align="C")
                pdf.cell(14, 6, str(qty or "-"), border=1, align="C")
                pdf.cell(20, 6, _safe(total_str), border=1, align="C")
                pdf.cell(30, 6, _safe(str(s.get("quality_grade", "-"))), border=1, align="C")
            else:
                qty = s.get("quantity", 1)
                total_stones += int(qty) if qty else 0
                pdf.cell(35, 6, _safe(str(s.get("stone_type", ""))), border=1)
                pdf.cell(25, 6, _safe(str(s.get("shape", ""))), border=1)
                pdf.cell(20, 6, _safe(str(s.get("size_mm", s.get("mm_size", "")))), border=1)
                pdf.cell(20, 6, _safe(str(s.get("estimated_carat", s.get("weight_per_piece", "")))), border=1)
                pdf.cell(15, 6, _safe(str(s.get("color_grade", ""))), border=1)
                pdf.cell(15, 6, _safe(str(s.get("clarity_grade", s.get("quality_grade", "")))), border=1)
                pdf.cell(12, 6, str(qty), border=1)
            pdf.ln(6)

        # Totals row
        if totals or total_stones:
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(235, 230, 215)
            tc = totals.get("total_stone_count", total_stones) if totals else total_stones
            tw = totals.get("total_carat_weight", "") if totals else ""
            tw_str = f"{float(tw):.3f}" if tw and str(tw).replace('.','').isdigit() else str(tw or "")
            if has_sieve:
                pdf.cell(108, 7, "TOTAL", border=1, fill=True, align="R")
                pdf.cell(14, 7, str(tc), border=1, fill=True, align="C")
                pdf.cell(20, 7, _safe(tw_str), border=1, fill=True, align="C")
                pdf.cell(30, 7, "", border=1, fill=True)
            else:
                pdf.cell(100, 7, "TOTAL", border=1, fill=True, align="R")
                pdf.cell(42, 7, f"{tc} stones", border=1, fill=True, align="C")
            pdf.ln(7)
        pdf.ln(4)

    # Grand Total
    if gold_rate_per_gram > 0 and weight_grams > 0:
        metal_cost = gold_rate_per_gram * weight_grams
        making = metal_cost * (making_charge_pct / 100)
        total = metal_cost + making

        pdf.ln(4)
        pdf.set_draw_color(200, 170, 80)
        pdf.set_line_width(0.8)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 10, f"ESTIMATED TOTAL: Rs {total:,.0f}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 6, "(Stone charges extra. Based on live gold rate. Making charges may vary.)", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    elif not weight_grams:
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 6, "(Weight not detected from image. Share actual weight for pricing.)", new_x="LMARGIN", new_y="NEXT")
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
