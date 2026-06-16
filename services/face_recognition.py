"""
services/face_recognition.py
-----------------------------
Handles all face recognition for the exam system:
  1. register_face()   — called when student enrolls (stores encoding in DB)
  2. verify_face()     — called every N seconds during exam (live check)
  3. verify_frame()    — verify a single base64 image frame
"""
import base64
import os
import tempfile
import numpy as np
from datetime import datetime
from deepface import DeepFace


# ── Config ────────────────────────────────────────────────────────
MODEL_NAME  = "Facenet512"   # best accuracy/speed balance
DETECTOR    = "opencv"       # fast detector, good for webcam frames
THRESHOLD   = 0.40           # distance threshold (lower = stricter)


# ── Internal helpers ─────────────────────────────────────────────

def _base64_to_tempfile(b64_string: str, suffix=".jpg") -> str:
    """Decode a base64 image string and write to a temp file. Returns path."""
    # strip data URI prefix if present  e.g. "data:image/jpeg;base64,..."
    if "," in b64_string:
        b64_string = b64_string.split(",", 1)[1]

    img_bytes = base64.b64decode(b64_string)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(img_bytes)
    tmp.flush()
    tmp.close()
    return tmp.name


def _cleanup(path: str):
    try:
        os.remove(path)
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────

def register_face(b64_image: str) -> dict:
    """
    Called during student enrolment.
    Generates face embedding and returns it for storage in MongoDB.

    Returns:
      {"success": True,  "encoding": [...], "message": "Face registered"}
      {"success": False, "encoding": None,  "message": "error details"}
    """
    tmp_path = None
    try:
        tmp_path = _base64_to_tempfile(b64_image)
        embedding_obj = DeepFace.represent(
            img_path        = tmp_path,
            model_name      = MODEL_NAME,
            detector_backend= DETECTOR,
            enforce_detection=True,
        )
        encoding = embedding_obj[0]["embedding"]
        return {
            "success" : True,
            "encoding": encoding,
            "message" : "Face registered successfully",
        }
    except ValueError as e:
        return {
            "success" : False,
            "encoding": None,
            "message" : f"No face detected in image. Please use a clear, front-facing photo. ({e})",
        }
    except Exception as e:
        return {
            "success" : False,
            "encoding": None,
            "message" : f"Face registration failed: {str(e)}",
        }
    finally:
        if tmp_path:
            _cleanup(tmp_path)


def verify_face(b64_frame: str, stored_encoding: list) -> dict:
    """
    Called live during exam (every ~10 seconds from webcam).
    Compares webcam frame against the stored face encoding.

    Returns:
      {
        "verified"  : True/False,
        "confidence": 0.0–1.0,   # 1.0 = perfect match
        "status"    : "verified" | "mismatch" | "no_face" | "error",
        "message"   : str,
        "timestamp" : ISO datetime string,
      }
    """
    tmp_path = None
    try:
        tmp_path = _base64_to_tempfile(b64_frame)

        # get embedding of the live frame
        live_obj = DeepFace.represent(
            img_path        = tmp_path,
            model_name      = MODEL_NAME,
            detector_backend= DETECTOR,
            enforce_detection=True,
        )
        live_encoding = live_obj[0]["embedding"]

        # cosine distance between live and stored
        live_arr   = np.array(live_encoding)
        stored_arr = np.array(stored_encoding)
        cosine_sim = np.dot(live_arr, stored_arr) / (
            np.linalg.norm(live_arr) * np.linalg.norm(stored_arr)
        )
        distance   = 1 - cosine_sim           # lower = more similar
        confidence = round(float(cosine_sim), 4)
        verified   = distance < THRESHOLD

        return {
            "verified"  : verified,
            "confidence": confidence,
            "distance"  : round(float(distance), 4),
            "status"    : "verified" if verified else "mismatch",
            "message"   : "Identity confirmed" if verified else "Face does not match registered student",
            "timestamp" : datetime.utcnow().isoformat(),
        }

    except ValueError:
        return {
            "verified"  : False,
            "confidence": 0.0,
            "status"    : "no_face",
            "message"   : "No face detected in frame",
            "timestamp" : datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "verified"  : False,
            "confidence": 0.0,
            "status"    : "error",
            "message"   : str(e),
            "timestamp" : datetime.utcnow().isoformat(),
        }
    finally:
        if tmp_path:
            _cleanup(tmp_path)


def build_face_log_entry(verify_result: dict) -> dict:
    """Returns a clean dict ready to append to exam_session.face_log"""
    return {
        "time"      : verify_result.get("timestamp", datetime.utcnow().isoformat()),
        "status"    : verify_result.get("status", "error"),
        "confidence": verify_result.get("confidence", 0.0),
        "verified"  : verify_result.get("verified", False),
    }


def summarise_face_log(face_log: list) -> dict:
    """
    After exam ends, summarise the face log.
    Returns overall integrity status for the result record.
    """
    if not face_log:
        return {"integrity": "unknown", "verified_pct": 0, "total_checks": 0}

    total    = len(face_log)
    verified = sum(1 for entry in face_log if entry.get("verified"))
    pct      = round((verified / total) * 100, 1)

    if pct >= 80:
        integrity = "high"
    elif pct >= 50:
        integrity = "medium"
    else:
        integrity = "low"

    return {
        "integrity"    : integrity,
        "verified_pct" : pct,
        "total_checks" : total,
        "passed_checks": verified,
    }
