"""
routes/admin.py
---------------
All admin-only endpoints. Every route requires a valid JWT with role=admin.

STUDENTS
  POST   /admin/students                  — enrol new student
  GET    /admin/students                  — list all students
  GET    /admin/students/<student_id>     — get one student
  PUT    /admin/students/<student_id>     — update student info
  DELETE /admin/students/<student_id>     — deactivate student

COURSES
  GET    /admin/courses                   — list all 46 courses
  POST   /admin/courses                   — create course
  PUT    /admin/courses/<course_id>       — update fee / duration / active
  DELETE /admin/courses/<course_id>       — hard delete (blocked if active batches)

BATCHES
  POST   /admin/batches                   — create batch
  GET    /admin/batches                   — list all batches
  GET    /admin/batches/<batch_id>        — get one batch + enrolled students
  POST   /admin/batches/<batch_id>/enrol  — add student to batch
  DELETE /admin/batches/<batch_id>/enrol  — remove student from batch
  DELETE /admin/batches/<batch_id>        — delete batch (blocked if students enrolled)

FEES
  POST   /admin/fees                      — create fee record
  GET    /admin/fees/<student_id>         — get all fees for a student
  POST   /admin/fees/<fee_id>/pay         — record a payment
  GET    /admin/fees/due                  — list all students with dues

EXAMS
  POST   /admin/exams                     — create exam + questions
  GET    /admin/exams                     — list all exams
  GET    /admin/exams/<exam_id>           — get exam with all questions
  DELETE /admin/exams/<exam_id>           — delete exam (only if no results)

RESULTS  (admin view)
  GET    /admin/results                   — list all results
  GET    /admin/results/<result_id>       — get one result in full
  DELETE /admin/results/<result_id>       — hard delete (admin only)

DASHBOARD
  GET    /admin/dashboard                 — summary counts
"""
from datetime import datetime
from functools import wraps
import bcrypt

from bson import ObjectId
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from db import (get_students, get_courses, get_batches,
                get_fees, get_exams, get_results, get_teachers)
from models.schemas import (build_student, build_batch,
                             build_fee, build_exam, build_teacher, build_course)
from services.question_service import get_question
from validators import validate_osec_id, validate_osec_ids, validate_lengths, validate_password, safe_str
# NOTE: face_recognition and video_handler are imported lazily inside the
# functions that use them. Importing them at module level causes blueprint
# registration to fail when deepface / cloudinary aren't installed yet,
# which makes ALL routes (including /auth/login) return 404.

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ═══════════════════════════════════════════════════════════════════
# DECORATOR — admin only
# ═══════════════════════════════════════════════════════════════════

def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _clean(doc: dict) -> dict:
    """Convert ObjectId fields to strings for JSON serialisation."""
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


def _missing(*fields, data: dict):
    return [f for f in fields if not data.get(f)]


# ID-format and string-length validation now live in validators.py (shared
# across blueprints). Keep _validate_osec_id as a thin alias so existing
# call sites in this file don't need to change.
_validate_osec_id = validate_osec_id


# ═══════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════

@admin_bp.get("/dashboard")
@admin_required
def dashboard():
    total_students  = get_students().count_documents({"active": True})
    total_batches   = get_batches().count_documents({"active": True})
    total_results   = get_results().count_documents({})
    dues_pipeline   = [
        {"$match": {"status": {"$ne": "paid"}}},
        {"$group": {"_id": None, "total_due": {"$sum": "$due_amount"}}}
    ]
    dues_result = list(get_fees().aggregate(dues_pipeline))
    total_dues  = dues_result[0]["total_due"] if dues_result else 0

    return jsonify({
        "total_students" : total_students,
        "total_batches"  : total_batches,
        "total_results"  : total_results,
        "total_dues_inr" : total_dues,
    }), 200


# ═══════════════════════════════════════════════════════════════════
# STUDENTS
# ═══════════════════════════════════════════════════════════════════

@admin_bp.post("/students")
@admin_required
def enrol_student():
    data = request.get_json(silent=True) or {}

    required = ["name","email","phone","dob","gender",
                "address","guardian_name","guardian_phone","password"]
    missing  = _missing(*required, data=data)
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    err = validate_lengths(data)
    if err:
        return err

    err = validate_password(data)
    if err:
        return err

    # duplicate check
    if get_students().find_one({"email": data["email"]}):
        return jsonify({"error": "Email already registered"}), 409

    student_doc = build_student(
        name           = data["name"],
        email          = data["email"],
        phone          = data["phone"],
        dob            = data["dob"],
        gender         = data["gender"],
        address        = data["address"],
        guardian_name  = data["guardian_name"],
        guardian_phone = data["guardian_phone"],
        plain_password = data["password"],
        photo_url      = "",
    )

    # optional: photo + face registration in one step
    if data.get("photo_b64"):
        from services.video_handler import upload_student_photo
        from services.face_recognition import register_face
        # upload photo to cloudinary
        photo_result = upload_student_photo(
            data["photo_b64"], student_doc["student_id"]
        )
        if photo_result["success"]:
            student_doc["photo_url"] = photo_result["url"]

        # register face encoding
        face_result = register_face(data["photo_b64"])
        if face_result["success"]:
            student_doc["face_encoding"] = face_result["encoding"]

    result = get_students().insert_one(student_doc)
    return jsonify({
        "message"    : "Student enrolled successfully",
        "student_id" : student_doc["student_id"],
        "_id"        : str(result.inserted_id),
    }), 201


@admin_bp.get("/students")
@admin_required
def list_students():
    page            = int(request.args.get("page", 1))
    per_page        = int(request.args.get("per_page", 20))
    search          = request.args.get("search", "").strip()
    include_inactive = request.args.get("include_inactive", "false").lower() == "true"

    query = {} if include_inactive else {"active": True}
    if search:
        query["$or"] = [
            {"name"      : {"$regex": search, "$options": "i"}},
            {"student_id": {"$regex": search, "$options": "i"}},
            {"phone"     : {"$regex": search, "$options": "i"}},
        ]

    total    = get_students().count_documents(query)
    students = list(
        get_students()
        .find(query, {"password_hash": 0, "face_encoding": 0})
        .skip((page - 1) * per_page)
        .limit(per_page)
        .sort("created_at", -1)
    )

    return jsonify({
        "total"    : total,
        "page"     : page,
        "per_page" : per_page,
        "students" : [_clean(s) for s in students],
    }), 200


@admin_bp.get("/students/<student_id>")
@admin_required
def get_student(student_id):
    student = get_students().find_one(
        {"student_id": student_id},
        {"password_hash": 0, "face_encoding": 0}
    )
    if not student:
        return jsonify({"error": "Student not found"}), 404
    return jsonify(_clean(student)), 200


@admin_bp.put("/students/<student_id>")
@admin_required
def update_student(student_id):
    data = request.get_json(silent=True) or {}

    allowed = [
        "name",
        "phone",
        "address",
        "guardian_name",
        "guardian_phone",
        "active"
    ]

    updates = {k: v for k, v in data.items() if k in allowed}

    err = validate_lengths(updates)
    if err:
        return err

    # handle face registration
    if data.get("photo_b64"):
        from services.face_recognition import register_face
        face_result = register_face(data["photo_b64"])

        if not face_result["success"]:
            return jsonify({
                "error": face_result["message"]
            }), 400

        updates["face_encoding"] = face_result["encoding"]

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    updates["updated_at"] = datetime.utcnow()

    get_students().update_one(
        {"student_id": student_id},
        {"$set": updates}
    )

    return jsonify({
        "message": "Student updated successfully"
    }), 200


@admin_bp.delete("/students/<student_id>")
@admin_required
def deactivate_student(student_id):
    result = get_students().update_one(
        {"student_id": student_id},
        {"$set": {"active": False, "deactivated_at": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        return jsonify({"error": "Student not found"}), 404
    return jsonify({"message": "Student deactivated"}), 200


# ═══════════════════════════════════════════════════════════════════
# COURSES
# ═══════════════════════════════════════════════════════════════════

@admin_bp.get("/courses")
@admin_required
def list_courses():
    search   = request.args.get("search", "").strip()
    page     = max(int(request.args.get("page", 1) or 1), 1)
    per_page = max(int(request.args.get("per_page", 20) or 20), 1)

    query = {}
    if search:
        query["$or"] = [
            {"name":     {"$regex": search, "$options": "i"}},
            {"category": {"$regex": search, "$options": "i"}},
            {"course_id": {"$regex": search, "$options": "i"}},
        ]

    total   = get_courses().count_documents(query)
    courses = list(
        get_courses().find(query)
        .sort("course_id", 1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return jsonify({
        "total"     : total,
        "courses"   : [_clean(c) for c in courses],
        "pagination": {
            "page": page, "per_page": per_page, "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }), 200


@admin_bp.post("/courses")
@admin_required
def create_course():
    data    = request.get_json(silent=True) or {}
    missing = _missing("name", "category", "duration_weeks", data=data)
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    err = validate_lengths(data)
    if err:
        return err

    if get_courses().find_one({"name": data["name"], "category": data["category"]}):
        return jsonify({"error": "A course with this name already exists in this category"}), 409

    try:
        course = build_course(
            name=data["name"],
            category=data["category"],
            duration_weeks=data["duration_weeks"],
            fee=data.get("fee", 0),
            max_students=data.get("max_students", 30),
            description=data.get("description", ""),
            active=data.get("active", True),
        )
    except (ValueError, TypeError):
        return jsonify({"error": "duration_weeks, fee and max_students must be numbers"}), 400

    get_courses().insert_one(course)
    return jsonify({"message": "Course created", "course": _clean(course)}), 201


@admin_bp.put("/courses/<course_id>")
@admin_required
def update_course(course_id):
    err = validate_osec_id(course_id, "course_id")
    if err:
        return err

    data    = request.get_json(silent=True) or {}
    allowed = ["name", "category", "fee", "duration_weeks", "max_students", "description", "active"]
    updates = {k: v for k, v in data.items() if k in allowed}

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    err = validate_lengths(updates)
    if err:
        return err

    result = get_courses().update_one({"course_id": course_id}, {"$set": updates})
    if result.matched_count == 0:
        return jsonify({"error": "Course not found"}), 404
    return jsonify({"message": "Course updated"}), 200

@admin_bp.delete("/courses/<course_id>")
@admin_required
def delete_course(course_id):
    """Hard delete a course — blocked if active batches exist."""
    err = _validate_osec_id(course_id, "course_id")
    if err:
        return err
    if get_batches().find_one({"course_id": course_id, "active": True}):
        return jsonify({"error": "Cannot delete course — active batches exist. Deactivate all batches first."}), 400
    result = get_courses().delete_one({"course_id": course_id})
    if result.deleted_count == 0:
        return jsonify({"error": "Course not found"}), 404
    return jsonify({"message": "Course deleted"}), 200



# ═══════════════════════════════════════════════════════════════════
# BATCHES
# ═══════════════════════════════════════════════════════════════════

@admin_bp.post("/batches")
@admin_required
def create_batch():
    data    = request.get_json(silent=True) or {}
    missing = _missing("name", "course_id", "start_date", "end_date", "schedule", data=data)
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    err = validate_lengths(data)
    if err:
        return err

    err = validate_osec_id(data["course_id"], "course_id")
    if err:
        return err

    # verify course exists
    if not get_courses().find_one({"course_id": data["course_id"]}):
        return jsonify({"error": "Course not found"}), 404

    try:
        max_students = int(data.get("max_students", 20))
    except (ValueError, TypeError):
        return jsonify({"error": "max_students must be a number"}), 400

    batch_doc = build_batch(
        course_id    = data["course_id"],
        name         = data["name"],
        start_date   = data["start_date"],
        end_date     = data["end_date"],
        schedule     = data["schedule"],
        max_students = max_students,
    )
    result = get_batches().insert_one(batch_doc)
    return jsonify({
        "message"  : "Batch created",
        "batch_id" : batch_doc["batch_id"],
        "_id"      : str(result.inserted_id),
    }), 201


@admin_bp.get("/batches")
@admin_required
def list_batches():
    course_id = request.args.get("course_id", "").strip()
    page      = max(int(request.args.get("page", 1) or 1), 1)
    per_page  = max(int(request.args.get("per_page", 20) or 20), 1)

    query = {}
    if course_id:
        err = validate_osec_id(course_id, "course_id")
        if err:
            return err
        query["course_id"] = course_id

    total   = get_batches().count_documents(query)
    batches = list(
        get_batches().find(query)
        .sort("created_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return jsonify({
        "total"     : total,
        "batches"   : [_clean(b) for b in batches],
        "pagination": {
            "page": page, "per_page": per_page, "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }), 200


@admin_bp.get("/batches/<batch_id>")
@admin_required
def get_batch(batch_id):
    batch = get_batches().find_one({"batch_id": batch_id})
    if not batch:
        return jsonify({"error": "Batch not found"}), 404

    # fetch enrolled student details
    # batch["students"] stores str(student["_id"]) values — query by _id
    student_ids = batch.get("students", [])
    students    = []
    for sid in student_ids:
        try:
            s = get_students().find_one(
                {"_id": ObjectId(sid)},
                {"password_hash": 0, "face_encoding": 0}
            )
            if s:
                students.append(s)
        except Exception:
            pass  # skip malformed ids

    batch_clean           = _clean(batch)
    batch_clean["students"] = [_clean(s) for s in students]
    return jsonify(batch_clean), 200


@admin_bp.post("/batches/<batch_id>/enrol")
@admin_required
def enrol_in_batch(batch_id):
    err = validate_osec_id(batch_id, "batch_id")
    if err:
        return err

    data       = request.get_json(silent=True) or {}
    student_id = safe_str(data, "student_id")
    if not student_id:
        return jsonify({"error": "student_id required"}), 400

    err = validate_osec_id(student_id, "student_id")
    if err:
        return err

    batch   = get_batches().find_one({"batch_id": batch_id})
    student = get_students().find_one({"student_id": student_id})

    if not batch:   return jsonify({"error": "Batch not found"}),   404
    if not student: return jsonify({"error": "Student not found"}), 404

    if len(batch.get("students",[])) >= batch.get("max_students", 20):
        return jsonify({"error": "Batch is full"}), 400

    s_oid = str(student["_id"])
    if s_oid in batch.get("students", []):
        return jsonify({"error": "Student already in this batch"}), 409

    get_batches().update_one(
        {"batch_id": batch_id},
        {"$addToSet": {"students": s_oid}}
    )
    get_students().update_one(
        {"student_id": student_id},
        {"$addToSet": {"enrolled_courses": batch["course_id"],
                       "enrolled_batches": batch_id}}
    )
    return jsonify({"message": "Student enrolled in batch"}), 200


@admin_bp.delete("/batches/<batch_id>/enrol")
@admin_required
def remove_from_batch(batch_id):
    err = validate_osec_id(batch_id, "batch_id")
    if err:
        return err

    data       = request.get_json(silent=True) or {}
    student_id = safe_str(data, "student_id")
    if not student_id:
        return jsonify({"error": "student_id required"}), 400

    err = validate_osec_id(student_id, "student_id")
    if err:
        return err

    batch   = get_batches().find_one({"batch_id": batch_id})
    student = get_students().find_one({"student_id": student_id})
    if not batch:   return jsonify({"error": "Batch not found"}),   404
    if not student: return jsonify({"error": "Student not found"}), 404

    # Remove student from batch roster
    get_batches().update_one(
        {"batch_id": batch_id},
        {"$pull": {"students": str(student["_id"])}}
    )

    # Only remove the course from enrolled_courses if the student has no other
    # active batch in the same course; otherwise they'd lose access mid-batch.
    other_batch = get_batches().find_one({
        "course_id": batch["course_id"],
        "batch_id":  {"$ne": batch_id},
        "students":  str(student["_id"]),
        "active":    True,
    })
    if not other_batch:
        get_students().update_one(
            {"student_id": student_id},
            {"$pull": {"enrolled_courses": batch["course_id"],
                       "enrolled_batches": batch_id}}
        )
    else:
        # Still remove the specific batch from enrolled_batches
        get_students().update_one(
            {"student_id": student_id},
            {"$pull": {"enrolled_batches": batch_id}}
        )

    return jsonify({"message": "Student removed from batch"}), 200

@admin_bp.delete("/batches/<batch_id>")
@admin_required
def delete_batch(batch_id):
    """Delete a batch — blocked if enrolled students exist."""
    err = _validate_osec_id(batch_id, "batch_id")
    if err:
        return err
    batch = get_batches().find_one({"batch_id": batch_id})
    if not batch:
        return jsonify({"error": "Batch not found"}), 404
    if batch.get("students"):
        return jsonify({"error": f"Cannot delete batch — {len(batch['students'])} student(s) enrolled. Remove all students first."}), 400
    get_batches().delete_one({"batch_id": batch_id})
    return jsonify({"message": "Batch deleted"}), 200




# ═══════════════════════════════════════════════════════════════════
# FEES
# ═══════════════════════════════════════════════════════════════════

@admin_bp.post("/fees")
@admin_required
def create_fee():
    data    = request.get_json(silent=True) or {}
    missing = _missing("student_id","course_id","batch_id","total_amount", data=data)
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    for field, label in (("student_id","student_id"), ("course_id","course_id"), ("batch_id","batch_id")):
        err = validate_osec_id(data[field], label)
        if err:
            return err

    try:
        total_amount = float(data["total_amount"])
    except (ValueError, TypeError):
        return jsonify({"error": "total_amount must be a number"}), 400

    student = get_students().find_one({"student_id": data["student_id"]})
    if not student:
        return jsonify({"error": "Student not found"}), 404

    fee_doc = build_fee(
        student_id   = data["student_id"],
        course_id    = data["course_id"],
        batch_id     = data["batch_id"],
        total_amount = total_amount,
    )
    result = get_fees().insert_one(fee_doc)
    return jsonify({
        "message": "Fee record created",
        "fee_id" : fee_doc["fee_id"],
        "_id"    : str(result.inserted_id),
    }), 201


@admin_bp.get("/fees")
@admin_required
def list_fees():
    """List all fee records with optional filtering and pagination."""
    search   = request.args.get("search", "").strip()
    status   = request.args.get("status", "").strip()
    page     = max(int(request.args.get("page", 1) or 1), 1)
    per_page = max(int(request.args.get("per_page", 20) or 20), 1)

    query = {}
    if search:
        query["$or"] = [
            {"student_id": {"$regex": search, "$options": "i"}},
            {"fee_id":     {"$regex": search, "$options": "i"}},
        ]
    if status:
        query["status"] = status

    total = get_fees().count_documents(query)
    fees  = list(
        get_fees().find(query)
        .sort("created_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return jsonify({
        "total"     : total,
        "fees"      : [_clean(f) for f in fees],
        "pagination": {
            "page": page, "per_page": per_page, "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }), 200


@admin_bp.get("/fees/due")
@admin_required
def fees_due():
    # NOTE: this route MUST be registered before /fees/<student_id>
    # so Flask matches the literal "due" before the variable segment.
    dues = list(get_fees().find(
        {"status": {"$ne": "paid"}},
        {"_id": 0, "fee_id": 1, "student_id": 1,
         "course_id": 1, "due_amount": 1, "status": 1}
    ).sort("due_amount", -1))
    return jsonify({"dues": dues}), 200


@admin_bp.get("/fees/<student_id>")
@admin_required
def get_student_fees(student_id):
    fees = list(get_fees().find({"student_id": student_id}).sort("created_at", -1))
    return jsonify({
        "student_id": student_id,
        "fees"      : [_clean(f) for f in fees],
    }), 200


@admin_bp.post("/fees/<fee_id>/pay")
@admin_required
def record_payment(fee_id):
    data    = request.get_json(silent=True) or {}
    missing = _missing("amount","mode", data=data)
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    fee = get_fees().find_one({"fee_id": fee_id})
    if not fee:
        return jsonify({"error": "Fee record not found"}), 404

    amount = float(data["amount"])
    if amount <= 0:
        return jsonify({"error": "Payment amount must be greater than zero"}), 400

    import shortuuid
    payment_entry = {
        "receipt" : f"RCP-{shortuuid.ShortUUID().random(length=6).upper()}",
        "amount"  : amount,
        "mode"    : data["mode"],   # cash | upi | bank
        "date"    : datetime.utcnow().isoformat(),
        "note"    : data.get("note",""),
    }

    # Atomic update — avoids race condition between concurrent payments on the
    # same fee record.  We clamp due_amount to 0 with a conditional update
    # after the $inc so it never goes negative.
    get_fees().update_one(
        {"fee_id": fee_id},
        {
            "$inc" : {"paid_amount": amount, "due_amount": -amount},
            "$push": {"payments": payment_entry},
        }
    )
    # Clamp due_amount to 0 and set final status in one more update
    updated_fee = get_fees().find_one({"fee_id": fee_id})
    new_due     = max(updated_fee["due_amount"], 0)
    new_status  = "paid" if new_due <= 0 else "partial"
    get_fees().update_one(
        {"fee_id": fee_id},
        {"$set": {"due_amount": new_due, "status": new_status}}
    )

    return jsonify({
        "message"    : "Payment recorded",
        "receipt"    : payment_entry["receipt"],
        "paid_amount": updated_fee["paid_amount"],
        "due_amount" : new_due,
        "status"     : new_status,
    }), 200


# ═══════════════════════════════════════════════════════════════════
# EXAMS (question builder)
# ═══════════════════════════════════════════════════════════════════

@admin_bp.post("/exams")
@admin_required
def create_exam():
    data    = request.get_json(silent=True) or {}
    required = ["course_id","title","duration_minutes","total_marks","pass_marks"]
    missing = _missing(*required, data=data)
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400
    if not data.get("questions") and not data.get("question_ids"):
        return jsonify({"error": "Either 'questions' or 'question_ids' must be provided"}), 400

    err = validate_osec_id(data["course_id"], "course_id")
    if err:
        return err
    err = validate_lengths(data, fields=["title"])
    if err:
        return err

    if not get_courses().find_one({"course_id": data["course_id"]}):
        return jsonify({"error": "Course not found"}), 404

    total_marks = int(data["total_marks"])
    pass_marks  = int(data["pass_marks"])
    if total_marks <= 0:
        return jsonify({"error": "total_marks must be greater than zero"}), 400
    if pass_marks <= 0:
        return jsonify({"error": "pass_marks must be greater than zero"}), 400
    if pass_marks > total_marks:
        return jsonify({"error": f"pass_marks ({pass_marks}) cannot exceed total_marks ({total_marks})"}), 400

    # Determine which question source to use
    question_ids = data.get("question_ids")
    legacy_questions = data.get("questions")
    questions_to_use = None

    if question_ids is not None:
        if not isinstance(question_ids, list) or not question_ids:
            return jsonify({"error": "'question_ids' must be a non-empty list"}), 400
        err = validate_osec_ids(question_ids, "question_id")
        if err:
            return err
        # Fetch questions from bank
        questions_list = []
        for qid in question_ids:
            q = get_question(qid)
            if not q:
                return jsonify({"error": f"Question not found or inactive: {qid}"}), 404
            if not q.get("question_text") or not q.get("type"):
                return jsonify({"error": f"Question {qid} missing required text or type"}), 404
            exam_question = {
                "q_id": q["question_id"],
                "type": q["type"],
                "question": q["question_text"],
                "marks": q["marks"],
                "options": q.get("options", []),
                "correct_answer": q.get("correct_answer"),
                "ai_rubric": q.get("ai_rubric")
            }
            questions_list.append(exam_question)
        questions_to_use = questions_list
    else:
        # Legacy path: use provided questions list
        if not isinstance(legacy_questions, list) or not legacy_questions:
            return jsonify({"error": "'questions' must be a non-empty list"}), 400
        # Validate each question has required keys
        for i, q in enumerate(legacy_questions):
            if not isinstance(q, dict):
                return jsonify({"error": f"Question {i+1} must be an object"}), 400
            if not q.get("q_id") or not q.get("type") or not q.get("question"):
                return jsonify({
                    "error": f"Question {i+1} is missing q_id, type, or question text"
                }), 400
            err = validate_osec_id(q["q_id"], "q_id")
            if err:
                return err
            err = validate_lengths(q, fields=["question", "ai_rubric"],
                                    limits={"question": 5000, "ai_rubric": 5000})
            if err:
                return err
            if q["type"] == "mcq" and not q.get("correct_answer"):
                return jsonify({
                    "error": f"MCQ question {q['q_id']} missing correct_answer"
                }), 400
            if q["type"] == "written" and not q.get("ai_rubric"):
                return jsonify({
                    "error": f"Written question {q['q_id']} missing ai_rubric"
                }), 400
        questions_to_use = legacy_questions

    exam_doc = build_exam(
        course_id        = data["course_id"],
        title            = data["title"],
        duration_minutes = int(data["duration_minutes"]),
        total_marks      = int(data["total_marks"]),
        pass_marks       = int(data["pass_marks"]),
        questions        = questions_to_use,
    )
    result = get_exams().insert_one(exam_doc)
    return jsonify({
        "message" : "Exam created",
        "exam_id" : exam_doc["exam_id"],
        "_id"     : str(result.inserted_id),
    }), 201


@admin_bp.get("/exams")
@admin_required
def list_exams():
    course_id = request.args.get("course_id", "").strip()
    page      = max(int(request.args.get("page", 1) or 1), 1)
    per_page  = max(int(request.args.get("per_page", 20) or 20), 1)

    query = {}
    if course_id:
        err = validate_osec_id(course_id, "course_id")
        if err:
            return err
        query["course_id"] = course_id

    total = get_exams().count_documents(query)
    exams = list(
        get_exams()
        .find(query, {"questions.correct_answer": 0})  # hide answers from list view
        .sort("created_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return jsonify({
        "total"     : total,
        "exams"     : [_clean(e) for e in exams],
        "pagination": {
            "page": page, "per_page": per_page, "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }), 200


@admin_bp.get("/exams/<exam_id>")
@admin_required
def get_exam(exam_id):
    # admin can see correct answers
    exam = get_exams().find_one({"exam_id": exam_id})
    if not exam:
        return jsonify({"error": "Exam not found"}), 404
    return jsonify(_clean(exam)), 200


@admin_bp.put("/exams/<exam_id>")
@admin_required
def update_exam(exam_id):
    """Update exam metadata and/or replace the question list."""
    err = validate_osec_id(exam_id, "exam_id")
    if err:
        return err

    exam = get_exams().find_one({"exam_id": exam_id})
    if not exam:
        return jsonify({"error": "Exam not found"}), 404

    data    = request.get_json(silent=True) or {}
    allowed = {"title", "duration_minutes", "total_marks", "pass_marks",
               "instructions", "active"}
    updates = {k: data[k] for k in allowed if k in data}

    err = validate_lengths(updates, fields=["title", "instructions"])
    if err:
        return err

    # Validate marks whenever either is touched
    total  = int(data.get("total_marks", exam["total_marks"]))
    passes = int(data.get("pass_marks",  exam["pass_marks"]))
    if total <= 0:
        return jsonify({"error": "total_marks must be greater than zero"}), 400
    if passes <= 0:
        return jsonify({"error": "pass_marks must be greater than zero"}), 400
    if passes > total:
        return jsonify({"error": f"pass_marks ({passes}) cannot exceed total_marks ({total})"}), 400

    # Rebuild question list from question-bank IDs (the only path the UI uses)
    if "question_ids" in data:
        qids = data["question_ids"]
        if not isinstance(qids, list) or not qids:
            return jsonify({"error": "'question_ids' must be a non-empty list"}), 400
        err = validate_osec_ids(qids, "question_id")
        if err:
            return err
        from services.question_service import get_question as _get_q
        qs = []
        for qid in qids:
            q = _get_q(qid)
            if not q:
                return jsonify({"error": f"Question not found: {qid}"}), 404
            qs.append({
                "q_id"          : q["question_id"],
                "type"          : q["type"],
                "question"      : q["question_text"],
                "marks"         : q["marks"],
                "options"       : q.get("options", []),
                "correct_answer": q.get("correct_answer"),
                "ai_rubric"     : q.get("ai_rubric"),
            })
        updates["questions"] = qs

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    updates["updated_at"] = datetime.utcnow()
    get_exams().update_one({"exam_id": exam_id}, {"$set": updates})
    return jsonify({"message": "Exam updated",
                    "exam": _clean(get_exams().find_one({"exam_id": exam_id}))}), 200


@admin_bp.delete("/exams/<exam_id>")
@admin_required
def delete_exam(exam_id):
    # block deletion if results exist for this exam
    if get_results().find_one({"exam_id": exam_id}):
        return jsonify({
            "error": "Cannot delete exam — results already exist for it"
        }), 400

    get_exams().delete_one({"exam_id": exam_id})
    return jsonify({"message": "Exam deleted"}), 200


# ═══════════════════════════════════════════════════════════════════
# RESULTS (admin view + hard delete)
# ═══════════════════════════════════════════════════════════════════

@admin_bp.get("/results")
@admin_required
def list_results():
    search   = request.args.get("search", "").strip()
    passed   = request.args.get("passed", "").strip()   # "true" / "false" / ""
    page     = max(int(request.args.get("page", 1) or 1), 1)
    per_page = max(int(request.args.get("per_page", 20) or 20), 1)

    query = {}
    if search:
        query["$or"] = [
            {"student_id": {"$regex": search, "$options": "i"}},
            {"exam_id":    {"$regex": search, "$options": "i"}},
        ]
    if passed == "true":
        query["passed"] = True
    elif passed == "false":
        query["passed"] = False

    total   = get_results().count_documents(query)
    results = list(
        get_results()
        .find(query, {"ai_evaluation": 0})   # exclude heavy field
        .sort("created_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return jsonify({
        "total"     : total,
        "results"   : [_clean(r) for r in results],
        "pagination": {
            "page": page, "per_page": per_page, "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }), 200
    results = list(
        get_results()
        .find({}, {"ai_evaluation": 0})   # exclude heavy field from list
        .skip((page - 1) * per_page)
        .limit(per_page)
        .sort("created_at", -1)
    )
    return jsonify({
        "total"  : total,
        "results": [_clean(r) for r in results],
    }), 200


@admin_bp.get("/results/<result_id>")
@admin_required
def get_result(result_id):
    result = get_results().find_one({"result_id": result_id})
    if not result:
        return jsonify({"error": "Result not found"}), 404
    return jsonify(_clean(result)), 200


@admin_bp.delete("/results/<result_id>")
@admin_required
def delete_result(result_id):
    """Hard delete — only admin can do this."""
    err = validate_osec_id(result_id, "result_id")
    if err:
        return err
    res = get_results().delete_one({"result_id": result_id})
    if res.deleted_count == 0:
        return jsonify({"error": "Result not found"}), 404
    return jsonify({"message": "Result permanently deleted"}), 200


# ═══════════════════════════════════════════════════════════════════
# TEACHERS  (Fix #1 — build_teacher was imported but never used)
# ═══════════════════════════════════════════════════════════════════

@admin_bp.post("/teachers")
@admin_required
def create_teacher():
    """Create a new teacher account."""
    data    = request.get_json(silent=True) or {}
    missing = _missing("name", "email", "phone", "password", data=data)
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    err = validate_lengths(data)
    if err:
        return err

    err = validate_password(data)
    if err:
        return err

    teaches = data.get("teaches", [])
    err = validate_osec_ids(teaches, "course_id")
    if err:
        return err

    if get_teachers().find_one({"email": data["email"]}):
        return jsonify({"error": "A teacher with this email already exists"}), 409

    try:
        teacher_doc = build_teacher(
            name               = data["name"].strip(),
            email              = data["email"].strip().lower(),
            phone              = data.get("phone", "").strip(),
            dob                = data.get("dob", ""),
            gender             = data.get("gender", ""),
            address            = data.get("address", "").strip(),
            subject_expertise  = data.get("subject_expertise", "").strip(),
            qualification      = data.get("qualification", "").strip(),
            plain_password     = data["password"],
            photo_url          = data.get("photo_url", ""),
            teaches            = data.get("teaches", []),    # list of course_ids
        )
        get_teachers().insert_one(teacher_doc)
        teacher_doc.pop("password_hash", None)
        teacher_doc["_id"] = str(teacher_doc["_id"])
        return jsonify({"message": "Teacher created", "teacher": teacher_doc}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@admin_bp.get("/teachers")
@admin_required
def list_teachers():
    """List all teachers with optional search."""
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    search   = request.args.get("search", "").strip()
    include_inactive = request.args.get("include_inactive", "false").lower() == "true"

    query = {} if include_inactive else {"active": True}
    if search:
        query["$or"] = [
            {"name"      : {"$regex": search, "$options": "i"}},
            {"teacher_id": {"$regex": search, "$options": "i"}},
            {"email"     : {"$regex": search, "$options": "i"}},
        ]

    total   = get_teachers().count_documents(query)
    teachers = list(
        get_teachers()
        .find(query, {"password_hash": 0})
        .sort("created_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return jsonify({
        "teachers"  : [_clean(t) for t in teachers],
        "pagination": {"page": page, "per_page": per_page, "total": total,
                       "pages": (total + per_page - 1) // per_page},
    }), 200


@admin_bp.get("/teachers/<teacher_id>")
@admin_required
def get_teacher(teacher_id):
    teacher = get_teachers().find_one({"teacher_id": teacher_id}, {"password_hash": 0})
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404
    return jsonify(_clean(teacher)), 200


@admin_bp.put("/teachers/<teacher_id>")
@admin_required
def update_teacher(teacher_id):
    """
    Update teacher details. Admins may also update email, dob, gender,
    and reset the teacher's password here (no old_password required —
    that's only enforced on the teacher's own self-service endpoint).
    """
    err = validate_osec_id(teacher_id, "teacher_id")
    if err:
        return err

    data    = request.get_json(silent=True) or {}
    teacher = get_teachers().find_one({"teacher_id": teacher_id})
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    allowed = {"name", "phone", "address", "subject_expertise",
               "qualification", "photo_url", "teaches", "active",
               "email", "dob", "gender"}
    updates = {k: v for k, v in data.items() if k in allowed}

    err = validate_lengths(updates)
    if err:
        return err

    if "teaches" in updates:
        err = validate_osec_ids(updates["teaches"], "course_id")
        if err:
            return err

    # Email changes: normalise + enforce uniqueness (mirrors create_teacher)
    if "email" in updates:
        new_email = updates["email"].strip().lower()
        if not new_email:
            return jsonify({"error": "Email cannot be empty"}), 400
        existing = get_teachers().find_one({"email": new_email})
        if existing and existing["teacher_id"] != teacher_id:
            return jsonify({"error": "A teacher with this email already exists"}), 409
        updates["email"] = new_email

    # Admin-initiated password reset
    if data.get("password"):
        err = validate_password(data, max_len=128)
        if err:
            return err
        updates["password_hash"] = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    updates["updated_at"] = datetime.utcnow()
    get_teachers().update_one({"teacher_id": teacher_id}, {"$set": updates})
    updated = get_teachers().find_one({"teacher_id": teacher_id}, {"password_hash": 0})
    return jsonify({"message": "Teacher updated", "teacher": _clean(updated)}), 200


@admin_bp.delete("/teachers/<teacher_id>")
@admin_required
def deactivate_teacher(teacher_id):
    """Soft-delete (deactivate) a teacher account."""
    result = get_teachers().update_one(
        {"teacher_id": teacher_id},
        {"$set": {"active": False, "deactivated_at": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        return jsonify({"error": "Teacher not found"}), 404
    return jsonify({"message": "Teacher deactivated"}), 200


# ═══════════════════════════════════════════════════════════════════
# EXAM EXTENSION — ADMIN ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

from datetime import datetime
from flask import request, jsonify, send_file
import io


# ─────────────────────────────────────────────────────────────────────────────
# EXAM REPORTS — APPROVAL WORKFLOW
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.get("/exam-reports")
@admin_required
def list_exam_reports():
    """
    List all AI-generated exam reports.
    Query params:
      - status: pending_approval | approved | rejected | all (default: all)
      - exam_id: filter by exam
      - page: 1-based (default 1), limit 30
    """
    from db import get_exam_reports, get_students, get_exams

    status   = request.args.get("status", "all")
    exam_id  = request.args.get("exam_id")
    page     = max(1, int(request.args.get("page", 1)))
    limit    = 30
    skip     = (page - 1) * limit

    query = {}
    if status != "all":
        query["status"] = status
    if exam_id:
        query["exam_id"] = exam_id

    reports = list(
        get_exam_reports()
        .find(query, {"report_content": 0})   # omit heavy field in list view
        .sort("generated_at", -1)
        .skip(skip)
        .limit(limit)
    )

    total = get_exam_reports().count_documents(query)

    # Enrich with student name and exam title
    enriched = []
    for r in reports:
        student = get_students().find_one(
            {"student_id": r["student_id"]}, {"name": 1, "_id": 0}
        )
        exam = get_exams().find_one(
            {"exam_id": r["exam_id"]}, {"title": 1, "_id": 0}
        )
        rc = _clean(r)
        rc["student_name"] = student["name"] if student else "—"
        rc["exam_title"]   = exam["title"]   if exam    else "—"
        enriched.append(rc)

    return jsonify({
        "total"   : total,
        "page"    : page,
        "pages"   : -(-total // limit),
        "reports" : enriched,
    }), 200


@admin_bp.get("/exam-reports/<report_id>")
@admin_required
def view_exam_report(report_id):
    """Full report detail — includes report_content and answer keys."""
    from db import get_exam_reports, get_students, get_exams, get_results

    report = get_exam_reports().find_one({"report_id": report_id})
    if not report:
        return jsonify({"error": "Report not found"}), 404

    student = get_students().find_one(
        {"student_id": report["student_id"]}, {"name": 1, "email": 1, "_id": 0}
    )
    exam = get_exams().find_one(
        {"exam_id": report["exam_id"]},
        {"title": 1, "course_id": 1, "total_marks": 1, "_id": 0}
    )
    result = get_results().find_one(
        {"result_id": report.get("result_id")},
        {"ai_evaluation": 1, "_id": 0}
    )

    rc = _clean(report)
    rc["student_name"]  = student["name"]  if student else "—"
    rc["student_email"] = student["email"] if student else "—"
    rc["exam_title"]    = exam["title"]    if exam    else "—"
    rc["ai_evaluation"] = result.get("ai_evaluation") if result else None

    return jsonify(rc), 200


@admin_bp.post("/exam-reports/<report_id>/approve")
@admin_required
def approve_report(report_id):
    """
    Approve a report. After approval:
    - Student and teacher can view and download the report.
    - If report PDF hasn't been generated yet, generates it now.
    """
    from db import get_exam_reports, get_students, get_exams
    from services.exam_report_service import generate_report_pdf
    from services.video_handler import upload_certificate_pdf

    report = get_exam_reports().find_one({"report_id": report_id})
    if not report:
        return jsonify({"error": "Report not found"}), 404

    if report.get("status") == "approved":
        return jsonify({"message": "Already approved", "pdf_url": report.get("pdf_url")}), 200

    admin   = _get_admin()
    updates = {
        "status"      : "approved",
        "approved_at" : datetime.utcnow(),
        "approved_by" : admin["admin_id"] if admin else "system",
    }

    # Generate PDF if not already done
    pdf_url = report.get("pdf_url")
    if not pdf_url:
        try:
            student = get_students().find_one({"student_id": report["student_id"]})
            exam    = get_exams().find_one({"exam_id": report["exam_id"]})
            pdf_bytes = generate_report_pdf(
                report_doc   = report,
                student_name = student["name"] if student else "Student",
                exam_title   = exam["title"] if exam else "Exam",
                course_name  = exam.get("course_id","") if exam else "",
            )
            upload_res = upload_certificate_pdf(pdf_bytes, f"report_{report_id}")
            if upload_res["success"]:
                pdf_url             = upload_res["url"]
                updates["pdf_url"]  = pdf_url
        except Exception as e:
            # Don't block approval if PDF fails
            import traceback; traceback.print_exc()

    get_exam_reports().update_one({"report_id": report_id}, {"$set": updates})

    return jsonify({
        "message" : "Report approved. Student and teacher can now access it.",
        "pdf_url" : pdf_url,
    }), 200


@admin_bp.post("/exam-reports/<report_id>/reject")
@admin_required
def reject_report(report_id):
    """Reject a report (it stays hidden from student/teacher)."""
    from db import get_exam_reports

    data   = request.get_json(silent=True) or {}
    reason = data.get("reason", "").strip()
    admin  = _get_admin()

    result = get_exam_reports().update_one(
        {"report_id": report_id},
        {"$set": {
            "status"       : "rejected",
            "rejected_at"  : datetime.utcnow(),
            "rejected_by"  : admin["admin_id"] if admin else "system",
            "reject_reason": reason,
        }}
    )
    if result.matched_count == 0:
        return jsonify({"error": "Report not found"}), 404

    return jsonify({"message": "Report rejected."}), 200


@admin_bp.get("/exam-reports/<report_id>/pdf")
@admin_required
def download_report_pdf(report_id):
    """
    Download the report PDF. Generates on-the-fly if pdf_url not set yet.
    """
    from db import get_exam_reports, get_students, get_exams
    from services.exam_report_service import generate_report_pdf

    report = get_exam_reports().find_one({"report_id": report_id})
    if not report:
        return jsonify({"error": "Report not found"}), 404

    student = get_students().find_one({"student_id": report["student_id"]})
    exam    = get_exams().find_one({"exam_id": report["exam_id"]})

    pdf_bytes = generate_report_pdf(
        report_doc   = report,
        student_name = student["name"] if student else "Student",
        exam_title   = exam["title"]   if exam else "Exam",
        course_name  = exam.get("course_id","") if exam else "",
    )
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype        = "application/pdf",
        as_attachment   = True,
        download_name   = f"report_{report_id}.pdf",
    )


# ─────────────────────────────────────────────────────────────────────────────
# CERTIFICATES — APPROVAL WORKFLOW
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.get("/certificates/pending")
@admin_required
def list_pending_certificates():
    """List all certificates awaiting admin approval."""
    from db import get_certificates, get_students, get_exams

    certs = list(
        get_certificates()
        .find({"status": "pending_approval"})
        .sort("created_at", -1)
        .limit(100)
    )

    enriched = []
    for c in certs:
        student = get_students().find_one(
            {"student_id": c["student_id"]}, {"name": 1, "_id": 0}
        )
        enriched.append({
            **_clean(c),
            "student_name": student["name"] if student else "—",
        })

    return jsonify({"total": len(enriched), "certificates": enriched}), 200


@admin_bp.post("/certificates/<cert_id>/approve")
@admin_required
def approve_certificate(cert_id):
    """
    Approve a certificate — changes status from pending_approval → valid.
    Student and teacher can now download it.
    """
    from db import get_certificates

    admin  = _get_admin()
    result = get_certificates().update_one(
        {"cert_id": cert_id, "status": "pending_approval"},
        {"$set": {
            "status"      : "valid",
            "approved_at" : datetime.utcnow(),
            "approved_by" : admin["admin_id"] if admin else "system",
        }}
    )
    if result.matched_count == 0:
        cert = get_certificates().find_one({"cert_id": cert_id})
        if not cert:
            return jsonify({"error": "Certificate not found"}), 404
        return jsonify({
            "message": f"Certificate status is already '{cert.get('status')}'.",
            "cert_id": cert_id,
        }), 200

    return jsonify({
        "message": "Certificate approved. Student and teacher can now download it.",
        "cert_id": cert_id,
    }), 200


@admin_bp.post("/certificates/<cert_id>/reject")
@admin_required
def reject_certificate(cert_id):
    """Reject a certificate (keeps status as pending, adds reject note)."""
    from db import get_certificates
    data   = request.get_json(silent=True) or {}
    reason = data.get("reason", "").strip()
    admin  = _get_admin()

    result = get_certificates().update_one(
        {"cert_id": cert_id},
        {"$set": {
            "status"       : "rejected",
            "rejected_at"  : datetime.utcnow(),
            "rejected_by"  : admin["admin_id"] if admin else "system",
            "reject_reason": reason,
        }}
    )
    if result.matched_count == 0:
        return jsonify({"error": "Certificate not found"}), 404

    return jsonify({"message": "Certificate rejected.", "cert_id": cert_id}), 200


# ─────────────────────────────────────────────────────────────────────────────
# PROCTORING VIDEO + LOG ACCESS
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.get("/sessions/<session_id>/video")
@admin_required
def view_session_video(session_id):
    """
    Returns all video chunk URLs for a session.
    Admin can watch them in sequence in the portal UI.
    """
    from db import get_exam_sessions

    session = get_exam_sessions().find_one(
        {"session_id": session_id},
        {"video_url": 1, "video_chunks": 1, "student_id": 1,
         "exam_id": 1, "start_time": 1, "end_time": 1, "_id": 0}
    )
    if not session:
        return jsonify({"error": "Session not found"}), 404

    return jsonify({
        "session_id"  : session_id,
        "student_id"  : session.get("student_id"),
        "exam_id"     : session.get("exam_id"),
        "start_time"  : session.get("start_time","").isoformat() if session.get("start_time") else None,
        "end_time"    : session.get("end_time","").isoformat() if session.get("end_time") else None,
        "video_url"   : session.get("video_url"),   # single final URL (if uploaded at end)
        "video_chunks": session.get("video_chunks", []),  # chunk list (if chunked)
        "total_chunks": len(session.get("video_chunks", [])),
    }), 200


@admin_bp.get("/sessions/<session_id>/proctor-log")
@admin_required
def view_proctor_log(session_id):
    """
    Full proctoring log for a session — all face events + suspicious events
    with timestamps.
    """
    from db import get_exam_sessions, get_students

    session = get_exam_sessions().find_one({"session_id": session_id})
    if not session:
        return jsonify({"error": "Session not found"}), 404

    student = get_students().find_one(
        {"student_id": session["student_id"]}, {"name": 1, "_id": 0}
    )

    proctor_log = session.get("proctor_log", [])
    face_log    = session.get("face_log",    [])

    # Summary
    summary = {
        "total_suspicious_events": len(proctor_log),
        "no_face_events"         : sum(1 for e in proctor_log if e.get("event_type") == "no_face"),
        "multiple_face_events"   : sum(1 for e in proctor_log if e.get("event_type") == "multiple_faces"),
        "looking_away_events"    : sum(1 for e in proctor_log if e.get("event_type") == "looking_away"),
        "tab_switch_events"      : sum(1 for e in proctor_log if e.get("event_type") == "tab_switch"),
        "total_face_checks"      : len(face_log),
        "typing_data"            : session.get("typing_data", {}),
    }

    return jsonify({
        "session_id"  : session_id,
        "student_name": student["name"] if student else "—",
        "status"      : session.get("status"),
        "summary"     : summary,
        "proctor_log" : proctor_log,
        "face_log"    : face_log,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# AI-GENERATED EXAM PAPERS (ADMIN VIEW — includes answer keys)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.get("/exam-papers")
@admin_required
def list_all_exam_papers():
    """List all AI-generated draft/published exam papers (with answer keys hidden in list view)."""
    from db import get_exam_papers

    status = request.args.get("status", "all")
    query  = {} if status == "all" else {"status": status}

    papers = list(
        get_exam_papers()
        .find(query, {"questions.model_answer": 0, "questions.ai_rubric": 0})
        .sort("created_at", -1)
        .limit(100)
    )
    return jsonify({"total": len(papers), "papers": [_clean(p) for p in papers]}), 200


@admin_bp.get("/exam-papers/<paper_id>")
@admin_required
def view_exam_paper_admin(paper_id):
    """View full paper WITH answer keys and rubrics — admin only."""
    from db import get_exam_papers
    paper = get_exam_papers().find_one({"paper_id": paper_id})
    if not paper:
        return jsonify({"error": "Paper not found"}), 404
    return jsonify(_clean(paper)), 200


@admin_bp.delete("/exam-papers/<paper_id>")
@admin_required
def delete_exam_paper(paper_id):
    """Hard-delete any exam paper (draft or published). Admin only."""
    from db import get_exam_papers
    result = get_exam_papers().delete_one({"paper_id": paper_id})
    if result.deleted_count == 0:
        return jsonify({"error": "Paper not found"}), 404
    return jsonify({"message": "Exam paper deleted"}), 200


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN DASHBOARD STATS (extend the existing dashboard if present)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.get("/dashboard/exam-stats")
@admin_required
def exam_dashboard_stats():
    """
    Exam-specific dashboard stats for the admin portal.
    Returns counts for reports/certs awaiting approval.
    """
    from db import (get_exam_reports, get_certificates, get_exam_papers,
                    get_exam_sessions, get_results)

    return jsonify({
        "reports": {
            "pending_approval": get_exam_reports().count_documents({"status": "pending_approval"}),
            "approved"        : get_exam_reports().count_documents({"status": "approved"}),
            "rejected"        : get_exam_reports().count_documents({"status": "rejected"}),
            "total"           : get_exam_reports().count_documents({}),
        },
        "certificates": {
            "pending_approval": get_certificates().count_documents({"status": "pending_approval"}),
            "valid"           : get_certificates().count_documents({"status": "valid"}),
            "rejected"        : get_certificates().count_documents({"status": "rejected"}),
            "total"           : get_certificates().count_documents({}),
        },
        "exam_papers": {
            "draft"           : get_exam_papers().count_documents({"status": "draft"}),
            "published"       : get_exam_papers().count_documents({"status": "published"}),
            "total"           : get_exam_papers().count_documents({}),
        },
        "sessions": {
            "active"          : get_exam_sessions().count_documents({"status": "active"}),
            "completed"       : get_exam_sessions().count_documents({"status": "completed"}),
            "total"           : get_exam_sessions().count_documents({}),
        },
        "results": {
            "total"           : get_results().count_documents({}),
            "passed"          : get_results().count_documents({"passed": True}),
            "failed"          : get_results().count_documents({"passed": False}),
        },
    }), 200

