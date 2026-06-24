"""
services/assignment_service.py — Business logic for assignment operations
"""
from bson import ObjectId
from datetime import datetime
from pymongo.errors import DuplicateKeyError
from flask import current_app
from models.assignment import new_assignment_id, build_assignment
from models.assignment_submission import new_submission_id, build_submission
from db import get_assignments, get_assignment_submissions, get_courses, get_batches, get_students
import os
from werkzeug.utils import secure_filename


def _validate_assignment_data(data):
    """Validate assignment-specific fields."""
    if not data.get("title"):
        raise ValueError("Title is required")
    if not data.get("description"):
        raise ValueError("Description is required")
    if not data.get("course_id"):
        raise ValueError("Course ID is required")
    if not get_courses().find_one({"course_id": data["course_id"]}):
        raise ValueError("Course not found")

    batch_id = data.get("batch_id")
    if batch_id:
        # Single fetch — reuse the result for both existence and course check
        batch = get_batches().find_one({"batch_id": batch_id})
        if not batch:
            raise ValueError("Batch not found")
        if batch["course_id"] != data["course_id"]:
            raise ValueError("Batch does not belong to the specified course")

    if not data.get("due_date"):
        raise ValueError("Due date is required")

    # Parse date first, then validate it is in the future — two separate checks
    # so the error message is accurate in both failure cases.
    try:
        due_date = (
            datetime.fromisoformat(data["due_date"])
            if isinstance(data["due_date"], str)
            else data["due_date"]
        )
    except (ValueError, TypeError):
        raise ValueError("Invalid due date format (expected ISO 8601)")

    if due_date <= datetime.utcnow():
        raise ValueError("Due date must be in the future")

    if not isinstance(data.get("max_points", 100), (int, float)) or data.get("max_points", 100) <= 0:
        raise ValueError("Max points must be a positive number")
    assignment_type = data.get("assignment_type", "file")
    if assignment_type not in ("file", "text"):
        raise ValueError("Assignment type must be 'file' or 'text'")


def create_assignment(data):
    """
    Create a new assignment.
    Expects dict with keys: title, description, course_id, batch_id (optional), due_date,
    max_points, assignment_type, instructions, attachments (optional), created_by.
    Returns the created assignment document (with _id and assignment_id as strings).
    Raises ValueError on validation error.
    """
    _validate_assignment_data(data)

    # Build assignment document
    assignment_doc = build_assignment(
        title=data["title"],
        description=data["description"],
        course_id=data["course_id"],
        batch_id=data.get("batch_id"),
        due_date=data["due_date"] if isinstance(data["due_date"], datetime) else datetime.fromisoformat(data["due_date"]),
        max_points=int(data.get("max_points", 100)),
        assignment_type=data.get("assignment_type", "file"),
        instructions=data.get("instructions", ""),
        attachments=data.get("attachments", []),
        created_by=data.get("created_by"),
        active=data.get("active", True)
    )

    # Insert into DB
    try:
        result = get_assignments().insert_one(assignment_doc)
        assignment_doc["_id"] = str(result.inserted_id)
        return assignment_doc
    except DuplicateKeyError:
        raise ValueError("An assignment with this ID already exists (unexpected)")


def get_assignment(assignment_id):
    """
    Fetch an assignment by its assignment_id (e.g., ASS-ABC123).
    Returns assignment document with _id as string, or None if not found.
    """
    doc = get_assignments().find_one({"assignment_id": assignment_id, "active": True})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_assignment_by_mongo_id(mongo_id):
    """
    Fetch an assignment by MongoDB _id.
    Useful for internal lookups.
    """
    try:
        doc = get_assignments().find_one({"_id": ObjectId(mongo_id), "active": True})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except Exception:
        return None


def update_assignment(assignment_id, updates):
    """
    Update an assignment by assignment_id.
    Only allows updating certain fields; assignment_id and course_id cannot be changed.
    Returns updated assignment document, or None if not found.
    """
    # Prevent changing immutable fields
    immutable = {"assignment_id", "course_id", "created_at"}
    filtered_updates = {k: v for k, v in updates.items() if k not in immutable}
    if not filtered_updates:
        # Nothing to update
        return get_assignment(assignment_id)

    # Validate updates if they affect validated fields
    if "due_date" in filtered_updates:
        due = filtered_updates["due_date"]
        if isinstance(due, str):
            due = datetime.fromisoformat(due)
        if due <= datetime.utcnow():
            raise ValueError("Due date must be in the future")
    if "max_points" in filtered_updates:
        if not isinstance(filtered_updates["max_points"], (int, float)) or filtered_updates["max_points"] <= 0:
            raise ValueError("Max points must be a positive number")
    if "assignment_type" in filtered_updates:
        if filtered_updates["assignment_type"] not in ("file", "text"):
            raise ValueError("Assignment type must be 'file' or 'text'")

    # Set updated_at
    filtered_updates["updated_at"] = datetime.utcnow()

    result = get_assignments().update_one(
        {"assignment_id": assignment_id, "active": True},
        {"$set": filtered_updates}
    )
    if result.matched_count == 0:
        return None
    return get_assignment(assignment_id)


def delete_assignment(assignment_id):
    """
    Soft-delete an assignment by setting active=False.
    Returns True if deleted, False if not found.
    """
    result = get_assignments().update_one(
        {"assignment_id": assignment_id},
        {"$set": {"active": False, "updated_at": datetime.utcnow()}}
    )
    return result.modified_count > 0


def list_assignments(filters=None, page=1, per_page=20, search=None, sort_by="created_at", sort_order=-1):
    """
    List assignments with filtering, searching, and pagination.
    Returns tuple (assignments_list, total_count).
    filters: dict of field->value equality filters (e.g., {"course_id": "OSEC-PD-011", "batch_id": "BATCH-XYZ"})
    search: text to search in title or description (case-insensitive regex)
    """
    query = {"active": True}
    if filters:
        for key, value in filters.items():
            if key in ["course_id", "batch_id"]:
                query[key] = value
            # Add other filterable fields as needed
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}}
        ]

    cursor = get_assignments().find(query)
    total = get_assignments().count_documents(query)
    # Apply sorting
    if sort_order == 1:
        cursor = cursor.sort(sort_by, 1)
    else:
        cursor = cursor.sort(sort_by, -1)
    # Apply pagination
    cursor = cursor.skip((page - 1) * per_page).limit(per_page)

    assignments = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        assignments.append(doc)

    return assignments, total


# Submission-related functions

def _validate_submission_data(assignment, data):
    """Validate submission data based on assignment type."""
    assignment_type = assignment.get("assignment_type")
    file_url = data.get("file_url")
    text_content = data.get("text_content")

    if assignment_type == "file":
        if not file_url:
            raise ValueError("File submission requires a file URL")
        # Additional validation: check file type, size if needed
    elif assignment_type == "text":
        if not text_content:
            raise ValueError("Text submission requires text content")
        # Optionally limit length
    else:
        raise ValueError(f"Unknown assignment type: {assignment_type}")


def submit_submission(assignment_id, student_id, data):
    """
    Create a submission for an assignment by a student.
    Expects data with either file_url or text_content depending on assignment type.
    Returns the created submission document.
    """
    assignment = get_assignment(assignment_id)
    if not assignment:
        raise ValueError("Assignment not found")
    if not assignment["active"]:
        raise ValueError("Assignment is not active")

    student = get_students().find_one({"student_id": student_id})
    if not student:
        raise ValueError("Student not found")
    if not student.get("active"):
        raise ValueError("Student is not active")
    if assignment["course_id"] not in student.get("enrolled_courses", []):
        raise ValueError("Student is not enrolled in the course for this assignment")

    # Batch-restricted assignment: check the student's batch enrollments.
    # enrolled_batches is populated by admin when enrolling a student in a batch.
    if assignment.get("batch_id"):
        enrolled_batches = student.get("enrolled_batches", [])
        if assignment["batch_id"] not in enrolled_batches:
            raise ValueError("Student is not enrolled in the specified batch")

    # Prevent duplicate submissions for the same assignment
    existing = get_assignment_submissions().find_one({
        "assignment_id": assignment_id,
        "student_id":    student_id,
    })
    if existing:
        raise ValueError("You have already submitted this assignment")

    submitted_at = datetime.utcnow()
    is_late      = submitted_at > assignment["due_date"] if assignment.get("due_date") else False

    _validate_submission_data(assignment, data)

    submission_doc = build_submission(
        assignment_id=assignment_id,
        student_id=student_id,
        submitted_at=submitted_at,
        file_url=data.get("file_url"),
        text_content=data.get("text_content"),
        status="late" if is_late else "submitted"
    )

    try:
        result = get_assignment_submissions().insert_one(submission_doc)
        submission_doc["_id"] = str(result.inserted_id)
        return submission_doc
    except DuplicateKeyError:
        raise ValueError("A submission with this ID already exists (unexpected)")


def get_submission(submission_id):
    """
    Fetch a submission by its submission_id.
    Returns submission document with _id as string, or None if not found.
    """
    doc = get_assignment_submissions().find_one({"submission_id": submission_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_submission_by_mongo_id(mongo_id):
    """
    Fetch a submission by MongoDB _id.
    """
    try:
        doc = get_assignment_submissions().find_one({"_id": ObjectId(mongo_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except Exception:
        return None


def grade_submission(submission_id, score, feedback, graded_by):
    """
    Grade a submission.
    Returns updated submission document.
    """
    submission = get_submission(submission_id)
    if not submission:
        raise ValueError("Submission not found")
    if submission["status"] == "graded":
        raise ValueError("Submission already graded")
    if score is None:
        raise ValueError("Score is required")
    assignment = get_assignment(submission["assignment_id"])
    max_points = assignment.get("max_points", 100) if assignment else 100
    if not (0 <= float(score) <= max_points):
        raise ValueError(f"Score must be between 0 and {max_points}")

    updates = {
        "score": float(score),
        "feedback": feedback.strip() if feedback else None,
        "graded_by": graded_by,
        "graded_at": datetime.utcnow(),
        "status": "graded",
        "updated_at": datetime.utcnow()
    }

    result = get_assignment_submissions().update_one(
        {"submission_id": submission_id},
        {"$set": updates}
    )
    if result.matched_count == 0:
        raise ValueError("Submission not found")
    return get_submission(submission_id)


def get_submissions_for_assignment(assignment_id, page=1, per_page=20, filters=None):
    """
    Get submissions for a specific assignment with filtering.
    filters: dict like {"student_id": "...", "status": "graded"}
    """
    query = {"assignment_id": assignment_id}
    if filters:
        for key, value in filters.items():
            if key in ["student_id", "status"]:
                query[key] = value

    # count_documents() replaces the removed cursor.count() (PyMongo 4+)
    total  = get_assignment_submissions().count_documents(query)
    cursor = (
        get_assignment_submissions()
        .find(query)
        .sort("submitted_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )

    submissions = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        submissions.append(doc)

    return submissions, total


def get_student_submissions(student_id, page=1, per_page=20, filters=None):
    """
    Get all submissions for a specific student.
    """
    query = {"student_id": student_id}
    if filters:
        for key, value in filters.items():
            if key in ["assignment_id", "status"]:
                query[key] = value

    # count_documents() replaces the removed cursor.count() (PyMongo 4+)
    total  = get_assignment_submissions().count_documents(query)
    cursor = (
        get_assignment_submissions()
        .find(query)
        .sort("submitted_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )

    submissions = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        submissions.append(doc)

    return submissions, total