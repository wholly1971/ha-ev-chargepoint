"""Printable invoice presentation, derived only from the issued snapshot."""

from html import escape
from io import BytesIO
from pathlib import Path
import re

from .billing import decimal, money, invoice_items, INVOICE_LAYOUT_LABELS, net_amount
from .branding import logo_bytes


def invoice_filename(invoice):
    """Safe attachment name; never use a customer-supplied path."""
    number = re.sub(r"[^A-Za-z0-9._-]", "_", str(invoice["number"]))[:120]
    return f"{number or 'EV-invoice'}.pdf"


def invoice_rows(invoice):
    """Return presentation rows shared with the email body."""
    return [(row["description"], row["quantity"], row["rate"], row["amount"])
            for row in invoice_items(invoice)]


def invoice_pdf(invoice, *, sample=False):
    """Generate A4 PDF bytes in an executor; no network or mutable config reads."""
    try:
        return _render_pdf(invoice, sample=sample)
    except Exception as err:
        # Normalize renderer errors at this boundary so delivery tracking can
        # mark failure without sending an attachment-less substitute.
        raise ValueError("Invoice PDF generation failed") from err


def _render_pdf(invoice, *, sample=False):
    """Render the original invoice values without changing accounting records."""
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    # Font files ship with ReportLab; no OS fonts or downloads are required.
    fonts = Path(reportlab.__file__).parent / "fonts"
    for name, file in (("EVSans", "Vera.ttf"), ("EVSansBold", "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / file)))
    navy, coral, grey = colors.HexColor("#152a4a"), colors.HexColor("#cf655c"), colors.HexColor("#627083")
    body = ParagraphStyle("EVBody", fontName="EVSans", fontSize=9, leading=13, textColor=navy, wordWrap="CJK")
    small = ParagraphStyle("EVSmall", parent=body, fontSize=8, leading=11, textColor=grey)
    label = ParagraphStyle("EVLabel", parent=body, fontName="EVSansBold", fontSize=8, leading=12)
    right = ParagraphStyle("EVRight", parent=body, alignment=TA_RIGHT)
    heading = ParagraphStyle("EVHeading", parent=body, fontName="EVSansBold", fontSize=32, leading=38)

    def p(text, style=body):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

    config = invoice["settings"]
    currency = config["currency"]
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=(595.28, 841.89), rightMargin=42, leftMargin=42,
                            topMargin=38, bottomMargin=85, title=f"Invoice {invoice['number']}",
                            author="EV ChargePoint")
    width = doc.width
    image_data = logo_bytes()
    iw, ih = ImageReader(BytesIO(image_data)).getSize()
    logo_width = 135
    logo = Image(BytesIO(image_data), width=logo_width, height=logo_width * ih / iw)
    logo.hAlign = "RIGHT"
    top = Table([[p("INVOICE", heading), logo]], colWidths=[width - 155, 155])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [top, Spacer(1, 20)]
    if sample:
        story += [p("SAMPLE - FOR PREVIEW ONLY - NOT A PAYMENT REQUEST", label), Spacer(1, 12)]
    meta = Table([
        [p("FROM", label), p("BILL TO", label), p("INVOICE DETAILS", label)],
        [p(config.get("seller") or "Seller details not configured"),
         p(config.get("customer") or "Customer details not configured"),
         p(f"Invoice: {invoice['number']}\nIssued: {invoice['issued_at'][:10]}\nBilling period: {invoice['period']}\nCurrency: {currency}\nLayout: {INVOICE_LAYOUT_LABELS.get(config.get('invoice_billing_option', 'itemised'), 'Itemised tariff charging')}", small)],
    ], colWidths=[width * .33, width * .33, width * .34])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story += [meta, Spacer(1, 24)]
    data = [[p("QTY / kWh", label), p("DESCRIPTION", label), p(f"UNIT RATE / {currency}", label), p(f"AMOUNT / {currency}", label)]]
    for name, quantity, rate, amount in invoice_rows(invoice):
        rate_text = (f"{rate:.6f}".rstrip("0").rstrip(".") if rate is not None else "-")
        if rate is not None and rate and decimal(rate_text) == 0:
            rate_text = f"{rate.normalize():f}"
        if rate is not None and "." not in rate_text:
            rate_text += ".00"
        elif rate is not None and len(rate_text.rsplit(".", 1)[1]) < 2:
            rate_text += "0"
        data.append([p(f"{quantity:.6f}", right), p(name), p(rate_text, right), p(money(amount), right)])
    if net_amount(config, "fixed_fee"):
        data.append([p("1", right), p("Monthly fixed fee"), p(money(net_amount(config, "fixed_fee")), right), p(money(net_amount(config, "fixed_fee")), right)])
    if len(data) == 1:
        data.append([p("0", right), p("No recorded billable charging"), p("-", right), p("0.00", right)])
    table = Table(data, colWidths=[73, width - 270, 97, 100], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEABOVE", (0, 0), (-1, 0), 1.2, coral), ("LINEBELOW", (0, 0), (-1, 0), 1.2, coral), ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 10), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    story += [table, Spacer(1, 12)]
    totals = Table([[p("Subtotal", right), p(invoice["subtotal"], right)],
                    [p("GST included in total", right), p(invoice["tax"], right)],
                    [p(f"TOTAL {currency}", label), p(f"{currency} {invoice['total']}", ParagraphStyle("EVTotal", parent=right, fontName="EVSansBold", fontSize=15, leading=20))]],
                   colWidths=[170, 125], hAlign="RIGHT")
    totals.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LINEABOVE", (0, 2), (-1, 2), 1, coral), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [totals, Spacer(1, 16), p("Prices shown exclude GST. GST-inclusive inputs have their GST extracted once. A dash in Unit rate means combined recorded rates. Totals use unrounded recorded energy; displayed rates use up to six decimals and amounts are rounded to two decimals.", small)]
    notes = []
    if invoice.get("tax_breakdown"):
        notes.append("GST breakdown: " + "; ".join(f"{rate}%: {currency} {amount}" for rate, amount in invoice["tax_breakdown"].items()))
    if invoice.get("partial") or invoice.get("gap_seconds"):
        notes.append(f"Approved incomplete period. Missing data: {invoice.get('gap_seconds', 0)} seconds. Only recorded usage is billed.")
    for item in invoice.get("tariffs", {}).values():
        if decimal(item.get("outside_schedule_kwh", "0")):
            notes.append(f"{item['name']}: {decimal(item['outside_schedule_kwh']):.6f} kWh recorded outside the charging schedule.")
        if decimal(item.get("fallback_kwh", "0")):
            notes.append(f"{item['name']}: {decimal(item['fallback_kwh']):.6f} kWh priced using the manual fallback rate.")
    if notes:
        story += [Spacer(1, 12), p("BILLING NOTES", label), p("\n".join(notes), small)]
    story += [Spacer(1, 30), KeepTogether([p("PAYMENT DETAILS & TERMS", label), Spacer(1, 7), p(config.get("payment_instructions") or "Payment instructions have not been configured.")])]

    def footer(canvas, document):
        canvas.setStrokeColor(coral)
        canvas.line(42, 66, 553, 66)
        canvas.setFillColor(navy)
        canvas.setFont("Helvetica-Oblique", 19)
        canvas.drawString(42, 40, "Thank you")
        canvas.setFont("EVSans", 7)
        canvas.drawRightString(553, 43, f"EV ChargePoint | Page {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
