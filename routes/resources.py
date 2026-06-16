"""
routes/resources.py — Resource/Learning material management endpoints
"""
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt
from db import get_students
from services.resource_service import (
    create_resource,
    get_resource,
    update_resource,
    delete_resource,
    list_resources,
    increment_view_count,
    create_resource_from_upload
)
from routes.admin import admin_required
from routes.student import student_required
from routes.auth import teacher_or_admin_required, is_teacher_authorized_for_course, get_actor_id
from services.file_validator import validate_upload
from validators import validate_osec_id, validate_lengths

resources_bp = Blueprint("resources", __name__, url_prefix="/api/resources")

# Helper to check if user is student or teacher/admin
def get_current_user_role():
    from flask_jwt_extended import get_jwt
    claims = get_jwt()
    return claims.get("role")  # admin, student, or later teacher

# ----------------- Resource CRUD (Admin/Teacher) -----------------

@resources_bp.post("/")
@teacher_or_admin_required
def create_resource_endpoint():
    """Create a new resource (metadata only; for uploads use /upload)."""
    data = request.get_json(silent=True) or {}

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

    # Always set uploaded_by server-side from the JWT (OSEC teacher_id/"admin"),
    # never trust a client-supplied value — and this must match what
    # routes/teacher.py's dashboard queries filter on.
    data["uploaded_by"] = get_actor_id()
    try:
        # Check if teacher is authorized for the course
        claims = get_jwt()
        if claims.get("role") == "teacher":
            course_id = data.get("course_id")
            if not course_id:
                return jsonify({"error": "course_id is required for teacher-created resources"}), 400
            if not is_teacher_authorized_for_course(course_id):
                return jsonify({"error": "Not authorized to create resources for this course"}), 403

        resource = create_resource(data)
        return jsonify({
            "message": "Resource created successfully",
            "resource": resource
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Unexpected error creating resource: {e}")
        return jsonify({"error": "Internal server error"}), 500


@resources_bp.post("/upload")
@teacher_or_admin_required
def upload_resource_endpoint():
    """Upload a file and create a resource record."""
    # Expect multipart/form-data with:
    # - file: the file to upload
    # - title, description, resource_type, course_id, batch_id (optional),
    #   category, tags (comma-separated string), uploaded_by (from JWT)
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # Get metadata from form
    title = request.form.get('title')
    description = request.form.get('description')
    resource_type = request.form.get('resource_type')
    course_id = request.form.get('course_id')
    batch_id = request.form.get('batch_id') or None
    category = request.form.get('category', '')
    tags_str = request.form.get('tags', '')
    tags = [t.strip() for t in tags_str.split(',') if t.strip()] if tags_str else []
    # uploaded_by: OSEC teacher_id (or "admin") — must match teacher.py
    # dashboard's {"uploaded_by": teacher_id} queries. get_jwt_identity()
    # returns the MongoDB _id and would never match.
    uploaded_by = get_actor_id()

    # Basic validation
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if not description:
        return jsonify({"error": "Description is required"}), 400
    if not resource_type:
        return jsonify({"error": "Resource type is required"}), 400
    valid_types = ["document", "video", "link", "audio", "image", "other"]
    if resource_type not in valid_types:
        return jsonify({"error": f"Resource type must be one of {valid_types}"}), 400
    if not course_id:
        return jsonify({"error": "Course ID is required"}), 400

    err = validate_osec_id(course_id, "course_id")
    if err:
        return err
    if batch_id:
        err = validate_osec_id(batch_id, "batch_id")
        if err:
            return err
    err = validate_lengths({
        "title": title, "description": description,
        "category": category, "tags": tags,
    })
    if err:
        return err
    # Note: batch_id optional
    # For link type, we expect external_url instead of file; but this endpoint is for file uploads.
    if resource_type == "link":
        return jsonify({"error": "Use standard creation endpoint for link resources (provide external_url)"}), 400

    # Check if teacher is authorized for the course
    claims = get_jwt()
    if claims.get("role") == "teacher":
        if not is_teacher_authorized_for_course(course_id):
            return jsonify({"error": "Not authorized to upload resources for this course"}), 403

    # ── File validation (extension allowlist + MIME + size) ─────────
    validation_error = validate_upload(file, resource_type=resource_type)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    try:
        resource = create_resource_from_upload(
            title=title,
            description=description,
            resource_type=resource_type,
            course_id=course_id,
            batch_id=batch_id,
            file_storage=file,
            uploaded_by=uploaded_by,
            category=category,
            tags=tags
        )
        return jsonify({
            "message": "Resource uploaded and created successfully",
            "resource": resource
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error uploading resource: {e}")
        return jsonify({"error": "Internal server error"}), 500


@resources_bp.get("/")
@teacher_or_admin_required
def list_resources_endpoint():
    """List resources with filtering, search, and pagination."""
    try:
        page     = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        search   = request.args.get("search", "").strip()

        filters = {}
        for param in ["course_id", "batch_id", "resource_type", "category"]:
            value = request.args.get(param)
            if value is not None:
                filters[param] = value
        tags_param = request.args.get("tags")
        if tags_param:
            tags = [t.strip() for t in tags_param.split(",") if t.strip()]
            if tags:
                filters["tags"] = tags

        # Teachers may only see resources for their own courses
        claims = get_jwt()
        if claims.get("role") == "teacher":
            teaches = claims.get("teaches", [])
            if "course_id" in filters:
                # honour the requested filter but validate they're authorised
                if not is_teacher_authorized_for_course(filters["course_id"]):
                    return jsonify({"error": "Not authorized to view resources for this course"}), 403
            else:
                # No filter supplied — limit to their own courses
                if not teaches:
                    return jsonify({"resources": [], "pagination": {
                        "page": page, "per_page": per_page, "total": 0, "pages": 0
                    }}), 200
                filters["course_id"] = {"$in": teaches}

        resources, total = list_resources(
            filters=filters if filters else None,
            page=page,
            per_page=per_page,
            search=search if search else None,
            sort_by=request.args.get("sort_by", "created_at"),
            sort_order=1 if request.args.get("sort_order", "desc").lower() == "asc" else -1
        )

        return jsonify({
            "resources": resources,
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
        current_app.logger.error(f"Error listing resources: {e}")
        return jsonify({"error": "Internal server error"}), 500


@resources_bp.get("/<resource_id>")
@teacher_or_admin_required
def get_resource_endpoint(resource_id):
    """Get a single resource by resource_id."""
    err = validate_osec_id(resource_id, "resource_id")
    if err:
        return err
    resource = get_resource(resource_id)
    if not resource:
        return jsonify({"error": "Resource not found"}), 404

    # Check if teacher is authorized for this resource's course
    claims = get_jwt()
    if claims.get("role") == "teacher":
        course_id = resource.get("course_id")
        if not is_teacher_authorized_for_course(course_id):
            return jsonify({"error": "Not authorized to view this resource"}), 403

    return jsonify({"resource": resource}), 200


@resources_bp.put("/<resource_id>")
@teacher_or_admin_required
def update_resource_endpoint(resource_id):
    """Update a resource."""
    err = validate_osec_id(resource_id, "resource_id")
    if err:
        return err

    data = request.get_json(silent=True) or {}
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
    try:
        # Get existing resource to check course authorization
        existing_resource = get_resource(resource_id)
        if not existing_resource:
            return jsonify({"error": "Resource not found"}), 404

        # Check if teacher is authorized for this resource's course
        claims = get_jwt()
        if claims.get("role") == "teacher":
            course_id = existing_resource.get("course_id")
            if not is_teacher_authorized_for_course(course_id):
                return jsonify({"error": "Not authorized to update this resource"}), 403

            # If trying to change course_id, check authorization for new course
            if "course_id" in data and data["course_id"] != course_id:
                if not is_teacher_authorized_for_course(data["course_id"]):
                    return jsonify({"error": "Not authorized to move resource to this course"}), 403

        updated = update_resource(resource_id, data)
        if not updated:
            return jsonify({"error": "Resource not found"}), 404
        return jsonify({
            "message": "Resource updated successfully",
            "resource": updated
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating resource {resource_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


@resources_bp.delete("/<resource_id>")
@teacher_or_admin_required
def delete_resource_endpoint(resource_id):
    """Delete a resource (soft delete)."""
    err = validate_osec_id(resource_id, "resource_id")
    if err:
        return err
    try:
        # Get existing resource to check course authorization
        existing_resource = get_resource(resource_id)
        if not existing_resource:
            return jsonify({"error": "Resource not found"}), 404

        # Check if teacher is authorized for this resource's course
        claims = get_jwt()
        if claims.get("role") == "teacher":
            course_id = existing_resource.get("course_id")
            if not is_teacher_authorized_for_course(course_id):
                return jsonify({"error": "Not authorized to delete this resource"}), 403

        deleted = delete_resource(resource_id)
        if not deleted:
            return jsonify({"error": "Resource not found"}), 404
        return jsonify({"message": "Resource deleted successfully"}), 200
    except Exception as e:
        current_app.logger.error(f"Error deleting resource {resource_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ----------------- Student-Facing Endpoints -----------------

@resources_bp.get("/<resource_id>/student")
@student_required
def get_resource_for_student_endpoint(resource_id):
    """Get resource details visible to student (with access control)."""
    err = validate_osec_id(resource_id, "resource_id")
    if err:
        return err
    # get_jwt().get("student_id") is the OSEC ID; get_jwt_identity() is the MongoDB _id
    student_id = get_jwt().get("student_id")

    resource = get_resource(resource_id)
    if not resource:
        return jsonify({"error": "Resource not found"}), 404

    student = get_students().find_one({"student_id": student_id})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    if resource["course_id"] not in student.get("enrolled_courses", []):
        return jsonify({"error": "You are not enrolled in the course for this resource"}), 403

    # Batch-restricted resource: check the student's batch enrollments
    if resource.get("batch_id"):
        enrolled_batches = student.get("enrolled_batches", [])
        if resource["batch_id"] not in enrolled_batches:
            return jsonify({"error": "You are not enrolled in the batch for this resource"}), 403

    increment_view_count(resource_id)
    return jsonify({"resource": resource}), 200


@resources_bp.get("/<resource_id>/download")
@student_required
def download_resource_endpoint(resource_id):
    """Redirect to file URL for download (or serve as attachment)."""
    err = validate_osec_id(resource_id, "resource_id")
    if err:
        return err
    student_id = get_jwt().get("student_id")

    resource = get_resource(resource_id)
    if not resource:
        return jsonify({"error": "Resource not found"}), 404

    student = get_students().find_one({"student_id": student_id})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    if resource["course_id"] not in student.get("enrolled_courses", []):
        return jsonify({"error": "You are not enrolled in the course for this resource"}), 403
    if resource.get("batch_id"):
        enrolled_batches = student.get("enrolled_batches", [])
        if resource["batch_id"] not in enrolled_batches:
            return jsonify({"error": "You are not enrolled in the batch for this resource"}), 403

    return jsonify({
        "download_url": resource.get("file_url"),
        "resource_id": resource_id
    }), 200


@resources_bp.get("/<resource_id>/stream")
@student_required
def stream_resource_endpoint(resource_id):
    """Get streaming URL for video/audio resources."""
    err = validate_osec_id(resource_id, "resource_id")
    if err:
        return err
    student_id = get_jwt().get("student_id")

    resource = get_resource(resource_id)
    if not resource:
        return jsonify({"error": "Resource not found"}), 404

    student = get_students().find_one({"student_id": student_id})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    if resource["course_id"] not in student.get("enrolled_courses", []):
        return jsonify({"error": "You are not enrolled in the course for this resource"}), 403
    if resource.get("batch_id"):
        enrolled_batches = student.get("enrolled_batches", [])
        if resource["batch_id"] not in enrolled_batches:
            return jsonify({"error": "You are not enrolled in the batch for this resource"}), 403

    if resource["resource_type"] not in ["video", "audio"]:
        return jsonify({"error": "Streaming not supported for this resource type"}), 400

    return jsonify({
        "stream_url": resource.get("file_url"),
        "resource_id": resource_id
    }), 200


# Optional: Get resources for a course/batch for student
@resources_bp.get("/course/<course_id>")
@student_required
def get_resources_for_course_endpoint(course_id):
    """List resources for a specific course (student view)."""
    err = validate_osec_id(course_id, "course_id")
    if err:
        return err

    # Use OSEC student_id from JWT claims — get_jwt_identity() returns MongoDB _id
    student_id = get_jwt().get("student_id")
    student = get_students().find_one({"student_id": student_id})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    if course_id not in student.get("enrolled_courses", []):
        return jsonify({"error": "You are not enrolled in this course"}), 403

    # Optional batch filter
    batch_id = request.args.get("batch_id")
    filters = {"course_id": course_id}
    if batch_id:
        err = validate_osec_id(batch_id, "batch_id")
        if err:
            return err
        filters["batch_id"] = batch_id

    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        resources, total = list_resources(
            filters=filters,
            page=page,
            per_page=per_page,
            sort_by="created_at",
            sort_order=-1
        )
        return jsonify({
            "resources": resources,
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
        current_app.logger.error(f"Error listing resources for course {course_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500