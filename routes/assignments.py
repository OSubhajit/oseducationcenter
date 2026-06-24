"""
routes/assignments.py — Assignment and submission management endpoints
"""
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from db import get_students
from services.assignment_service import (
    create_assignment,
    get_assignment,
    update_assignment,
    delete_assignment,
    list_assignments,
    submit_submission,
    get_submission,
    grade_submission,
    get_submissions_for_assignment,
    get_student_submissions
)
from services.storage_service import upload_file
from routes.admin import admin_required
from routes.student import student_required
from routes.auth import teacher_or_admin_required, is_teacher_authorized_for_course, get_actor_id
from services.file_validator import validate_upload
from services.email_service import send_grade_posted
from db import get_students as _get_students_col, get_courses as _get_courses_col
from werkzeug.utils import secure_filename
from validators import validate_osec_id, validate_lengths

assignments_bp = Blueprint("assignments", __name__, url_prefix="/api/assignments")


# ─── Assignment CRUD (Admin / Teacher) ──────────────────────────────────────

@assignments_bp.post("/")
@teacher_or_admin_required
def create_assignment_endpoint():
    """Create a new assignment."""
    data   = request.get_json(silent=True) or {}
    claims = get_jwt()

    err = validate_lengths(data)
    if err:
        return err
    if "course_id" in data:
        err = validate_osec_id(data["course_id"], "course_id")
        if err:
            return err
    if data.get("batch_id"):
        err = validate_osec_id(data["batch_id"], "batch_id")
        if err:
            return err

    # Inject creator identity before validation.
    # Use the OSEC teacher_id (or "admin"), NOT get_jwt_identity() — the latter
    # is the MongoDB _id and won't match teacher_id in dashboard queries.
    data["created_by"] = get_actor_id()

    if claims.get("role") == "teacher":
        course_id = data.get("course_id")
        if not course_id:
            return jsonify({"error": "course_id is required for teacher-created assignments"}), 400
        if not is_teacher_authorized_for_course(course_id):
            return jsonify({"error": "Not authorized to create assignments for this course"}), 403

    try:
        assignment = create_assignment(data)
        return jsonify({
            "message": "Assignment created successfully",
            "assignment": assignment
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Unexpected error creating assignment: {e}")
        return jsonify({"error": "Internal server error"}), 500


@assignments_bp.get("/")
@teacher_or_admin_required
def list_assignments_endpoint():
    """List assignments with filtering, search, and pagination."""
    try:
        page     = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        search   = request.args.get("search", "").strip()

        filters = {}
        for param in ["course_id", "batch_id"]:
            value = request.args.get(param)
            if value is not None:
                filters[param] = value

        # Teachers may only see assignments for their own courses
        claims = get_jwt()
        if claims.get("role") == "teacher":
            teaches = claims.get("teaches", [])
            if "course_id" in filters:
                if not is_teacher_authorized_for_course(filters["course_id"]):
                    return jsonify({"error": "Not authorized to view assignments for this course"}), 403
            else:
                if not teaches:
                    return jsonify({"assignments": [], "pagination": {
                        "page": page, "per_page": per_page, "total": 0, "pages": 0
                    }}), 200
                filters["course_id"] = {"$in": teaches}

        assignments, total = list_assignments(
            filters=filters if filters else None,
            page=page,
            per_page=per_page,
            search=search if search else None,
            sort_by=request.args.get("sort_by", "created_at"),
            sort_order=1 if request.args.get("sort_order", "desc").lower() == "asc" else -1
        )

        return jsonify({
            "assignments": assignments,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page
            }
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error listing assignments: {e}")
        return jsonify({"error": "Internal server error"}), 500


@assignments_bp.get("/<assignment_id>")
@teacher_or_admin_required
def get_assignment_endpoint(assignment_id):
    """Get a single assignment by assignment_id."""
    err = validate_osec_id(assignment_id, "assignment_id")
    if err:
        return err
    assignment = get_assignment(assignment_id)
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    claims = get_jwt()
    if claims.get("role") == "teacher":
        if not is_teacher_authorized_for_course(assignment.get("course_id")):
            return jsonify({"error": "Not authorized to view this assignment"}), 403

    return jsonify({"assignment": assignment}), 200


@assignments_bp.put("/<assignment_id>")
@admin_required
def update_assignment_endpoint(assignment_id):
    """Update an assignment (admin only)."""
    err = validate_osec_id(assignment_id, "assignment_id")
    if err:
        return err

    data = request.get_json(silent=True) or {}
    err = validate_lengths(data)
    if err:
        return err
    if data.get("batch_id"):
        err = validate_osec_id(data["batch_id"], "batch_id")
        if err:
            return err
    try:
        updated = update_assignment(assignment_id, data)
        if not updated:
            return jsonify({"error": "Assignment not found"}), 404
        return jsonify({
            "message": "Assignment updated successfully",
            "assignment": updated
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating assignment {assignment_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


@assignments_bp.delete("/<assignment_id>")
@teacher_or_admin_required
def delete_assignment_endpoint(assignment_id):
    """Delete an assignment (soft delete)."""
    err = validate_osec_id(assignment_id, "assignment_id")
    if err:
        return err
    try:
        existing = get_assignment(assignment_id)
        if not existing:
            return jsonify({"error": "Assignment not found"}), 404

        claims = get_jwt()
        if claims.get("role") == "teacher":
            if not is_teacher_authorized_for_course(existing.get("course_id")):
                return jsonify({"error": "Not authorized to delete this assignment"}), 403

        deleted = delete_assignment(assignment_id)
        if not deleted:
            return jsonify({"error": "Assignment not found"}), 404
        return jsonify({"message": "Assignment deleted successfully"}), 200
    except Exception as e:
        current_app.logger.error(f"Error deleting assignment {assignment_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ─── Submission endpoints (Student) ─────────────────────────────────────────

@assignments_bp.post("/<assignment_id>/submit")
@student_required
def submit_assignment_endpoint(assignment_id):
    """Submit an assignment (file or text)."""
    err = validate_osec_id(assignment_id, "assignment_id")
    if err:
        return err
    # Use the OSEC student_id from JWT claims, NOT get_jwt_identity() which is MongoDB _id
    student_id = get_jwt().get("student_id")

    file_url     = None
    text_content = None

    if request.content_type and request.content_type.startswith("multipart/form-data"):
        if "file" not in request.files:
            return jsonify({"error": "No file part in the request"}), 400
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400
        filename = secure_filename(file.filename)  # noqa: F841 — kept for logging if needed

        # ── File validation (extension allowlist + MIME + size) ─────
        # Determine expected resource type from the assignment
        _assignment_obj = get_assignment(assignment_id)
        _expected_rtype = "document"  # default; submissions are usually docs/pdfs
        validation_error = validate_upload(file, resource_type=_expected_rtype)
        if validation_error:
            return jsonify({"error": validation_error}), 400

        upload_result = upload_file(file, folder="assignments")
        if upload_result["success"]:
            file_url = upload_result["url"]
        else:
            return jsonify({"error": f"File upload failed: {upload_result.get('error')}"}), 500
        text_content = request.form.get("text_content")
    else:
        data         = request.get_json(silent=True) or {}
        text_content = data.get("text_content")
        file_url     = data.get("file_url")
        err = validate_lengths(
            {"text_content": text_content, "file_url": file_url},
            limits={"text_content": 50000, "file_url": 2000}
        )
        if err:
            return err

    submission_data = {}
    if file_url:
        submission_data["file_url"] = file_url
    if text_content:
        submission_data["text_content"] = text_content

    try:
        submission = submit_submission(assignment_id, student_id, submission_data)
        return jsonify({
            "message": "Assignment submitted successfully",
            "submission": submission
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error submitting assignment: {e}")
        return jsonify({"error": "Internal server error"}), 500


@assignments_bp.get("/<assignment_id>/submissions")
@teacher_or_admin_required
def list_assignment_submissions_endpoint(assignment_id):
    """List submissions for an assignment (admin/teacher)."""
    err = validate_osec_id(assignment_id, "assignment_id")
    if err:
        return err
    try:
        assignment = get_assignment(assignment_id)
        if not assignment:
            return jsonify({"error": "Assignment not found"}), 404

        claims = get_jwt()
        if claims.get("role") == "teacher":
            if not is_teacher_authorized_for_course(assignment.get("course_id")):
                return jsonify({"error": "Not authorized to view submissions for this assignment"}), 403

        page     = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        filters  = {}
        for param in ["student_id", "status"]:
            value = request.args.get(param)
            if value is not None:
                filters[param] = value

        submissions, total = get_submissions_for_assignment(
            assignment_id,
            page=page,
            per_page=per_page,
            filters=filters if filters else None
        )

        return jsonify({
            "submissions": submissions,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page
            }
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error listing submissions for assignment {assignment_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


@assignments_bp.get("/submissions/<submission_id>")
@teacher_or_admin_required
def get_submission_endpoint(submission_id):
    """Get a specific submission (admin/teacher)."""
    err = validate_osec_id(submission_id, "submission_id")
    if err:
        return err
    submission = get_submission(submission_id)
    if not submission:
        return jsonify({"error": "Submission not found"}), 404

    assignment = get_assignment(submission.get("assignment_id"))
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    claims = get_jwt()
    if claims.get("role") == "teacher":
        if not is_teacher_authorized_for_course(assignment.get("course_id")):
            return jsonify({"error": "Not authorized to view this submission"}), 403

    return jsonify({"submission": submission}), 200


@assignments_bp.put("/submissions/<submission_id>/grade")
@teacher_or_admin_required
def grade_submission_endpoint(submission_id):
    """Grade a submission (admin/teacher)."""
    err = validate_osec_id(submission_id, "submission_id")
    if err:
        return err

    data      = request.get_json(silent=True) or {}
    score     = data.get("score")
    feedback  = data.get("feedback")
    graded_by = get_actor_id()

    err = validate_lengths({"feedback": feedback})
    if err:
        return err

    try:
        submission_doc = get_submission(submission_id)
        if not submission_doc:
            return jsonify({"error": "Submission not found"}), 404

        assignment = get_assignment(submission_doc.get("assignment_id"))
        if not assignment:
            return jsonify({"error": "Assignment not found"}), 404

        claims = get_jwt()
        if claims.get("role") == "teacher":
            if not is_teacher_authorized_for_course(assignment.get("course_id")):
                return jsonify({"error": "Not authorized to grade this submission"}), 403

        submission = grade_submission(submission_id, score, feedback, graded_by)

        # ── Email notification (best-effort — don't fail the grade if email fails) ──
        try:
            student = _get_students_col().find_one({"student_id": submission_doc.get("student_id")})
            course  = _get_courses_col().find_one({"course_id": assignment.get("course_id")})
            if student and student.get("email"):
                send_grade_posted(
                    student_email=student["email"],
                    student_name=student.get("name", "Student"),
                    assignment=assignment,
                    submission=submission,
                    course_name=course.get("name", assignment.get("course_id")) if course else assignment.get("course_id"),
                )
        except Exception as _email_err:
            current_app.logger.warning("Grade notification email failed: %s", _email_err)

        return jsonify({
            "message": "Submission graded successfully",
            "submission": submission
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error grading submission {submission_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


@assignments_bp.get("/my/submissions")
@student_required
def my_submissions_endpoint():
    """Get current student's submissions."""
    # Use OSEC student_id from claims, not get_jwt_identity() (MongoDB _id)
    student_id = get_jwt().get("student_id")

    try:
        page     = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        filters  = {}
        for param in ["assignment_id", "status"]:
            value = request.args.get(param)
            if value is not None:
                filters[param] = value

        submissions, total = get_student_submissions(
            student_id,
            page=page,
            per_page=per_page,
            filters=filters if filters else None
        )

        return jsonify({
            "submissions": submissions,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page
            }
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error listing submissions for student {student_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


@assignments_bp.get("/<assignment_id>/student")
@student_required
def get_assignment_for_student_endpoint(assignment_id):
    """Get assignment details visible to student."""
    err = validate_osec_id(assignment_id, "assignment_id")
    if err:
        return err
    # Use OSEC student_id from claims, not get_jwt_identity() (MongoDB _id)
    student_id = get_jwt().get("student_id")

    assignment = get_assignment(assignment_id)
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    student = get_students().find_one({"student_id": student_id})
    if not student or assignment["course_id"] not in student.get("enrolled_courses", []):
        return jsonify({"error": "You are not enrolled in the course for this assignment"}), 403

    return jsonify({"assignment": assignment}), 200
