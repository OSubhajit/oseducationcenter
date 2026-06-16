"""
routes/exam.py
--------------
The core exam engine. All routes used during a live exam.

START & FETCH
  POST  /exam/start                        — student starts exam session
  GET   /exam/session/<session_id>         — get current session status
  GET   /exam/questions/<session_id>       — get exam questions (NO correct answers)

LIVE FACE VERIFICATION
  POST  /exam/face-ping/<session_id>       — send webcam frame every 10s for identity check

SUBMIT
  POST  /exam/submit/<session_id>          — submit answers → AI grades → result locked

VIDEO UPLOAD (called after exam from admin side)
  POST  /exam/upload-video/<session_id>    — upload recorded exam hall video

STUDENT: view own active session
  GET   /exam/my-session                   — student's active exam session (if any)
"""
import os
import tempfile
import base64
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from validators import validate_osec_id, validate_answers_payload, safe_str

from db import (get_students, get_exams, get_exam_sessions,
                get_results, get_certificates, get_courses)
from models.schemas import (build_exam_session, build_result,
                             build_certificate, calculate_grade,
                             new_cert_id)
# NOTE: ai_grader, face_recognition, cert_generator, video_handler are
# imported lazily inside each function. Top-level imports of these crash
# blueprint registration when deepface / cloudinary are missing, making
# every route in the app return 404.

exam_bp = Blueprint("exam", __name__, url_prefix="/exam")


# ═══════════════════════════════════════════════════════════════════
# DECORATORS
# ═══════════════════════════════════════════════════════════════════

def student_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if get_jwt().get("role") != "student":
            return jsonify({"error": "Student access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if get_jwt().get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _clean(doc: dict) -> dict:
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


def _strip_answers(questions: list) -> list:
    """Remove correct_answer from MCQ questions before sending to student."""
    safe = []
    for q in questions:
        q_copy = dict(q)
        q_copy.pop("correct_answer", None)   # never expose to student
        safe.append(q_copy)
    return safe


def _get_student_from_jwt() -> dict | None:
    claims     = get_jwt()
    student_id = claims.get("student_id")
    return get_students().find_one({"student_id": student_id})


def _is_session_expired(session: dict, exam: dict) -> bool:
    duration  = exam.get("duration_minutes", 60)
    start     = session["start_time"]
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    deadline  = start + timedelta(minutes=duration)
    return datetime.utcnow() > deadline


# ═══════════════════════════════════════════════════════════════════
# START EXAM
# ═══════════════════════════════════════════════════════════════════

@exam_bp.post("/start")
@student_required
def start_exam():
    """
    Body: { "exam_id": "EXAM-OSEC-PD-011-XXXX" }

    Checks:
    - Student is enrolled in the course this exam belongs to
    - Student has no already-active session
    - Student has a face encoding registered
    - Exam exists and is active

    Creates an exam_session document and returns session_id + exam metadata.
    """
    data    = request.get_json(silent=True) or {}
    exam_id = safe_str(data, "exam_id")

    if not exam_id:
        return jsonify({"error": "exam_id required"}), 400

    err = validate_osec_id(exam_id, "exam_id")
    if err:
        return err

    student = _get_student_from_jwt()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    # ── Block if face not registered ─────────────────
    if not student.get("face_encoding"):
        return jsonify({
            "error": "Face not registered. Visit admin to complete enrolment."
        }), 403

    # ── Fetch exam ───────────────────────────────────
    exam = get_exams().find_one({"exam_id": exam_id, "active": True})
    if not exam:
        return jsonify({"error": "Exam not found or not active"}), 404

    # ── Check enrolment ──────────────────────────────
    if exam["course_id"] not in student.get("enrolled_courses", []):
        return jsonify({
            "error": "You are not enrolled in the course for this exam"
        }), 403

    # ── Block duplicate active sessions ──────────────
    active_session = get_exam_sessions().find_one({
        "student_id": student["student_id"],
        "status"    : "active",
    })
    if active_session:
        return jsonify({
            "error"      : "You already have an active exam session",
            "session_id" : active_session["session_id"],
        }), 409

    # ── Block re-take (result already exists) ────────
    existing_result = get_results().find_one({
        "student_id": student["student_id"],
        "exam_id"   : exam_id,
    })
    if existing_result:
        return jsonify({
            "error"    : "You have already taken this exam. No re-takes allowed.",
            "result_id": existing_result["result_id"],
        }), 403

    # ── Create session ───────────────────────────────
    session_doc = build_exam_session(
        student_id = student["student_id"],
        exam_id    = exam_id,
    )
    get_exam_sessions().insert_one(session_doc)

    deadline = datetime.utcnow() + timedelta(minutes=exam["duration_minutes"])

    return jsonify({
        "message"          : "Exam started. Good luck!",
        "session_id"       : session_doc["session_id"],
        "exam_id"          : exam_id,
        "title"            : exam["title"],
        "duration_minutes" : exam["duration_minutes"],
        "deadline"         : deadline.isoformat(),
        "total_marks"      : exam["total_marks"],
        "pass_marks"       : exam["pass_marks"],
        "total_questions"  : len(exam["questions"]),
    }), 201


# ═══════════════════════════════════════════════════════════════════
# FETCH QUESTIONS (no correct answers)
# ═══════════════════════════════════════════════════════════════════

@exam_bp.get("/questions/<session_id>")
@student_required
def get_questions(session_id):
    """
    Returns exam questions for an active session.
    Correct answers are NEVER included in the response.
    """
    err = validate_osec_id(session_id, "session_id")
    if err:
        return err

    student = _get_student_from_jwt()
    session = get_exam_sessions().find_one({
        "session_id": session_id,
        "status"    : "active",
    })

    if not session:
        return jsonify({"error": "Session not found or already completed"}), 404

    # only the student who owns this session can fetch questions
    if session["student_id"] != student["student_id"]:
        return jsonify({"error": "Access denied"}), 403

    exam = get_exams().find_one({"exam_id": session["exam_id"]})
    if not exam:
        return jsonify({"error": "Exam not found"}), 404

    # check time
    if _is_session_expired(session, exam):
        return jsonify({
            "error": "Time is up. Please submit your exam immediately."
        }), 410

    start    = session["start_time"]
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    deadline = start + timedelta(minutes=exam["duration_minutes"])
    remaining_seconds = max(0, int((deadline - datetime.utcnow()).total_seconds()))

    return jsonify({
        "session_id"       : session_id,
        "exam_id"          : exam["exam_id"],
        "title"            : exam["title"],
        "total_marks"      : exam["total_marks"],
        "pass_marks"       : exam["pass_marks"],
        "duration_minutes" : exam["duration_minutes"],
        "remaining_seconds": remaining_seconds,
        "questions"        : _strip_answers(exam["questions"]),
    }), 200


# ═══════════════════════════════════════════════════════════════════
# LIVE FACE VERIFICATION PING
# ═══════════════════════════════════════════════════════════════════

@exam_bp.post("/face-ping/<session_id>")
@student_required
def face_ping(session_id):
    """
    Called every 10 seconds from the exam frontend (webcam frame).
    Body: { "frame_b64": "<base64 image>" }

    Verifies identity and appends result to session face_log.
    Returns verification status so frontend can warn the student.
    """
    err = validate_osec_id(session_id, "session_id")
    if err:
        return err

    data      = request.get_json(silent=True) or {}
    frame_b64 = data.get("frame_b64", "")

    if not frame_b64:
        return jsonify({"error": "frame_b64 required"}), 400
    if not isinstance(frame_b64, str) or len(frame_b64) > 5_000_000:
        return jsonify({"error": "frame_b64 too large"}), 400

    student = _get_student_from_jwt()
    session = get_exam_sessions().find_one({
        "session_id": session_id,
        "status"    : "active",
    })

    if not session:
        return jsonify({"error": "Session not found or completed"}), 404
    if session["student_id"] != student["student_id"]:
        return jsonify({"error": "Access denied"}), 403

    # run face verification
    from services.face_recognition import verify_face, build_face_log_entry
    face_result  = verify_face(frame_b64, student["face_encoding"])
    log_entry    = build_face_log_entry(face_result)

    # append to face_log in DB
    get_exam_sessions().update_one(
        {"session_id": session_id},
        {"$push": {"face_log": log_entry}}
    )

    return jsonify({
        "verified"  : face_result["verified"],
        "confidence": face_result["confidence"],
        "status"    : face_result["status"],
        "message"   : face_result["message"],
    }), 200


# ═══════════════════════════════════════════════════════════════════
# SUBMIT EXAM
# ═══════════════════════════════════════════════════════════════════

@exam_bp.post("/submit/<session_id>")
@student_required
def submit_exam(session_id):
    """
    The most critical route in the system.

    Body: {
      "answers": [
        {"q_id": "Q001", "answer": "A"},
        {"q_id": "Q002", "answer": "A variable stores data..."}
      ]
    }

    Flow:
    1. Validate session ownership + not already submitted
    2. Lock session (status = completed)
    3. Grade MCQs instantly
    4. Grade written answers via Groq
    5. Build result document → insert with locked=True
    6. Generate PDF certificate (if passed)
    7. Upload certificate PDF to Cloudinary
    8. Return result to student
    """
    err = validate_osec_id(session_id, "session_id")
    if err:
        return err

    data    = request.get_json(silent=True) or {}
    answers = data.get("answers", [])

    err = validate_answers_payload(answers)
    if err:
        return err

    student = _get_student_from_jwt()
    session = get_exam_sessions().find_one({
        "session_id": session_id,
        "status"    : "active",
    })

    if not session:
        return jsonify({"error": "Session not found or already submitted"}), 404
    if session["student_id"] != student["student_id"]:
        return jsonify({"error": "Access denied"}), 403

    exam = get_exams().find_one({"exam_id": session["exam_id"]})
    if not exam:
        return jsonify({"error": "Exam not found"}), 404

    # ── Enforce time limit ───────────────────────────
    if _is_session_expired(session, exam):
        # Lock the session even on expired submit so student can't retry
        get_exam_sessions().update_one(
            {"session_id": session_id, "status": "active"},
            {"$set": {"status": "expired", "end_time": datetime.utcnow()}}
        )
        return jsonify({"error": "Time limit exceeded. Your session has been closed."}), 410

    # ── Step 1: Lock session immediately ────────────
    # This prevents double-submission even if student clicks twice
    lock_result = get_exam_sessions().update_one(
        {"session_id": session_id, "status": "active"},
        {"$set": {
            "status"   : "completed",
            "end_time" : datetime.utcnow(),
            "answers"  : answers,
        }}
    )
    if lock_result.modified_count == 0:
        return jsonify({"error": "Session already submitted"}), 409

    # ── Everything after the lock runs inside a try/except so that if
    #    grading or cert-generation fails we can put the session back to
    #    "active" and let the student retry, rather than leaving them in
    #    a state where the session is locked but no result exists. ──────
    try:
        # ── Step 2: Summarise face log ───────────────────
        updated_session = get_exam_sessions().find_one({"session_id": session_id})
        from services.face_recognition import summarise_face_log
        face_summary    = summarise_face_log(updated_session.get("face_log", []))

        # ── Step 3: Grade everything ─────────────────────
        from services.ai_grader import grade_full_exam
        grading = grade_full_exam(exam, answers)

        total_marks   = grading["total_marks"]
        scored_marks  = grading["scored_marks"]
        percentage    = round((scored_marks / total_marks) * 100, 2) if total_marks > 0 else 0
        grade         = calculate_grade(percentage)
        passed        = scored_marks >= exam["pass_marks"]

        # ── Step 4: Build and insert result ─────────────
        result_doc = build_result(
            student_id    = student["student_id"],
            exam_id       = exam["exam_id"],
            session_id    = session_id,
            total_marks   = total_marks,
            scored_marks  = scored_marks,
            mcq_score     = grading["mcq_score"],
            written_score = grading["written_score"],
            ai_evaluation = grading["ai_evaluation"],
            video_url     = None,     # uploaded separately after exam
            grade         = grade,
            passed        = passed,
        )
        # attach face integrity to result
        result_doc["face_integrity"] = face_summary
        get_results().insert_one(result_doc)

        # ── Step 5: Generate certificate (if passed) ─────
        cert_doc = None
        cert_url = None

        if passed:
            course = get_courses().find_one({"course_id": exam["course_id"]})
            from services.cert_generator import generate_certificate_pdf, generate_cert_hash
            from services.video_handler import upload_certificate_pdf

            cert_hash = generate_cert_hash(
                "PENDING", student["student_id"], result_doc["result_id"]
            )

            cert_doc = build_certificate(
                student_id = student["student_id"],
                course_id  = exam["course_id"],
                result_id  = result_doc["result_id"],
                grade      = grade,
                percentage = percentage,
                cert_hash  = cert_hash,
            )

            # generate PDF bytes
            pdf_bytes = generate_certificate_pdf(
                cert_id      = cert_doc["cert_id"],
                student_name = student["name"],
                student_id   = student["student_id"],
                course_name  = course["name"] if course else exam["course_id"],
                grade        = grade,
                percentage   = percentage,
                issued_date  = datetime.utcnow(),
                result_id    = result_doc["result_id"],
            )

            # upload PDF to Cloudinary
            upload_result = upload_certificate_pdf(pdf_bytes, cert_doc["cert_id"])
            if upload_result["success"]:
                cert_doc["pdf_url"] = upload_result["url"]
                cert_url            = upload_result["url"]

            # update cert hash with real cert_id
            real_hash = generate_cert_hash(
                cert_doc["cert_id"],
                student["student_id"],
                result_doc["result_id"]
            )
            cert_doc["hash"] = real_hash

            get_certificates().insert_one(cert_doc)

        # ── Step 6: Return result to student ─────────────
        response = {
            "message"       : "Exam submitted successfully",
            "result_id"     : result_doc["result_id"],
            "session_id"    : session_id,
            "total_marks"   : total_marks,
            "scored_marks"  : scored_marks,
            "percentage"    : percentage,
            "grade"         : grade,
            "passed"        : passed,
            "mcq_score"     : grading["mcq_score"],
            "written_score" : grading["written_score"],
            "face_integrity": face_summary,
            "ai_feedback"   : [
                {
                    "q_id"    : w["q_id"],
                    "feedback": w["feedback"],
                    "score"   : w["score"],
                    "max"     : w["max_marks"],
                }
                for w in grading["ai_evaluation"].get("written_answers", [])
            ],
        }

        if passed and cert_doc:
            response["certificate"] = {
                "cert_id"   : cert_doc["cert_id"],
                "pdf_url"   : cert_url,
                "verify_url": f"/api/verify/{cert_doc['cert_id']}/page",
            }
        else:
            response["certificate"] = None
            response["message_fail"] = (
                f"Minimum passing marks: {exam['pass_marks']}. "
                "Please re-enrol to attempt again."
            )

        return jsonify(response), 200

    except Exception as exc:
        # Grading or cert generation failed — unlock the session so the
        # student can re-submit once the issue is resolved.
        get_exam_sessions().update_one(
            {"session_id": session_id},
            {"$set": {"status": "active", "end_time": None, "answers": []}}
        )
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "An internal error occurred during grading. "
                     "Your session has been reopened — please try submitting again."
        }), 500


# ═══════════════════════════════════════════════════════════════════
# UPLOAD EXAM VIDEO (admin calls this after exam)
# ═══════════════════════════════════════════════════════════════════

@exam_bp.post("/upload-video/<session_id>")
@admin_required
def upload_video(session_id):
    """
    Admin uploads the recorded exam hall video after the exam ends.
    Accepts multipart/form-data with field "video".

    Updates both the exam_session and result documents with the video URL.
    """
    err = validate_osec_id(session_id, "session_id")
    if err:
        return err

    if "video" not in request.files:
        return jsonify({"error": "No video file in request"}), 400

    video_file = request.files["video"]

    # save to temp file
    suffix = os.path.splitext(video_file.filename)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        video_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        from services.video_handler import upload_exam_video
        upload_result = upload_exam_video(tmp_path, session_id)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    if not upload_result["success"]:
        return jsonify({
            "error": f"Upload failed: {upload_result.get('error')}"
        }), 500

    video_url = upload_result["url"]

    # update session
    get_exam_sessions().update_one(
        {"session_id": session_id},
        {"$set": {"video_url": video_url}}
    )

    # update result
    get_results().update_one(
        {"session_id": session_id},
        {"$set": {"video_url": video_url}}
    )

    return jsonify({
        "message"  : "Video uploaded and linked to session and result",
        "video_url": video_url,
    }), 200


# ═══════════════════════════════════════════════════════════════════
# STUDENT: CHECK OWN ACTIVE SESSION
# ═══════════════════════════════════════════════════════════════════

@exam_bp.get("/my-session")
@student_required
def my_session():
    """Returns the student's currently active session, if any."""
    student = _get_student_from_jwt()
    session = get_exam_sessions().find_one({
        "student_id": student["student_id"],
        "status"    : "active",
    })

    if not session:
        return jsonify({"active_session": None}), 200

    exam = get_exams().find_one({"exam_id": session["exam_id"]})
    if not exam:
        # Exam was deleted while session was active — treat as no active session
        return jsonify({"active_session": None}), 200
    start = session["start_time"]
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    deadline = start + timedelta(minutes=exam["duration_minutes"])
    remaining = max(0, int((deadline - datetime.utcnow()).total_seconds()))

    return jsonify({
        "active_session": {
            "session_id"       : session["session_id"],
            "exam_id"          : session["exam_id"],
            "remaining_seconds": remaining,
            "started_at"       : start.isoformat(),
        }
    }), 200


# ═══════════════════════════════════════════════════════════════════
# SESSION STATUS (admin view)
# ═══════════════════════════════════════════════════════════════════

@exam_bp.get("/session/<session_id>")
@admin_required
def get_session(session_id):
    """Admin can view full session details including face log."""
    err = validate_osec_id(session_id, "session_id")
    if err:
        return err
    session = get_exam_sessions().find_one({"session_id": session_id})
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_clean(session)), 200
