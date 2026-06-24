"""
routes/questions.py — Question bank management endpoints
"""
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required
from db import get_questions
from services.question_service import (
    create_question,
    get_question,
    update_question,
    delete_question,
    list_questions
)
from routes.admin import admin_required
from validators import validate_osec_id, validate_lengths

questions_bp = Blueprint("questions", __name__, url_prefix="/api/questions")


# ─── Helper routes BEFORE /<question_id> so Flask matches literals first ───

@questions_bp.get("/categories")
@admin_required
def get_categories():
    """Get distinct categories used in questions."""
    try:
        pipeline = [
            {"$match": {"active": True}},
            {"$group": {"_id": "$category"}},
            {"$match": {"_id": {"$ne": ""}}},
            {"$sort": {"_id": 1}}
        ]
        categories = [doc["_id"] for doc in get_questions().aggregate(pipeline)]
        return jsonify({"categories": categories}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching categories: {e}")
        return jsonify({"error": "Internal server error"}), 500


@questions_bp.get("/tags")
@admin_required
def get_tags():
    """Get frequently used tags."""
    try:
        pipeline = [
            {"$match": {"active": True}},
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 50}
        ]
        tag_stats = [{"tag": doc["_id"], "count": doc["count"]}
                     for doc in get_questions().aggregate(pipeline)]
        return jsonify({"tags": tag_stats}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching tags: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ─── Collection endpoints ────────────────────────────────────────────────────

@questions_bp.post("/")
@admin_required
def create_question_endpoint():
    """Create a new question."""
    data = request.get_json(silent=True) or {}
    err = validate_lengths(data)
    if err:
        return err
    if isinstance(data.get("options"), list):
        for opt in data["options"]:
            if isinstance(opt, dict) and isinstance(opt.get("text"), str) and len(opt["text"]) > 1000:
                return jsonify({"error": "Each option's text must be 1000 characters or fewer"}), 400
    try:
        question = create_question(data)
        return jsonify({
            "message": "Question created successfully",
            "question": question
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Unexpected error creating question: {e}")
        return jsonify({"error": "Internal server error"}), 500


@questions_bp.get("/")
@admin_required
def list_questions_endpoint():
    """List questions with filtering, search, and pagination."""
    try:
        page     = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        search   = request.args.get("search", "").strip()

        filters = {}
        for param in ["type", "category", "difficulty"]:
            value = request.args.get(param)
            if value is not None:
                filters[param] = value
        active_param = request.args.get("active")
        if active_param is not None:
            filters["active"] = active_param.lower() == "true"

        tags_param = request.args.get("tags")
        if tags_param:
            tags = [t.strip() for t in tags_param.split(",") if t.strip()]
            if tags:
                filters["tags"] = tags

        questions, total = list_questions(
            filters=filters if filters else None,
            page=page,
            per_page=per_page,
            search=search if search else None,
            sort_by=request.args.get("sort_by", "created_at"),
            sort_order=1 if request.args.get("sort_order", "desc").lower() == "asc" else -1
        )

        return jsonify({
            "questions": questions,
            "pagination": {
                "page":  page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page
            }
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error listing questions: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ─── Per-resource endpoints (registered AFTER literals) ──────────────────────

@questions_bp.get("/<question_id>")
@admin_required
def get_question_endpoint(question_id):
    """Get a single question by question_id."""
    err = validate_osec_id(question_id, "question_id")
    if err:
        return err
    question = get_question(question_id)
    if not question:
        return jsonify({"error": "Question not found"}), 404
    return jsonify({"question": question}), 200


@questions_bp.put("/<question_id>")
@admin_required
def update_question_endpoint(question_id):
    """Update a question."""
    err = validate_osec_id(question_id, "question_id")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    err = validate_lengths(data)
    if err:
        return err
    if isinstance(data.get("options"), list):
        for opt in data["options"]:
            if isinstance(opt, dict) and isinstance(opt.get("text"), str) and len(opt["text"]) > 1000:
                return jsonify({"error": "Each option's text must be 1000 characters or fewer"}), 400
    try:
        updated = update_question(question_id, data)
        if not updated:
            return jsonify({"error": "Question not found"}), 404
        return jsonify({
            "message": "Question updated successfully",
            "question": updated
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating question {question_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500


@questions_bp.delete("/<question_id>")
@admin_required
def delete_question_endpoint(question_id):
    """Delete a question (soft delete)."""
    err = validate_osec_id(question_id, "question_id")
    if err:
        return err
    try:
        deleted = delete_question(question_id)
        if not deleted:
            return jsonify({"error": "Question not found"}), 404
        return jsonify({"message": "Question deleted successfully"}), 200
    except Exception as e:
        current_app.logger.error(f"Error deleting question {question_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500
