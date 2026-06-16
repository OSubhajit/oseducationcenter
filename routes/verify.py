"""
routes/verify.py
----------------
Public certificate verification — NO login required.
Anyone who scans the QR code lands here.

GET  /verify/<cert_id>          — JSON verification result
GET  /verify/<cert_id>/page     — Human-readable HTML verify page
"""
import hashlib
from datetime import datetime
from flask import Blueprint, jsonify, render_template_string
from markupsafe import escape

from db import get_certificates, get_students, get_courses, get_results

verify_bp = Blueprint("verify", __name__, url_prefix="/verify")


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _recompute_hash(cert_id: str, student_id: str, result_id: str) -> str:
    raw = f"{cert_id}:{student_id}:{result_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _build_verification_data(cert_id: str) -> dict:
    """
    Core verification logic used by both JSON and HTML endpoints.
    Returns a structured dict with all verification details.
    """
    cert = get_certificates().find_one({"cert_id": cert_id})

    if not cert:
        return {"valid": False, "reason": "Certificate ID not found in our records"}

    if cert.get("status") == "revoked":
        return {
            "valid"      : False,
            "reason"     : "This certificate has been revoked",
            "cert_id"    : cert_id,
            "revoked_at" : cert.get("revoked_at", ""),
        }

    # ── Tamper check ─────────────────────────────────
    stored_hash   = cert.get("hash", "")
    computed_hash = _recompute_hash(
        cert_id,
        cert["student_id"],
        cert["result_id"],
    )
    tamper_detected = stored_hash != computed_hash

    # ── Fetch related documents ───────────────────────
    student = get_students().find_one(
        {"student_id": cert["student_id"]},
        {"name": 1, "student_id": 1, "photo_url": 1, "_id": 0}
    )
    course = get_courses().find_one(
        {"course_id": cert["course_id"]},
        {"name": 1, "category": 1, "duration_weeks": 1, "_id": 0}
    )
    result = get_results().find_one(
        {"result_id": cert["result_id"]},
        {"scored_marks": 1, "total_marks": 1,
         "percentage": 1, "grade": 1, "video_url": 1,
         "face_integrity": 1, "created_at": 1, "_id": 0}
    )

    issued_date = cert.get("issued_date", "")
    if isinstance(issued_date, datetime):
        issued_date = issued_date.strftime("%d %B %Y")

    return {
        "valid"           : not tamper_detected,
        "tamper_detected" : tamper_detected,
        "cert_id"         : cert_id,
        "status"          : cert.get("status", "valid"),
        "issued_date"     : issued_date,
        "student"         : {
            "name"       : student["name"]       if student else "—",
            "student_id" : student["student_id"] if student else "—",
            "photo_url"  : student.get("photo_url","") if student else "",
        },
        "course"          : {
            "name"           : course["name"]           if course else "—",
            "category"       : course["category"]       if course else "—",
            "duration_weeks" : course["duration_weeks"] if course else "—",
        },
        "result"          : {
            "scored_marks" : result["scored_marks"]  if result else "—",
            "total_marks"  : result["total_marks"]   if result else "—",
            "percentage"   : result["percentage"]    if result else "—",
            "grade"        : result["grade"]         if result else "—",
            "exam_date"    : result["created_at"].strftime("%d %B %Y")
                             if result and isinstance(result.get("created_at"), datetime)
                             else "—",
            "face_integrity": result.get("face_integrity", {}) if result else {},
        },
        "download_url"    : cert.get("pdf_url", ""),
        "hash"            : stored_hash[:20] + "..." if stored_hash else "",
    }


# ═══════════════════════════════════════════════════════════════════
# JSON ENDPOINT (for API consumers)
# ═══════════════════════════════════════════════════════════════════

@verify_bp.get("/<cert_id>")
def verify_json(cert_id):
    """
    Returns JSON verification result.
    Used by third parties or employers to verify programmatically.
    """
    data = _build_verification_data(cert_id.upper())
    status_code = 200 if data.get("valid") else 404
    return jsonify(data), status_code


# ═══════════════════════════════════════════════════════════════════
# HTML PAGE (QR code scan lands here)
# ═══════════════════════════════════════════════════════════════════

@verify_bp.get("/<cert_id>/page")
def verify_page(cert_id):
    """
    Human-readable verify page. Rendered as inline HTML.
    No template file needed — self-contained.
    """
    d = _build_verification_data(cert_id.upper())

    if not d.get("valid"):
        reason = d.get("reason", "Invalid certificate")
        html = (INVALID_TEMPLATE
                .replace("{{REASON}}", str(escape(reason)))
                .replace("{{CERT_ID}}", str(escape(cert_id))))
        return html, 404

    # build photo block
    photo_url = d["student"].get("photo_url", "")
    if photo_url:
        photo_block = f'<img class="photo" src="{escape(photo_url)}" alt="Student photo">'
    else:
        initials = str(escape(d["student"]["name"][0].upper())) if d["student"]["name"] else "?"
        photo_block = f'<div class="photo-placeholder">{initials}</div>'

    html = VALID_TEMPLATE
    html = html.replace("{{PHOTO_BLOCK}}", photo_block)

    for key, val in {
        "{{CERT_ID}}"         : str(escape(d["cert_id"])),
        "{{STUDENT_NAME}}"    : str(escape(d["student"]["name"])),
        "{{STUDENT_ID}}"      : str(escape(d["student"]["student_id"])),
        "{{COURSE_NAME}}"     : str(escape(d["course"]["name"])),
        "{{COURSE_CATEGORY}}" : str(escape(d["course"]["category"])),
        "{{COURSE_DURATION}}" : str(escape(str(d["course"]["duration_weeks"]))) + " weeks",
        "{{GRADE}}"           : str(escape(str(d["result"]["grade"]))),
        "{{PERCENTAGE}}"      : str(escape(str(d["result"]["percentage"]))) + "%",
        "{{SCORED}}"          : str(escape(str(d["result"]["scored_marks"]))),
        "{{TOTAL}}"           : str(escape(str(d["result"]["total_marks"]))),
        "{{EXAM_DATE}}"       : str(escape(d["result"]["exam_date"])),
        "{{ISSUED_DATE}}"     : str(escape(d["issued_date"])),
        "{{HASH}}"            : str(escape(d["hash"])),
        "{{DOWNLOAD_URL}}"    : str(escape(d["download_url"])),
        # Map integrity value to a safe CSS class — never inject raw value as class
        "{{INTEGRITY_CLASS}}" : {"high": "high", "medium": "medium", "low": "low"}.get(
                                    str(d["result"]["face_integrity"].get("integrity", "")).lower(), "low"),
        "{{INTEGRITY}}"       : str(escape(d["result"]["face_integrity"].get("integrity", "—"))),
        "{{INTEGRITY_PCT}}"   : str(escape(str(d["result"]["face_integrity"].get("verified_pct", "—")))) + "%",
    }.items():
        html = html.replace(key, val)

    return html, 200


# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATES (inline — no separate template files needed)
# ═══════════════════════════════════════════════════════════════════

VALID_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Certificate Verified — OS Education Center</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5;
         display: flex; justify-content: center; padding: 40px 16px; }
  .card { background: #fff; border-radius: 16px; max-width: 600px;
          width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.10); overflow: hidden; }
  .header { background: #0D1B2A; padding: 32px; text-align: center; }
  .badge { display: inline-flex; align-items: center; gap: 8px;
           background: #22c55e; color: #fff; padding: 8px 20px;
           border-radius: 999px; font-weight: 700; font-size: 15px; }
  .badge svg { width: 18px; height: 18px; }
  .header h1 { color: #C9A84C; font-size: 22px; margin-top: 16px; }
  .header p  { color: #aaa; font-size: 13px; margin-top: 4px; }
  .photo-wrap { display: flex; justify-content: center; margin: 28px 0 0; }
  .photo { width: 90px; height: 90px; border-radius: 50%;
           object-fit: cover; border: 3px solid #C9A84C;
           background: #eee; }
  .photo-placeholder { width: 90px; height: 90px; border-radius: 50%;
           background: #0D1B2A; display: flex; align-items: center;
           justify-content: center; color: #C9A84C; font-size: 32px;
           font-weight: 700; border: 3px solid #C9A84C; }
  .body { padding: 24px 32px 32px; }
  .name { font-size: 26px; font-weight: 700; color: #0D1B2A;
          text-align: center; margin-top: 12px; }
  .sid  { text-align: center; color: #888; font-size: 13px; margin-top: 4px; }
  .divider { border: none; border-top: 1px solid #eee; margin: 20px 0; }
  .row { display: flex; justify-content: space-between;
         padding: 10px 0; border-bottom: 1px solid #f5f5f5; }
  .row:last-child { border-bottom: none; }
  .label { color: #666; font-size: 13px; }
  .value { color: #0D1B2A; font-weight: 600; font-size: 14px;
           text-align: right; max-width: 60%; }
  .grade-box { display: flex; justify-content: center; gap: 24px;
               background: #0D1B2A; border-radius: 12px;
               padding: 18px; margin: 20px 0; }
  .stat { text-align: center; }
  .stat .big { color: #C9A84C; font-size: 28px; font-weight: 800; }
  .stat .lbl { color: #aaa; font-size: 12px; margin-top: 2px; }
  .hash { background: #f8f8f8; border-radius: 8px; padding: 10px 14px;
          font-family: monospace; font-size: 11px; color: #999;
          word-break: break-all; margin-top: 16px; }
  .dl-btn { display: block; text-align: center; background: #C9A84C;
            color: #0D1B2A; font-weight: 700; padding: 14px;
            border-radius: 10px; text-decoration: none;
            margin-top: 20px; font-size: 15px; }
  .dl-btn:hover { background: #b8963f; }
  .footer { text-align: center; color: #bbb; font-size: 11px;
            padding: 16px; border-top: 1px solid #eee; }
  .integrity { display: inline-block; padding: 3px 10px; border-radius: 999px;
               font-size: 12px; font-weight: 600; }
  .high   { background: #dcfce7; color: #16a34a; }
  .medium { background: #fef9c3; color: #ca8a04; }
  .low    { background: #fee2e2; color: #dc2626; }
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div class="badge">
      <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
      </svg>
      CERTIFICATE VERIFIED
    </div>
    <h1>OS Education Center</h1>
    <p>Assam, India — Official Certificate Registry</p>
  </div>

  <div class="photo-wrap">
    {{PHOTO_BLOCK}}
  </div>

  <div class="body">
    <div class="name">{{STUDENT_NAME}}</div>
    <div class="sid">Student ID: {{STUDENT_ID}}</div>

    <div class="grade-box">
      <div class="stat"><div class="big">{{GRADE}}</div><div class="lbl">Grade</div></div>
      <div class="stat"><div class="big">{{PERCENTAGE}}</div><div class="lbl">Score</div></div>
      <div class="stat"><div class="big">{{SCORED}}/{{TOTAL}}</div><div class="lbl">Marks</div></div>
    </div>

    <div class="row"><span class="label">Course</span>
      <span class="value">{{COURSE_NAME}}</span></div>
    <div class="row"><span class="label">Category</span>
      <span class="value">{{COURSE_CATEGORY}}</span></div>
    <div class="row"><span class="label">Duration</span>
      <span class="value">{{COURSE_DURATION}}</span></div>
    <div class="row"><span class="label">Exam Date</span>
      <span class="value">{{EXAM_DATE}}</span></div>
    <div class="row"><span class="label">Issued On</span>
      <span class="value">{{ISSUED_DATE}}</span></div>
    <div class="row"><span class="label">Exam Integrity</span>
      <span class="value">
        <span class="integrity {{INTEGRITY_CLASS}}">{{INTEGRITY}} ({{INTEGRITY_PCT}} face verified)</span>
      </span></div>
    <div class="row"><span class="label">Certificate ID</span>
      <span class="value" style="font-family:monospace;font-size:12px">{{CERT_ID}}</span></div>

    <div class="hash">SHA-256: {{HASH}}</div>

    <a class="dl-btn" href="{{DOWNLOAD_URL}}" target="_blank">
      ⬇ Download Certificate PDF
    </a>
  </div>

  <div class="footer">
    Verified by OS Education Center Certificate Registry &bull;
    This certificate is tamper-proof and blockchain-grade hashed.
  </div>
</div>
</body>
</html>"""


INVALID_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invalid Certificate — OS Education Center</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5;
         display: flex; justify-content: center;
         align-items: center; min-height: 100vh; padding: 16px; }
  .card { background: #fff; border-radius: 16px; max-width: 480px;
          width: 100%; padding: 48px 32px; text-align: center;
          box-shadow: 0 4px 24px rgba(0,0,0,0.10); }
  .icon { font-size: 64px; margin-bottom: 16px; }
  h1 { color: #dc2626; font-size: 24px; margin-bottom: 12px; }
  p  { color: #666; font-size: 15px; line-height: 1.6; }
  .cert-id { font-family: monospace; background: #f8f8f8;
             padding: 8px 16px; border-radius: 8px;
             font-size: 13px; color: #999; margin-top: 20px;
             display: inline-block; }
  .contact { margin-top: 24px; font-size: 13px; color: #aaa; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">❌</div>
  <h1>Certificate Not Valid</h1>
  <p>{{REASON}}</p>
  <div class="cert-id">ID: {{CERT_ID}}</div>
  <p class="contact">
    If you believe this is an error, contact<br>
    <strong>OS Education Center, Assam, India</strong>
  </p>
</div>
</body>
</html>"""
