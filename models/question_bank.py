"""
models/question_bank.py — Question bank model and ID generation
"""
from datetime import datetime
import shortuuid


def new_question_id():   return f"QUES-{shortuuid.ShortUUID().random(length=6).upper()}"


def build_question(
    question_text: str,
    qtype: str,          # "mcq" or "written"
    marks: int,
    options=None,        # list of dicts {"label": "A", "text": "..."} for mcq
    correct_answer=None, # "A" for mcq
    ai_rubric=None,      # for written
    category: str = "",
    difficulty: str = "medium",  # easy, medium, hard
    tags=None,
    active: bool = True
):
    """
    Build a question document for storage in MongoDB.
    Returns a dict ready for insertion.
    """
    if tags is None:
        tags = []
    if options is None:
        options = []

    # Basic validation (service layer should do thorough validation)
    if qtype not in ("mcq", "written"):
        raise ValueError("qtype must be 'mcq' or 'written'")
    if qtype == "mcq":
        if not options or len(options) < 2:
            raise ValueError("MCQ questions must have at least two options")
        if not correct_answer:
            raise ValueError("MCQ questions must have a correct_answer")
    else:  # written
        if not ai_rubric:
            raise ValueError("Written questions must have an ai_rubric")

    return {
        "question_id": new_question_id(),
        "question_text": question_text.strip(),
        "type": qtype,
        "marks": int(marks),
        "options": options,
        "correct_answer": correct_answer,
        "ai_rubric": ai_rubric,
        "category": category.strip(),
        "difficulty": difficulty.lower(),
        "tags": [t.strip() for t in tags if t.strip()],
        "active": active,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }