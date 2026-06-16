"""
services/cert_generator.py
--------------------------
Generates a professional PDF certificate using ReportLab.
Embeds a QR code that links to the public verify URL.
"""
import io
import hashlib
import qrcode
from datetime import datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from flask import current_app


# ── Colours ──────────────────────────────────────────────────────
NAVY    = colors.HexColor("#0D1B2A")
GOLD    = colors.HexColor("#C9A84C")
LIGHT   = colors.HexColor("#F5F5F0")
WHITE   = colors.white
GRAY    = colors.HexColor("#555555")


# ── QR Code generator ────────────────────────────────────────────

def generate_qr(cert_id: str) -> io.BytesIO:
    """Returns a BytesIO PNG of the QR code."""
    website = current_app.config.get("CENTER_WEBSITE", "https://oseducationcenter.com")
    url     = f"{website}/api/verify/{cert_id}/page"

    qr = qrcode.QRCode(
        version        = 1,
        error_correction = qrcode.constants.ERROR_CORRECT_H,
        box_size       = 6,
        border         = 2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0D1B2A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ── Certificate hash ─────────────────────────────────────────────

def generate_cert_hash(cert_id: str, student_id: str, result_id: str) -> str:
    """SHA-256 hash for tamper detection."""
    raw = f"{cert_id}:{student_id}:{result_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── PDF Certificate ──────────────────────────────────────────────

def generate_certificate_pdf(
    cert_id        : str,
    student_name   : str,
    student_id     : str,
    course_name    : str,
    grade          : str,
    percentage     : float,
    issued_date    : datetime,
    result_id      : str,
) -> bytes:
    """
    Generates a landscape A4 PDF certificate.
    Returns raw PDF bytes (ready to upload to Cloudinary or send to browser).
    """
    buf = io.BytesIO()

    # ── Page setup ───────────────────────────────────
    page_w, page_h = landscape(A4)
    c = canvas.Canvas(buf, pagesize=landscape(A4))

    # ── Background ───────────────────────────────────
    c.setFillColor(LIGHT)
    c.rect(0, 0, page_w, page_h, fill=True, stroke=False)

    # ── Outer border ─────────────────────────────────
    c.setStrokeColor(NAVY)
    c.setLineWidth(8)
    c.rect(1*cm, 1*cm, page_w - 2*cm, page_h - 2*cm, fill=False, stroke=True)

    # ── Inner gold border ─────────────────────────────
    c.setStrokeColor(GOLD)
    c.setLineWidth(2)
    c.rect(1.4*cm, 1.4*cm, page_w - 2.8*cm, page_h - 2.8*cm, fill=False, stroke=True)

    # ── Top navy header bar ───────────────────────────
    c.setFillColor(NAVY)
    c.rect(1*cm, page_h - 5*cm, page_w - 2*cm, 3.5*cm, fill=True, stroke=False)

    # ── Center name in header ─────────────────────────
    center_name = current_app.config.get("CENTER_NAME", "OS Education Center")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(page_w / 2, page_h - 3.2*cm, center_name.upper())

    c.setFont("Helvetica", 12)
    c.setFillColor(GOLD)
    c.drawCentredString(page_w / 2, page_h - 4.2*cm,
                        current_app.config.get("CENTER_ADDRESS","Assam, India")
                        + "  •  "
                        + current_app.config.get("CENTER_WEBSITE",""))

    # ── "Certificate of Completion" title ────────────
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(page_w / 2, page_h - 7.2*cm, "Certificate of Completion")

    # ── Gold divider ──────────────────────────────────
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.line(5*cm, page_h - 7.6*cm, page_w - 5*cm, page_h - 7.6*cm)

    # ── "This is to certify that" ─────────────────────
    c.setFillColor(GRAY)
    c.setFont("Helvetica", 13)
    c.drawCentredString(page_w / 2, page_h - 9*cm, "This is to certify that")

    # ── Student name ──────────────────────────────────
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(page_w / 2, page_h - 10.8*cm, student_name.upper())

    # ── Student ID ────────────────────────────────────
    c.setFillColor(GRAY)
    c.setFont("Helvetica", 11)
    c.drawCentredString(page_w / 2, page_h - 11.6*cm, f"Student ID: {student_id}")

    # ── "has successfully completed" ─────────────────
    c.setFont("Helvetica", 13)
    c.drawCentredString(page_w / 2, page_h - 12.6*cm, "has successfully completed the course")

    # ── Course name ───────────────────────────────────
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(page_w / 2, page_h - 13.8*cm, course_name)

    # ── Grade badge box ───────────────────────────────
    badge_x = page_w / 2 - 3*cm
    badge_y = page_h - 16.5*cm
    c.setFillColor(NAVY)
    c.roundRect(badge_x, badge_y, 6*cm, 2*cm, 0.3*cm, fill=True, stroke=False)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(page_w / 2, badge_y + 1.2*cm,
                        f"Grade: {grade}   |   Score: {percentage:.1f}%")

    # ── Issue date ────────────────────────────────────
    c.setFillColor(GRAY)
    c.setFont("Helvetica", 11)
    date_str = issued_date.strftime("%d %B %Y")
    c.drawCentredString(page_w / 2, page_h - 17.5*cm, f"Issued on: {date_str}")

    # ── Signature line (left) ─────────────────────────
    sig_y = 3.5*cm
    c.setStrokeColor(NAVY)
    c.setLineWidth(1)
    c.line(3*cm, sig_y, 10*cm, sig_y)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(6.5*cm, sig_y - 0.5*cm, "Director / Authorized Signatory")
    c.setFont("Helvetica", 9)
    c.drawCentredString(6.5*cm, sig_y - 1*cm, center_name)

    # ── Cert ID + hash (bottom center) ───────────────
    cert_hash = generate_cert_hash(cert_id, student_id, result_id)
    c.setFillColor(GRAY)
    c.setFont("Helvetica", 8)
    c.drawCentredString(page_w / 2, 2.2*cm, f"Certificate ID: {cert_id}")
    c.drawCentredString(page_w / 2, 1.7*cm,
                        f"Verify at: {current_app.config.get('CENTER_WEBSITE','')}/api/verify/{cert_id}/page")
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#999999"))
    c.drawCentredString(page_w / 2, 1.3*cm, f"Hash: {cert_hash[:48]}...")

    # ── QR Code (bottom right) ────────────────────────
    qr_buf  = generate_qr(cert_id)
    qr_img  = ImageReader(qr_buf)
    qr_size = 3.5*cm
    c.drawImage(qr_img,
                page_w - 1*cm - qr_size - 1*cm,
                1*cm,
                width=qr_size,
                height=qr_size,
                preserveAspectRatio=True)

    c.setFont("Helvetica", 7)
    c.setFillColor(GRAY)
    c.drawCentredString(
        page_w - 1*cm - qr_size/2 - 1*cm,
        0.7*cm,
        "Scan to verify"
    )

    c.save()
    buf.seek(0)
    return buf.read()
