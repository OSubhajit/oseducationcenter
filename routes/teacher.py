"""
routes/teacher.py
-----------------
Teacher-facing portal routes. All require role=teacher JWT.
"""

import bcrypt
from functools import wraps
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from validators import safe_str

from db import (get_teachers, get_courses, get_batches,
                get_assignments, get_assignment_submissions,
                get_resources, get_students, get_results, get_exams)

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")


# ═════════════════════════════════════════════════════════════════════════
# DECORATOR
# ═════════════════════════════════════════════════════════════════════════

def teacher_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        role = get_jwt().get("role")
        # Allow both teachers and admins (admins can preview the teacher portal)
        if role not in ("teacher", "admin"):
            return jsonify({"error": "Teacher access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


# ═════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════

def _clean(doc: dict) -> dict:
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


def _get_teacher() -> dict | None:
    teacher_id = get_jwt().get("teacher_id")
    return get_teachers().find_one(
        {"teacher_id": teacher_id},
        {"password_hash": 0}
    )


# ═════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═════════════════════════════════════════════════════════════════════════

@teacher_bp.get("/dashboard")
@teacher_required
def dashboard():
    """
    Returns:
    - Teacher name, ID, photo
    - Courses taught by this teacher
    - Recent assignments created
    - Pending submissions to grade
    """
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    teacher_id = teacher["teacher_id"]

    # Courses this teacher is assigned to teach (authoritative — set by admin).
    course_ids = teacher.get("teaches", [])
    courses = list(get_courses().find(
        {"course_id": {"$in": course_ids}},
        {"_id": 0, "course_id": 1, "name": 1, "category": 1,
         "duration_weeks": 1, "fee": 1}
    )) if course_ids else []

    # Recent assignments created by this teacher
    recent_assignments = list(get_assignments().find(
        {"created_by": teacher_id},
        {"_id": 0, "assignment_id": 1, "title": 1, "course_id": 1, "created_at": 1}
    ).sort("created_at", -1).limit(5))

    # Enrich assignments with course names
    for assignment in recent_assignments:
        course = get_courses().find_one(
            {"course_id": assignment["course_id"]},
            {"name": 1, "_id": 0}
        )
        assignment["course_name"] = course["name"] if course else "—"

    # Count pending submissions for assignments created by this teacher —
    # done with a single aggregation instead of a nested find + count_documents.
    pending_pipeline = [
        {"$match": {"created_by": teacher_id}},
        {"$project": {"assignment_id": 1, "_id": 0}},
        {"$lookup": {
            "from"        : "assignment_submissions",
            "localField"  : "assignment_id",
            "foreignField": "assignment_id",
            "as"          : "subs",
            "pipeline"    : [{"$match": {"status": "submitted"}}],
        }},
        {"$unwind": "$subs"},
        {"$count": "total"},
    ]
    pending_result            = list(get_assignments().aggregate(pending_pipeline))
    pending_submissions_count = pending_result[0]["total"] if pending_result else 0

    return jsonify({
        "teacher": {
            "teacher_id" : teacher["teacher_id"],
            "name"       : teacher["name"],
            "email"      : teacher["email"],
            "phone"      : teacher["phone"],
            "photo_url"  : teacher.get("photo_url", ""),
        },
        "courses_taught"  : courses,
        "recent_assignments": recent_assignments,
        "pending_submissions": pending_submissions_count,
    }), 200


# ═════════════════════════════════════════════════════════════════════════
# COURSES MANAGEMENT (View only for teachers)
# ═════════════════════════════════════════════════════════════════════════

@teacher_bp.get("/courses")
@teacher_required
def my_courses():
    """List courses that this teacher has created content for."""
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    teacher_id = teacher["teacher_id"]

    # Courses this teacher is assigned to teach (authoritative).
    course_ids = teacher.get("teaches", [])

    courses = list(get_courses().find(
        {"course_id": {"$in": course_ids}},
        {"_id": 0, "course_id": 1, "name": 1, "category": 1,
         "duration_weeks": 1, "fee": 1, "active": 1}
    )) if course_ids else []

    # Add counts for each course
    for course in courses:
        course_id = course["course_id"]
        course["assignment_count"] = get_assignments().count_documents({
            "course_id": course_id,
            "created_by": teacher_id
        })
        course["resource_count"] = get_resources().count_documents({
            "course_id": course_id,
            "uploaded_by": teacher_id
        })

    return jsonify({
        "total": len(courses),
        "courses": courses
    }), 200


# ═════════════════════════════════════════════════════════════════════════
# PROFILE
# ═════════════════════════════════════════════════════════════════════════

@teacher_bp.get("/profile")
@teacher_required
def my_profile():
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404
    return jsonify(_clean(teacher)), 200


@teacher_bp.put("/profile/password")
@teacher_required
def change_password():
    """Teacher can change their own password."""
    data         = request.get_json(silent=True) or {}
    old_password = safe_str(data, "old_password", strip=False)
    new_password = safe_str(data, "new_password", strip=False)

    if not old_password or not new_password:
        return jsonify({"error": "old_password and new_password required"}), 400

    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400

    teacher_id = get_jwt().get("teacher_id")
    # fetch full doc including password_hash (not excluded here unlike _get_teacher)
    teacher    = get_teachers().find_one({"teacher_id": teacher_id})
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    pwd_hash = teacher["password_hash"]
    if isinstance(pwd_hash, str):
        pwd_hash = pwd_hash.encode()
    if not bcrypt.checkpw(old_password.encode(), pwd_hash):
        return jsonify({"error": "Old password is incorrect"}), 401

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    get_teachers().update_one(
        {"teacher_id": teacher_id},
        {"$set": {"password_hash": new_hash}}
    )
<<<<<<< HEAD
    return jsonify({"message": "Password changed successfully"}), 200


# ═══════════════════════════════════════════════════════════════════
# EXAM EXTENSION — TEACHER ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

import io
from datetime import datetime
from flask import request, jsonify

# NOTE: teacher_bp, teacher_required, _clean, _get_teacher
# are already defined in teacher.py — do not re-import them here,
# just paste the route functions below into teacher.py.


# ─────────────────────────────────────────────────────────────────────────────
# EXAM PAPER GENERATION
# ─────────────────────────────────────────────────────────────────────────────

@teacher_bp.post("/exam/generate")
@teacher_required
def generate_exam_paper():
    """
    Upload a PDF → Groq analyzes → returns a unique 100-mark draft paper.

    multipart/form-data:
      - file       : PDF file
      - course_id  : course this exam belongs to

    Returns the draft paper_id. Teacher reviews it before publishing.
    """
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No PDF file uploaded. Field name must be 'file'"}), 400

    pdf_file  = request.files["file"]
    course_id = request.form.get("course_id", "").strip()

    if not course_id:
        return jsonify({"error": "course_id is required"}), 400

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    # Check teacher is assigned to this course
    if course_id not in teacher.get("teaches", []):
        return jsonify({"error": "You are not assigned to this course"}), 403

    # Fetch course name
    from db import get_courses
    course = get_courses().find_one({"course_id": course_id})
    if not course:
        return jsonify({"error": "Course not found"}), 404

    # Size guard (20 MB)
    pdf_bytes = pdf_file.read()
    if len(pdf_bytes) > 20 * 1024 * 1024:
        return jsonify({"error": "PDF too large. Maximum 20 MB."}), 413

    # Generate paper
    try:
        from services.pdf_exam_generator import generate_paper_from_pdf
        paper_doc = generate_paper_from_pdf(
            pdf_bytes   = pdf_bytes,
            course_name = course["name"],
            teacher_id  = teacher["teacher_id"],
            course_id   = course_id,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Paper generation failed: {e}"}), 500

    # Store in exam_papers collection
    from db import get_exam_papers
    get_exam_papers().insert_one(paper_doc)

    return jsonify({
        "message"         : "Exam paper generated successfully. Review and publish when ready.",
        "paper_id"        : paper_doc["paper_id"],
        "paper_title"     : paper_doc["paper_title"],
        "total_questions" : len(paper_doc["questions"]),
        "total_marks"     : paper_doc["total_marks"],
        "structure"       : paper_doc["structure"],
        "questions"       : paper_doc["questions"],   # so teacher can review in UI
    }), 201


@teacher_bp.get("/exam/papers")
@teacher_required
def list_draft_papers():
    """List all draft exam papers created by this teacher."""
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    from db import get_exam_papers
    papers = list(
        get_exam_papers()
        .find({"teacher_id": teacher["teacher_id"]},
              {"questions.ai_rubric": 0, "questions.model_answer": 0})  # hide answer keys
        .sort("created_at", -1)
        .limit(50)
    )
    return jsonify({
        "total"  : len(papers),
        "papers" : [_clean(p) for p in papers],
    }), 200


@teacher_bp.get("/exam/papers/<paper_id>")
@teacher_required
def get_draft_paper(paper_id):
    """View full draft paper (including questions with marks, no answer keys)."""
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    from db import get_exam_papers
    paper = get_exam_papers().find_one({
        "paper_id"   : paper_id,
        "teacher_id" : teacher["teacher_id"],   # teacher can only see own papers
    })
    if not paper:
        return jsonify({"error": "Draft paper not found"}), 404

    p = _clean(paper)
    # Strip answer keys from teacher view (admin sees them)
    for q in p.get("questions", []):
        q.pop("model_answer", None)
        q.pop("ai_rubric", None)

    return jsonify(p), 200


@teacher_bp.post("/exam/papers/<paper_id>/publish")
@teacher_required
def publish_paper(paper_id):
    """
    Publish a draft paper as a live exam.
    Body (optional): { "pass_marks": 40, "duration_minutes": 180 }
    Creates an entry in the exams collection and links paper → exam.
    """
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    from db import get_exam_papers, get_exams
    from models.schemas import build_exam

    paper = get_exam_papers().find_one({
        "paper_id"   : paper_id,
        "teacher_id" : teacher["teacher_id"],
    })
    if not paper:
        return jsonify({"error": "Draft paper not found"}), 404

    if paper.get("status") == "published":
        return jsonify({
            "error"   : "Paper already published",
            "exam_id" : paper.get("exam_id"),
        }), 409

    data         = request.get_json(silent=True) or {}
    pass_marks   = int(data.get("pass_marks",   paper["pass_marks"]))
    duration     = int(data.get("duration_minutes", paper["duration_minutes"]))

    # Build question list compatible with existing exam schema
    # (type field: short/long → written, preserving ai_rubric for grader)
    questions = []
    for i, q in enumerate(paper["questions"], 1):
        questions.append({
            "q_id"          : q.get("q_id", f"Q{str(i).zfill(3)}"),
            "type"          : "written",   # ai_grader uses "written" type
            "question"      : q["question"],
            "marks"         : q["marks"],
            "options"       : [],
            "correct_answer": None,
            "ai_rubric"     : q.get("ai_rubric", ""),
            "section"       : q.get("section", "A"),
            "sub_type"      : q.get("type", "short"),   # 'short' or 'long'
        })

    exam_doc = build_exam(
        course_id        = paper["course_id"],
        title            = paper["paper_title"],
        duration_minutes = duration,
        total_marks      = paper["total_marks"],
        pass_marks       = pass_marks,
        questions        = questions,
    )
    # Tag exam as AI-generated
    exam_doc["source"]     = "ai_generated"
    exam_doc["paper_id"]   = paper_id
    exam_doc["teacher_id"] = teacher["teacher_id"]
    exam_doc["instructions"] = paper.get("instructions", "Answer all questions.")

    get_exams().insert_one(exam_doc)

    # Mark paper as published
    get_exam_papers().update_one(
        {"paper_id": paper_id},
        {"$set": {
            "status"       : "published",
            "exam_id"      : exam_doc["exam_id"],
            "published_at" : datetime.utcnow(),
        }}
    )

    return jsonify({
        "message"          : "Exam published successfully.",
        "exam_id"          : exam_doc["exam_id"],
        "title"            : exam_doc["title"],
        "total_questions"  : len(questions),
        "total_marks"      : exam_doc["total_marks"],
        "pass_marks"       : pass_marks,
        "duration_minutes" : duration,
    }), 201


@teacher_bp.delete("/exam/papers/<paper_id>")
@teacher_required
def delete_draft_paper(paper_id):
    """Delete a draft paper (only if not yet published)."""
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    from db import get_exam_papers
    paper = get_exam_papers().find_one({
        "paper_id"   : paper_id,
        "teacher_id" : teacher["teacher_id"],
    })
    if not paper:
        return jsonify({"error": "Draft paper not found"}), 404

    if paper.get("status") == "published":
        return jsonify({
            "error": "Cannot delete a published paper. Ask admin to delete the exam."
        }), 400

    get_exam_papers().delete_one({"paper_id": paper_id})
    return jsonify({"message": "Draft paper deleted"}), 200


# ─────────────────────────────────────────────────────────────────────────────
# LIVE EXAM MANAGEMENT (teacher view)
# ─────────────────────────────────────────────────────────────────────────────

@teacher_bp.get("/exams")
@teacher_required
def my_exams():
    """List all live exams for courses this teacher teaches."""
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    course_ids = teacher.get("teaches", [])
    if not course_ids:
        return jsonify({"total": 0, "exams": []}), 200

    from db import get_exams, get_results
    exams = list(
        get_exams()
        .find({"course_id": {"$in": course_ids}},
              {"questions.correct_answer": 0, "questions.ai_rubric": 0})
        .sort("created_at", -1)
    )

    enriched = []
    for e in exams:
        e_clean = _clean(e)
        e_clean["result_count"] = get_results().count_documents(
            {"exam_id": e["exam_id"]}
        )
        e_clean["total_questions"] = len(e.get("questions", []))
        enriched.append(e_clean)

    return jsonify({"total": len(enriched), "exams": enriched}), 200


@teacher_bp.get("/exams/<exam_id>/results")
@teacher_required
def exam_results(exam_id):
    """
    View all results for a specific exam.
    Only returns results where the corresponding report is approved
    (so teacher can't see unapproved data).
    """
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    from db import get_exams, get_results, get_exam_reports, get_students
    exam = get_exams().find_one({"exam_id": exam_id})
    if not exam:
        return jsonify({"error": "Exam not found"}), 404

    # Verify teacher teaches this course
    if exam.get("course_id") not in teacher.get("teaches", []):
        return jsonify({"error": "Access denied — not your course"}), 403

    results = list(get_results().find(
        {"exam_id": exam_id},
        {"ai_evaluation": 0}
    ).sort("created_at", -1))

    enriched = []
    for r in results:
        # Check if report is approved
        report = get_exam_reports().find_one(
            {"result_id": r["result_id"], "status": "approved"},
            {"report_id": 1, "pdf_url": 1, "_id": 0}
        )
        student = get_students().find_one(
            {"student_id": r["student_id"]},
            {"name": 1, "student_id": 1, "_id": 0}
        )
        r_clean = _clean(r)
        r_clean["student_name"]   = student["name"] if student else "—"
        r_clean["report_approved"] = bool(report)
        r_clean["report_id"]      = report["report_id"] if report else None
        r_clean["report_pdf_url"] = report.get("pdf_url") if report else None
        enriched.append(r_clean)

    return jsonify({
        "exam_id"  : exam_id,
        "title"    : exam.get("title",""),
        "total"    : len(enriched),
        "results"  : enriched,
    }), 200


@teacher_bp.get("/results/<result_id>/report")
@teacher_required
def view_approved_report(result_id):
    """
    View the approved AI performance report for a result.
    Only returns reports where status == 'approved'.
    """
    teacher = _get_teacher()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    from db import get_results, get_exam_reports, get_exams
    result = get_results().find_one({"result_id": result_id})
    if not result:
        return jsonify({"error": "Result not found"}), 404

    # Verify this result belongs to a course the teacher teaches
    exam = get_exams().find_one({"exam_id": result["exam_id"]})
    if exam and exam.get("course_id") not in teacher.get("teaches", []):
        return jsonify({"error": "Access denied — not your course"}), 403

    report = get_exam_reports().find_one({
        "result_id": result_id,
        "status"   : "approved",
    })
    if not report:
        return jsonify({
            "error": "Report not yet approved by admin or not generated yet."
        }), 404

    return jsonify(_clean(report)), 200

=======
    return jsonify({"message": "Password changed successfully"}), 200
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c
