"""
models/assignment.py — Assignment model and ID generation
"""
from datetime import datetime
import shortuuid


def new_assignment_id():   return f"ASS-{shortuuid.ShortUUID().random(length=6).upper()}"


def build_assignment(
    title: str,
    description: str,
    course_id: str,
    batch_id: str = None,
    due_date: datetime = None,
    max_points: int = 100,
    assignment_type: str = "file",  # file, text, etc.
    instructions: str = "",
    attachments=None,  # list of dicts {"name": "...", "url": "..."}
    created_by: str = None,  # admin/teacher ID who created
    active: bool = True
):
    """
    Build an assignment document for storage in MongoDB.
    Returns a dict ready for insertion.
    """
    if attachments is None:
        attachments = []

    # Basic validation (service layer should do thorough validation)
    if assignment_type not in ("file", "text"):
        raise ValueError("assignment_type must be 'file' or 'text'")
    if max_points <= 0:
        raise ValueError("max_points must be positive")
    if due_date and due_date <= datetime.utcnow():
        raise ValueError("due_date must be in the future")

    return {
        "assignment_id": new_assignment_id(),
        "title": title.strip(),
        "description": description.strip(),
        "course_id": course_id.strip(),
        "batch_id": batch_id.strip() if batch_id else None,
        "due_date": due_date,
        "max_points": int(max_points),
        "assignment_type": assignment_type,
        "instructions": instructions.strip(),
        "attachments": attachments,
        "created_by": created_by,
        "active": active,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }