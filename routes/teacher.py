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
    return jsonify({"message": "Password changed successfully"}), 200