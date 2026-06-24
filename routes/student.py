"""
routes/student.py
-----------------
Student-facing portal routes. All require role=student JWT.

DASHBOARD
  GET  /student/dashboard               — enrolled courses, results summary, available exams

RESULTS
  GET  /student/results                 — all my results
  GET  /student/results/<result_id>     — one full result with AI feedback

CERTIFICATES
  GET  /student/certificates            — all my certificates
  GET  /student/certificates/<cert_id>  — one certificate detail + download URL

PROFILE
  GET  /student/profile                 — my profile info
  PUT  /student/profile/password        — change password
"""
import bcrypt
from functools import wraps
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from db import (get_students, get_results, get_certificates,
                get_exams, get_courses, get_batches, get_fees)

student_bp = Blueprint("student", __name__, url_prefix="/student")


# ═══════════════════════════════════════════════════════════════════
# DECORATOR
# ═══════════════════════════════════════════════════════════════════

def student_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if get_jwt().get("role") != "student":
            return jsonify({"error": "Student access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _clean(doc: dict) -> dict:
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


def _get_student() -> dict | None:
    student_id = get_jwt().get("student_id")
    return get_students().find_one(
        {"student_id": student_id},
        {"password_hash": 0, "face_encoding": 0}
    )


# ═══════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════

@student_bp.get("/dashboard")
@student_required
def dashboard():
    """
    Returns:
    - Student name, ID, photo
    - Enrolled courses with course details
    - Result summary (total exams taken, passed, failed)
    - Certificate count
    - Fee dues
    - Available exams (active exams for enrolled courses the student hasn't taken yet)
    """
    student = _get_student()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    student_id = student["student_id"]

    # ── Enrolled courses ─────────────────────────────
    enrolled_ids = student.get("enrolled_courses", [])
    courses = list(get_courses().find(
        {"course_id": {"$in": enrolled_ids}},
        {"_id": 0, "course_id": 1, "name": 1, "category": 1,
         "duration_weeks": 1, "fee": 1}
    ))

    # ── Results summary ──────────────────────────────
    all_results = list(get_results().find(
        {"student_id": student_id},
        {"result_id": 1, "exam_id": 1, "percentage": 1,
         "grade": 1, "passed": 1, "created_at": 1,
         "scored_marks": 1, "total_marks": 1}
    ))

    # ── Certificates ─────────────────────────────────
    cert_count = get_certificates().count_documents({
        "student_id": student_id,
        "status"    : "valid",
    })

    # ── Fee dues ─────────────────────────────────────
    dues_pipeline = [
        {"$match": {"student_id": student_id, "status": {"$ne": "paid"}}},
        {"$group": {"_id": None, "total_due": {"$sum": "$due_amount"}}}
    ]
    dues_res  = list(get_fees().aggregate(dues_pipeline))
    total_due = dues_res[0]["total_due"] if dues_res else 0

    # ── Available exams ───────────────────────────────
    # Active exams for enrolled courses that this student hasn't already taken
    taken_exam_ids = {r["exam_id"] for r in all_results}
    available_exams = []
    if enrolled_ids:
        candidate_exams = list(get_exams().find(
            {"course_id": {"$in": enrolled_ids}, "active": True},
            {"_id": 0, "exam_id": 1, "course_id": 1, "title": 1,
             "duration_minutes": 1, "total_marks": 1, "pass_marks": 1,
             "questions": 1}   # include questions so we can count them without a second query
        ))
        for exam in candidate_exams:
            if exam["exam_id"] not in taken_exam_ids:
                course_match = next(
                    (c for c in courses if c["course_id"] == exam["course_id"]), None
                )
                exam["course_name"]      = course_match["name"] if course_match else "—"
                exam["total_questions"]  = len(exam.pop("questions", []))  # count and remove from response
                available_exams.append(exam)

    return jsonify({
        "student": {
            "student_id" : student["student_id"],
            "name"       : student["name"],
            "email"      : student["email"],
            "phone"      : student["phone"],
            "photo_url"  : student.get("photo_url", ""),
        },
        "enrolled_courses"  : courses,
        "results_summary"   : {
            "total_exams"  : len(all_results),
            "certificates" : cert_count,
        },
        "fee_dues_inr"      : total_due,
        "available_exams"   : available_exams,
    }), 200


# ═══════════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════════

@student_bp.get("/results")
@student_required
def my_results():
    """List all results for the logged-in student."""
    student    = _get_student()
    student_id = student["student_id"]

    results = list(get_results().find(
        {"student_id": student_id},
        {"ai_evaluation": 0}   # exclude heavy field from list
    ).sort("created_at", -1))

    # enrich with exam title and course name
    enriched = []
    for r in results:
        exam   = get_exams().find_one(
            {"exam_id": r.get("exam_id")},
            {"title": 1, "course_id": 1, "pass_marks": 1}
        )
        course = None
        passed = False
        if exam:
            course = get_courses().find_one(
                {"course_id": exam["course_id"]},
                {"name": 1, "_id": 0}
            )
            passed = r.get("scored_marks", 0) >= exam.get("pass_marks", 0)

        r_clean = _clean(r)
        r_clean["exam_title"]   = exam["title"]   if exam   else "—"
        r_clean["course_name"]  = course["name"]  if course else "—"
        r_clean["passed"]       = passed
        enriched.append(r_clean)

    return jsonify({
        "total"  : len(enriched),
        "results": enriched,
    }), 200


@student_bp.get("/results/<result_id>")
@student_required
def my_result_detail(result_id):
    """Full result — includes AI feedback per written question."""
    student = _get_student()
    result  = get_results().find_one({
        "result_id" : result_id,
        "student_id": student["student_id"],
    })

    if not result:
        return jsonify({"error": "Result not found"}), 404

    exam   = get_exams().find_one({"exam_id": result["exam_id"]},
                                   {"title": 1, "course_id": 1, "pass_marks": 1})
    course = None
    passed = False
    if exam:
        course = get_courses().find_one(
            {"course_id": exam["course_id"]}, {"name": 1, "_id": 0}
        )
        passed = result.get("scored_marks", 0) >= exam.get("pass_marks", 0)

    # check if certificate exists for this result
    cert = get_certificates().find_one(
        {"result_id": result_id, "status": "valid"},
        {"cert_id": 1, "pdf_url": 1, "_id": 0}
    )

    r_clean = _clean(result)
    r_clean["exam_title"]  = exam["title"]  if exam   else "—"
    r_clean["course_name"] = course["name"] if course else "—"
    r_clean["passed"]      = passed
    r_clean["certificate"] = {
        "cert_id"      : cert["cert_id"],
        "pdf_url"      : cert.get("pdf_url", ""),
        "download_url" : cert.get("pdf_url", ""),   # alias used by results.html
        "verify_url"   : f"/api/verify/{cert['cert_id']}/page",
    } if cert else None

    # format AI feedback for clean display
    written = result.get("ai_evaluation", {}).get("written_answers", [])
    r_clean["written_feedback"] = [
        {
            "question"      : w.get("question"),
            "your_answer"   : w.get("student_answer"),
            "score"         : w.get("score"),
            "max_marks"     : w.get("max_marks"),
            "feedback"      : w.get("feedback"),
        }
        for w in written
    ]

    return jsonify(r_clean), 200


# ═══════════════════════════════════════════════════════════════════
# CERTIFICATES
# ═══════════════════════════════════════════════════════════════════

@student_bp.get("/certificates")
@student_required
def my_certificates():
    """
    List all certificates. Shows status so student knows what's pending.
    Only 'valid' ones have a downloadable PDF URL.
    """
    student = _get_student()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    from db import get_exams

    certs = list(
        get_certificates()
        .find({"student_id": student["student_id"]})
        .sort("created_at", -1)
    )

    enriched = []
    for c in certs:
        exam = get_exams().find_one(
            {"exam_id": c.get("exam_id", "")},
            {"title": 1, "course_id": 1, "_id": 0}
        )
        cc = _clean(c)
        cc["exam_title"]   = exam["title"]    if exam else "—"
        cc["downloadable"] = c.get("status") == "valid" and bool(c.get("pdf_url"))
        cc["pdf_url"]      = c.get("pdf_url") if c.get("status") == "valid" else None
        enriched.append(cc)

    return jsonify({"total": len(enriched), "certificates": enriched}), 200


@student_bp.get("/certificates/<cert_id>")
@student_required
def my_certificate_detail(cert_id):
    """Single certificate — includes download URL and verify URL."""
    student = _get_student()
    cert    = get_certificates().find_one({
        "cert_id"   : cert_id,
        "student_id": student["student_id"],
    })

    if not cert:
        return jsonify({"error": "Certificate not found"}), 404
    if cert.get("status") != "valid":
        return jsonify({"error": "Certificate is not valid"}), 403

    course = get_courses().find_one(
        {"course_id": cert["course_id"]},
        {"name": 1, "category": 1, "duration_weeks": 1, "_id": 0}
    )

    c_clean = _clean(cert)
    c_clean["course_name"]     = course["name"]           if course else "—"
    c_clean["course_category"] = course["category"]       if course else "—"
    c_clean["verify_url"]      = f"/api/verify/{cert_id}/page"
    c_clean["download_url"]    = cert.get("pdf_url", "")

    return jsonify(c_clean), 200


# ═══════════════════════════════════════════════════════════════════
# PROFILE
# ═══════════════════════════════════════════════════════════════════

@student_bp.get("/profile")
@student_required
def my_profile():
    student = _get_student()
    if not student:
        return jsonify({"error": "Student not found"}), 404
    return jsonify(_clean(student)), 200


@student_bp.put("/profile/password")
@student_required
def change_password():
    """Student can change their own password."""
    data         = request.get_json(silent=True) or {}
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if not old_password or not new_password:
        return jsonify({"error": "old_password and new_password required"}), 400

    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400

    student_id = get_jwt().get("student_id")
    # fetch full doc including password_hash (not excluded here unlike _get_student)
    student    = get_students().find_one({"student_id": student_id})
    if not student:
        return jsonify({"error": "Student not found"}), 404

    pwd_hash = student["password_hash"]
    if isinstance(pwd_hash, str):
        pwd_hash = pwd_hash.encode()
    if not bcrypt.checkpw(old_password.encode(), pwd_hash):
        return jsonify({"error": "Old password is incorrect"}), 401

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    get_students().update_one(
        {"student_id": student_id},
        {"$set": {"password_hash": new_hash}}
    )
    return jsonify({"message": "Password changed successfully"}), 200


# ═══════════════════════════════════════════════════════════════════
# EXAM INFO  (Fix #1 — exam.html start screen needs this)
# ═══════════════════════════════════════════════════════════════════

@student_bp.get("/exams/<exam_id>")
@student_required
def get_exam_for_student(exam_id):
    """
    Return exam metadata (no questions, no answers) so the student
    can review rules before starting.  Checks enrolment.
    """
    student = _get_student()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    exam = get_exams().find_one({"exam_id": exam_id, "active": True})
    if not exam:
        return jsonify({"error": "Exam not found or not active"}), 404

    if exam["course_id"] not in student.get("enrolled_courses", []):
        return jsonify({"error": "You are not enrolled in the course for this exam"}), 403

    # Check if already taken
    from db import get_results
    already_taken = get_results().find_one({
        "student_id": student["student_id"],
        "exam_id"   : exam_id,
    })

    return jsonify({
        "exam": {
            "exam_id"         : exam["exam_id"],
            "title"           : exam["title"],
            "course_id"       : exam["course_id"],
            "duration_minutes": exam["duration_minutes"],
            "total_marks"     : exam["total_marks"],
            "pass_marks"      : exam["pass_marks"],
            "total_questions" : len(exam.get("questions", [])),
            "instructions"    : exam.get("instructions", ""),
            "already_taken"   : bool(already_taken),
        }
    }), 200


# ═══════════════════════════════════════════════════════════════════
# EXAM EXTENSION — STUDENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

from flask import request, jsonify, send_file
import io


# ─────────────────────────────────────────────────────────────────────────────
# EXAM REPORTS (student access — only approved ones)
# ─────────────────────────────────────────────────────────────────────────────

@student_bp.get("/reports")
@student_required
def my_reports():
    """
    List all approved performance reports for the logged-in student.
    Pending or rejected reports are NOT returned here.
    """
    student = _get_student()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    from db import get_exam_reports, get_exams

    reports = list(
        get_exam_reports()
        .find(
            {"student_id": student["student_id"], "status": "approved"},
            {"report_content": 0}    # keep list lightweight
        )
        .sort("generated_at", -1)
        .limit(50)
    )

    enriched = []
    for r in reports:
        exam = get_exams().find_one(
            {"exam_id": r["exam_id"]},
            {"title": 1, "course_id": 1, "_id": 0}
        )
        rc = _clean(r)
        rc["exam_title"] = exam["title"]    if exam else "—"
        rc["course_id"]  = exam["course_id"] if exam else "—"
        enriched.append(rc)

    return jsonify({"total": len(enriched), "reports": enriched}), 200


@student_bp.get("/reports/<report_id>")
@student_required
def view_my_report(report_id):
    """
    View a specific approved report — includes full report_content.
    Returns 404 if report is pending or rejected (admin hasn't approved yet).
    """
    student = _get_student()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    from db import get_exam_reports, get_exams

    report = get_exam_reports().find_one({
        "report_id" : report_id,
        "student_id": student["student_id"],
        "status"    : "approved",
    })
    if not report:
        # Check if it exists but is pending
        pending = get_exam_reports().find_one({
            "report_id" : report_id,
            "student_id": student["student_id"],
        })
        if pending:
            return jsonify({
                "error"  : "Report is pending admin review. Check back later.",
                "status" : pending.get("status", "pending_approval"),
            }), 403
        return jsonify({"error": "Report not found"}), 404

    exam = get_exams().find_one(
        {"exam_id": report["exam_id"]},
        {"title": 1, "course_id": 1, "_id": 0}
    )
    rc = _clean(report)
    rc["exam_title"] = exam["title"]    if exam else "—"
    rc["course_id"]  = exam["course_id"] if exam else "—"
    return jsonify(rc), 200


@student_bp.get("/reports/<report_id>/pdf")
@student_required
def download_my_report_pdf(report_id):
    """
    Download the report PDF. Only works for approved reports.
    If PDF URL is set (uploaded to Cloudinary), redirects there.
    Otherwise generates on the fly.
    """
    student = _get_student()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    from db import get_exam_reports, get_exams

    report = get_exam_reports().find_one({
        "report_id" : report_id,
        "student_id": student["student_id"],
        "status"    : "approved",
    })
    if not report:
        return jsonify({
            "error": "Report not available. It may be pending admin approval."
        }), 404

    # If PDF already generated, serve from Cloudinary (redirect)
    if report.get("pdf_url"):
        from flask import redirect
        return redirect(report["pdf_url"])

    # Generate on the fly
    exam = get_exams().find_one({"exam_id": report["exam_id"]})
    from services.exam_report_service import generate_report_pdf
    pdf_bytes = generate_report_pdf(
        report_doc   = report,
        student_name = student["name"],
        exam_title   = exam["title"] if exam else "Exam",
        course_name  = exam.get("course_id","") if exam else "",
    )
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype      = "application/pdf",
        as_attachment = True,
        download_name = f"my_report_{report_id}.pdf",
    )


# ─────────────────────────────────────────────────────────────────────────────
# CERTIFICATES — APPROVED ONLY
# ─────────────────────────────────────────────────────────────────────────────

@student_bp.get("/certificates/<cert_id>/pdf")
@student_required
def download_my_certificate_pdf(cert_id):
    """
    Download a certificate PDF. Only returns if status == 'valid' (approved).
    """
    student = _get_student()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    from db import get_certificates

    cert = get_certificates().find_one({
        "cert_id"   : cert_id,
        "student_id": student["student_id"],
    })
    if not cert:
        return jsonify({"error": "Certificate not found"}), 404

    if cert.get("status") == "pending_approval":
        return jsonify({
            "error"  : "Certificate is pending admin approval. Check back later.",
            "status" : "pending_approval",
        }), 403

    if cert.get("status") == "rejected":
        return jsonify({
            "error"  : "Certificate was not approved. Contact your teacher for details.",
            "status" : "rejected",
        }), 403

    # Valid — redirect to PDF URL or generate
    if cert.get("pdf_url"):
        from flask import redirect
        return redirect(cert["pdf_url"])

    return jsonify({"error": "Certificate PDF not available. Contact admin."}), 404


