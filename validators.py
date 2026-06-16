"""
validators.py
--------------
Shared input-validation helpers used across route blueprints.

Pure functions only — no Flask extension / db / app dependencies — so
this module can be imported from any blueprint (admin, questions,
resources, assignments, auth, ...) without circular-import risk.
"""
import re
from flask import jsonify

# ── Safe field extraction ────────────────────────────────────────────────
def safe_str(data, key, default="", strip=True):
    """
    Safely extract a string field from a JSON body (optionally stripped).

    Plain `(data.get(key) or "").strip()` crashes with AttributeError if
    the client sends a non-string value (e.g. {"student_id": {"$gt": ""}}
    — a NoSQL-operator-injection attempt, or just a malformed request with
    a number/list/dict where a string is expected) — `dict or ""` returns
    the dict (truthy), and `.strip()` on a dict raises. That AttributeError
    is uncaught -> 500, instead of the clean 400 every other validation
    error in this codebase returns.

    Returns `default` (empty string) for missing/non-string values, so
    callers' existing `if not value: return 400 "X required"` and
    `validate_osec_id(value)` checks handle it cleanly. Pass strip=False
    for fields like passwords where leading/trailing whitespace may be
    meaningful and shouldn't be silently altered.
    """
    val = data.get(key)
    if not isinstance(val, str):
        return default
    return val.strip() if strip else val


# ── ID format validation ────────────────────────────────────────────────────
# All OSEC-generated IDs (student_id, course_id, batch_id, exam_id,
# question_id, assignment_id, submission_id, teacher_id, cert_id, ...) are
# alphanumeric + hyphens, capped at 64 chars. Rejecting anything else up
# front prevents NoSQL-operator injection via crafted JSON (e.g. an object
# where a string is expected) and path-traversal-style payloads in URL
# segments / request bodies before they ever reach a Mongo query.
OSEC_ID_RE = re.compile(r'^[A-Za-z0-9\-]{1,64}$')


def validate_osec_id(id_value, label="ID"):
    """
    Returns a Flask response tuple (jsonify(...), status_code) if id_value
    is not a valid OSEC ID, else None. Use as:

        err = validate_osec_id(student_id, "student_id")
        if err:
            return err
    """
    if not isinstance(id_value, str) or not OSEC_ID_RE.match(id_value):
        return jsonify({"error": f"Invalid {label} format"}), 400
    return None


def validate_osec_ids(values, label="ID"):
    """Validate a list of IDs (e.g. question_ids: [...]). Returns error tuple or None."""
    if not isinstance(values, list):
        return jsonify({"error": f"'{label}' must be a list"}), 400
    for v in values:
        err = validate_osec_id(v, label)
        if err:
            return err
    return None


def validate_password(data, field="password", min_len=6, max_len=128):
    """
    Validate a plaintext password field before it's passed to bcrypt.
    bcrypt.hashpw(plain.encode(), ...) raises AttributeError on a non-str
    (e.g. a NoSQL-operator dict), and bcrypt has a 72-byte input limit, so
    both type and length need checking before hashing.
    Returns (body_dict, status_code) on failure, else None.
    """
    val = data.get(field)
    if not isinstance(val, str):
        return jsonify({"error": f"'{field}' must be a string"}), 400
    if len(val) < min_len:
        return jsonify({"error": f"'{field}' must be at least {min_len} characters"}), 400
    if len(val) > max_len:
        return jsonify({"error": f"'{field}' must be {max_len} characters or fewer"}), 400
    return None


# ── String length validation ────────────────────────────────────────────────
# Caps on free-text fields so a client can't write multi-megabyte blobs into
# MongoDB documents (or balloon the size of exam/result documents that get
# read back on every dashboard load). Generous enough for legitimate use —
# e.g. a 5000-char rubric/description is ~1 page of text.
FIELD_MAX_LENGTHS = {
    # Identity / short fields
    "name"             : 200,
    "title"            : 200,
    "category"         : 100,
    "subject_expertise": 200,
    "qualification"    : 200,
    "schedule"         : 200,
    "phone"            : 20,
    "guardian_phone"   : 20,
    "email"            : 254,
    "gender"           : 20,
    "dob"              : 20,
    "guardian_name"    : 200,
    "address"          : 500,
    "external_url"     : 2000,
    "difficulty"       : 20,
    # Long free-text fields
    "question_text"    : 5000,
    "ai_rubric"        : 5000,
    "description"      : 5000,
    "instructions"     : 5000,
    "feedback"         : 5000,
    "answer"           : 10000,   # individual exam answer (written question)
    "text_content"     : 50000,   # assignment text submission
    # Per-item limit for list fields (tags, etc.)
    "tags"             : 50,
}


def validate_lengths(data, fields=None, limits=None):
    """
    Check string (and list-of-string) field lengths in `data` against
    FIELD_MAX_LENGTHS (or a custom `limits` dict).

    `fields`: optional iterable restricting which keys to check. If not
    given, every key in `data` that has a configured limit is checked.

    Returns (body_dict, status_code) on the first violation, else None.
    """
    limits = limits or FIELD_MAX_LENGTHS
    keys = fields if fields is not None else data.keys()

    for key in keys:
        if key not in data:
            continue
        value = data[key]
        max_len = limits.get(key)
        if max_len is None:
            continue

        if isinstance(value, str) and len(value) > max_len:
            return jsonify({"error": f"'{key}' must be {max_len} characters or fewer (got {len(value)})"}), 400

        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and len(item) > max_len:
                    return jsonify({"error": f"each item in '{key}' must be {max_len} characters or fewer"}), 400

    return None


def validate_answers_payload(answers, max_answers=200):
    """
    Validate the shape of an exam-submission `answers` list:
    [{"q_id": "...", "answer": "..."}, ...]

    Bounds both the number of answers and each answer's length, and
    validates q_id format. Returns (body_dict, status_code) or None.
    """
    if not isinstance(answers, list):
        return jsonify({"error": "'answers' must be a list"}), 400
    if len(answers) > max_answers:
        return jsonify({"error": f"Too many answers submitted (max {max_answers})"}), 400
    for a in answers:
        if not isinstance(a, dict):
            return jsonify({"error": "Each answer must be an object with q_id and answer"}), 400
        err = validate_osec_id(a.get("q_id", ""), "q_id")
        if err:
            return err
        ans = a.get("answer", "")
        if isinstance(ans, str) and len(ans) > FIELD_MAX_LENGTHS["answer"]:
            return jsonify({"error": f"Answer for {a.get('q_id')} exceeds {FIELD_MAX_LENGTHS['answer']} characters"}), 400
    return None
