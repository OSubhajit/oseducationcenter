"""
services/question_service.py — Business logic for question bank operations
"""
from bson import ObjectId
from datetime import datetime
from pymongo.errors import DuplicateKeyError
from flask import current_app
from models.question_bank import new_question_id, build_question
from db import get_questions


def _validate_mcq_data(data):
    """Validate MCQ-specific fields."""
    if not data.get("options") or len(data["options"]) < 2:
        raise ValueError("MCQ questions must have at least two options")
    if not data.get("correct_answer"):
        raise ValueError("MCQ questions must have a correct answer")
    # Ensure options have label and text
    for opt in data["options"]:
        if not isinstance(opt, dict) or "label" not in opt or "text" not in opt:
            raise ValueError("Each option must be a dict with 'label' and 'text'")
    # Ensure correct_answer matches one of the option labels
    labels = [opt["label"].upper() for opt in data["options"]]
    if data["correct_answer"].upper() not in labels:
        raise ValueError("Correct answer must match one of the option labels")


def _validate_written_data(data):
    """Validate written-specific fields."""
    if not data.get("ai_rubric"):
        raise ValueError("Written questions must have an AI rubric")


def create_question(data):
    """
    Create a new question.
    Expects dict with keys: question_text, type, marks, plus type-specific fields.
    Returns the created question document (with _id and question_id as strings).
    Raises ValueError on validation error.
    """
    # Determine type
    qtype = data.get("type", "").lower()
    if qtype not in ("mcq", "written"):
        raise ValueError("Question type must be 'mcq' or 'written'")

    # Validate based on type
    if qtype == "mcq":
        _validate_mcq_data(data)
    else:
        _validate_written_data(data)

    # Build question document
    question_doc = build_question(
        question_text=data["question_text"],
        qtype=qtype,
        marks=data["marks"],
        options=data.get("options", []),
        correct_answer=data.get("correct_answer"),
        ai_rubric=data.get("ai_rubric"),
        category=data.get("category", ""),
        difficulty=data.get("difficulty", "medium"),
        tags=data.get("tags", []),
        active=data.get("active", True)
    )

    # Insert into DB
    try:
        result = get_questions().insert_one(question_doc)
        question_doc["_id"] = str(result.inserted_id)
        # Ensure question_id is present (should be from build_question)
        return question_doc
    except DuplicateKeyError:
        raise ValueError("A question with this ID already exists (unexpected)")


def get_question(question_id):
    """
    Fetch a question by its question_id (e.g., QUES-ABC123).
    Returns question document with _id as string, or None if not found.
    Only returns active questions — for selecting questions to build exams.
    """
    doc = get_questions().find_one({"question_id": question_id, "active": True})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _get_question_any(question_id):
    """
    Fetch a question regardless of active status. Used internally by
    update_question so that deactivated questions can still be found
    (e.g. to reactivate them) — get_question() would return None for
    these and make reactivation impossible.
    """
    doc = get_questions().find_one({"question_id": question_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_question_by_mongo_id(mongo_id):
    """
    Fetch a question by MongoDB _id.
    Useful for internal lookups.
    """
    try:
        doc = get_questions().find_one({"_id": ObjectId(mongo_id), "active": True})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except Exception:
        return None


def update_question(question_id, updates):
    """
    Update a question by question_id.
    Only allows updating certain fields; question_id and type cannot be changed.
    Returns updated question document, or None if not found.
    """
    # Prevent changing immutable fields
    immutable = {"question_id", "type", "created_at"}
    filtered_updates = {k: v for k, v in updates.items() if k not in immutable}
    if not filtered_updates:
        # Nothing to update
        return get_question(question_id)

    # If updating marks, ensure it's int
    if "marks" in filtered_updates:
        try:
            filtered_updates["marks"] = int(filtered_updates["marks"])
        except ValueError:
            raise ValueError("Marks must be an integer")

    # If updating options or correct_answer, validate MCQ consistency
    existing = _get_question_any(question_id)
    if existing is None:
        return None   # caller will surface this as 404

    if filtered_updates.get("type") == "mcq" or existing["type"] == "mcq":
        # If either options or correct_answer being updated, need to validate together
        current = existing
        new_options = filtered_updates.get("options", current.get("options", []))
        new_correct = filtered_updates.get("correct_answer", current.get("correct_answer"))
        if new_options is not None:
            if len(new_options) < 2:
                raise ValueError("MCQ questions must have at least two options")
            for opt in new_options:
                if not isinstance(opt, dict) or "label" not in opt or "text" not in opt:
                    raise ValueError("Each option must be a dict with 'label' and 'text'")
        if new_correct is not None and new_options:
            labels = [opt["label"].upper() for opt in new_options]
            if new_correct.upper() not in labels:
                raise ValueError("Correct answer must match one of the option labels")

    # If updating written fields, ensure ai_rubric present if type written
    if filtered_updates.get("type") == "written" or existing["type"] == "written":
        if "ai_rubric" in filtered_updates and not filtered_updates["ai_rubric"]:
            raise ValueError("Written questions must have an AI rubric")
        # If type changing to written, ensure ai_rubric present
        if filtered_updates.get("type") == "written" and not (filtered_updates.get("ai_rubric") or existing.get("ai_rubric")):
            raise ValueError("Written questions must have an AI rubric")

    # Set updated_at
    filtered_updates["updated_at"] = datetime.utcnow()

    result = get_questions().update_one(
        {"question_id": question_id},
        {"$set": filtered_updates}
    )
    if result.matched_count == 0:
        return None
    return _get_question_any(question_id)


def delete_question(question_id):
    """
    Soft-delete a question by setting active=False.
    Returns True if deleted, False if not found.
    """
    result = get_questions().update_one(
        {"question_id": question_id},
        {"$set": {"active": False, "updated_at": datetime.utcnow()}}
    )
    return result.modified_count > 0


def list_questions(filters=None, page=1, per_page=20, search=None, sort_by="created_at", sort_order=-1):
    """
    List questions with filtering, searching, and pagination.
    Returns tuple (questions_list, total_count).
    filters: dict of field->value filters.
        For tags, provide a list of tags to match any of them (uses $in).
        For other fields, exact match.
    search: text to search in question_text (case-insensitive regex)
    """
    query = {"active": True}
    if filters:
        for key, value in filters.items():
            if key == "tags":
                if isinstance(value, list) and value:
                    # Match any of the provided tags
                    query["tags"] = {"$in": value}
                elif isinstance(value, str):
                    # Single tag as string
                    query["tags"] = value
                # else ignore empty
            else:
                query[key] = value
    if search:
        query["question_text"] = {"$regex": search, "$options": "i"}

    cursor = get_questions().find(query)
    total  = get_questions().count_documents(query)   # cursor.count() removed in PyMongo 4
    # Apply sorting
    if sort_order == 1:
        cursor = cursor.sort(sort_by, 1)
    else:
        cursor = cursor.sort(sort_by, -1)
    # Apply pagination
    cursor = cursor.skip((page - 1) * per_page).limit(per_page)

    questions = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        questions.append(doc)

    return questions, total