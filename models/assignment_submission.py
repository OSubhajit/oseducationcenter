"""
models/assignment_submission.py — Assignment submission model and ID generation
"""
from datetime import datetime
import shortuuid


def new_submission_id():   return f"SUB-{shortuuid.ShortUUID().random(length=6).upper()}"


def build_submission(
    assignment_id: str,
    student_id: str,
    submitted_at: datetime = None,
    file_url: str = None,          # for file submissions
    text_content: str = None,      # for text submissions
    score: float = None,           # graded score
    feedback: str = None,          # grader feedback
    graded_by: str = None,         # admin/teacher ID who graded
    graded_at: datetime = None,    # when graded
    status: str = "submitted"      # submitted, graded, late, etc.
):
    """
    Build an assignment submission document for storage in MongoDB.
    Returns a dict ready for insertion.
    """
    if submitted_at is None:
        submitted_at = datetime.utcnow()

    # Validate that either file_url or text_content is provided based on assignment type (checked in service)
    if not file_url and not text_content:
        raise ValueError("Either file_url or text_content must be provided")

    return {
        "submission_id": new_submission_id(),
        "assignment_id": assignment_id.strip(),
        "student_id": student_id.strip(),
        "submitted_at": submitted_at,
        "file_url": file_url,
        "text_content": text_content.strip() if text_content else None,
        "score": score,
        "feedback": feedback.strip() if feedback else None,
        "graded_by": graded_by,
        "graded_at": graded_at,
        "status": status,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }