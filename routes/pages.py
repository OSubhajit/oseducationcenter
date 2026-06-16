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
