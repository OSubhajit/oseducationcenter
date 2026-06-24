"""
routes/pages.py
---------------
Serves all HTML pages. No auth here — auth is handled
client-side via JWT in localStorage, checked by api.js.
"""
from flask import Blueprint, render_template, redirect

pages_bp = Blueprint("pages", __name__)

# ── Root ──────────────────────────────────────────────
@pages_bp.get("/")
def root():
    return redirect("/admin/login")

# ── Admin pages ───────────────────────────────────────
@pages_bp.get("/admin/login")
def admin_login_page():
    return render_template("admin/login.html")

@pages_bp.get("/admin/dashboard")
def admin_dashboard():
    return render_template("admin/dashboard.html")

@pages_bp.get("/admin/students")
def admin_students():
    return render_template("admin/students.html")

@pages_bp.get("/admin/courses")
def admin_courses():
    return render_template("admin/courses.html")

@pages_bp.get("/admin/batches")
def admin_batches():
    return render_template("admin/batches.html")

@pages_bp.get("/admin/fees")
def admin_fees():
    return render_template("admin/fees.html")

@pages_bp.get("/admin/exams")
def admin_exams():
    return render_template("admin/exams.html")

@pages_bp.get("/admin/questions")
def admin_questions():
    return render_template("admin/questions.html")

@pages_bp.get("/admin/results")
def admin_results():
    return render_template("admin/results.html")

@pages_bp.get("/admin/teachers")
def admin_teachers():
    return render_template("admin/teachers.html")

# ── Teacher portal ────────────────────────────────────
@pages_bp.get("/teacher/login")
def teacher_login_page():
    return render_template("teacher/login.html")

@pages_bp.get("/teacher/dashboard")
def teacher_dashboard():
    return render_template("teacher/dashboard.html")

@pages_bp.get("/teacher/resources")
def teacher_resources():
    return render_template("teacher/resources.html")

@pages_bp.get("/teacher/assignments")
def teacher_assignments():
    return render_template("teacher/assignments.html")

# ── Student pages ─────────────────────────────────────
@pages_bp.get("/student/login")
def student_login_page():
    return render_template("student/login.html")

@pages_bp.get("/student/dashboard")
def student_dashboard():
    return render_template("student/dashboard.html")

@pages_bp.get("/student/assignments")
def student_assignments():
    return render_template("student/assignments.html")

@pages_bp.get("/student/resources")
def student_resources():
    return render_template("student/resources.html")

@pages_bp.get("/student/results")
def student_results():
    return render_template("student/results.html")

@pages_bp.get("/student/certificates")
def student_certificates():
    return render_template("student/certificates.html")

# ── Exam page ─────────────────────────────────────────
@pages_bp.get("/exam/take")
def exam_take():
    return render_template("exam/exam.html")

@pages_bp.get("/exam/<exam_id>")
def exam_page(exam_id):
    """Student navigates here from dashboard: /exam/OSEC-EXM-XXXXXX"""
    return render_template("exam/exam.html")
<<<<<<< HEAD


# ── Exam extension pages ──────────────────────────────────────────
#
# AUTH PATTERN (applies to ALL page routes in this file):
# Pages are served without server-side JWT verification. Auth is handled
# entirely by client-side JS (api.js / sidebar.js) which checks for a valid
# token and redirects to the login page if missing or expired. This is
# consistent with every other page route above. The API endpoints behind
# these pages are independently protected by @jwt_required decorators.

@pages_bp.get("/teacher/generate-exam")
def generate_exam_page():
    return render_template("teacher/generate_exam.html")


@pages_bp.get("/exam/room/<session_id>")
def exam_room(session_id):
    # Look up session/exam metadata so the template can pre-populate the
    # timer and hidden fields. No auth check here — the exam API endpoints
    # that actually serve questions and accept answers all require a valid
    # student JWT. A URL-guessed session_id with no matching JWT will get 403
    # from every subsequent API call, so no data is exposed by serving the page.
    from db import get_exam_sessions, get_exams
    session = get_exam_sessions().find_one({"session_id": session_id})
    if not session:
        return redirect("/student/dashboard")
    exam = get_exams().find_one({"exam_id": session["exam_id"]})
    return render_template(
        "exam/exam_room.html",
        session_id       = session_id,
        exam_id          = session["exam_id"],
        duration_minutes = exam.get("duration_minutes", 180) if exam else 180,
    )
=======
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c
