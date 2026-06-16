"""
routes/auth.py
--------------
POST /auth/admin/login      — admin login (rate limited)
POST /auth/student/login    — student login (rate limited)
POST /auth/teacher/login    — teacher login (rate limited)
POST /auth/logout
GET  /auth/me
POST /auth/forgot-password  — request a reset link (student/teacher by email)
POST /auth/reset-password   — consume reset token, set new password
POST /auth/admin/reset-password/<user_type>/<user_id>  — admin force-reset
"""
import os
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, make_response, current_app, url_for
from flask_jwt_extended import (
    create_access_token, jwt_required,
    get_jwt_identity, get_jwt, unset_jwt_cookies, set_access_cookies
)
from functools import wraps
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import bcrypt
from db import get_admin, get_students, get_teachers
from services.email_service import send_password_reset
from extensions import limiter
from validators import safe_str

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ── Helpers ────────────────────────────────────────────────────────────────

def _check_password(plain: str, hashed) -> bool:
    """Handle both str and bytes hash from MongoDB."""
    if isinstance(hashed, str):
        hashed = hashed.encode()
    return bcrypt.checkpw(plain.encode(), hashed)


def _login_rate_limit():
    """Returns the configured login rate-limit string(s) for @limiter.limit().

    Evaluated per-request (Flask-Limiter calls this lazily), so it picks up
    current_app.config — which differs between dev/test/production.
    """
    return current_app.config.get("LOGIN_RATE_LIMIT", "5 per minute;20 per hour")


def _reset_rate_limit():
    return current_app.config.get("PASSWORD_RESET_RATE_LIMIT", "3 per minute;10 per hour")


def _get_reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


# ── Login endpoints ─────────────────────────────────────────────────────────

@auth_bp.post("/admin/login")
@limiter.limit(_login_rate_limit)
def admin_login():
    data = request.get_json(silent=True) or {}
    username = safe_str(data, "username")
    password = safe_str(data, "password", strip=False)

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    admin = get_admin().find_one({"username": username})
    if not admin or not _check_password(password, admin["password_hash"]):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(
        identity=str(admin["_id"]),
        additional_claims={"role": "admin", "name": admin["name"]}
    )

    resp = make_response(jsonify({
        "message": "Login successful",
        "role": "admin",
        "name": admin["name"],
        "token": token
    }))

    # set_access_cookies sets BOTH the httpOnly access_token_cookie AND the
    # JS-readable csrf_access_token cookie (api.js echoes the latter back as
    # X-CSRF-TOKEN on mutations when JWT_COOKIE_CSRF_PROTECT is enabled).
    # A plain resp.set_cookie() here would leave csrf_access_token unset,
    # which silently breaks every mutating request once the frontend stops
    # sending an Authorization header and relies on the cookie.
    set_access_cookies(resp, token)
    return resp, 200


@auth_bp.post("/student/login")
@limiter.limit(_login_rate_limit)
def student_login():
    data       = request.get_json(silent=True) or {}
    identifier = safe_str(data, "identifier")
    password   = safe_str(data, "password", strip=False)

    if not identifier or not password:
        return jsonify({"error": "identifier and password required"}), 400

    student = get_students().find_one({"$or": [{"student_id": identifier}, {"email": identifier}]})
    if not student or not _check_password(password, student["password_hash"]):
        return jsonify({"error": "Invalid credentials"}), 401

    if not student.get("active"):
        return jsonify({"error": "Account inactive. Contact admin."}), 403

    token = create_access_token(
        identity=str(student["_id"]),
        additional_claims={
            "role": "student",
            "student_id": student["student_id"],
            "name": student["name"]
        }
    )

    resp = make_response(jsonify({
        "message": "Login successful",
        "role": "student",
        "name": student["name"],
        "student_id": student["student_id"],
        "token": token
    }))

    set_access_cookies(resp, token)
    return resp, 200


@auth_bp.post("/teacher/login")
@limiter.limit(_login_rate_limit)
def teacher_login():
    data       = request.get_json(silent=True) or {}
    identifier = safe_str(data, "identifier")
    password   = safe_str(data, "password", strip=False)

    if not identifier or not password:
        return jsonify({"error": "identifier and password required"}), 400

    teacher = get_teachers().find_one({"$or": [{"teacher_id": identifier}, {"email": identifier}]})
    if not teacher or not _check_password(password, teacher["password_hash"]):
        return jsonify({"error": "Invalid credentials"}), 401

    if not teacher.get("active"):
        return jsonify({"error": "Account inactive. Contact admin."}), 403

    token = create_access_token(
        identity=str(teacher["_id"]),
        additional_claims={
            "role": "teacher",
            "teacher_id": teacher["teacher_id"],
            "name": teacher["name"],
            "teaches": teacher.get("teaches", [])
        }
    )

    resp = make_response(jsonify({
        "message": "Login successful",
        "role": "teacher",
        "name": teacher["name"],
        "teacher_id": teacher["teacher_id"],
        "token": token
    }))

    set_access_cookies(resp, token)
    return resp, 200


@auth_bp.post("/logout")
def logout():
    resp = make_response(jsonify({"message": "Logged out"}))
    unset_jwt_cookies(resp)
    return resp, 200


@auth_bp.get("/me")
@jwt_required()
def me():
    claims = get_jwt()
    return jsonify({
        "id":         get_jwt_identity(),
        "role":       claims.get("role"),
        "name":       claims.get("name"),
        "student_id": claims.get("student_id"),
        "teacher_id": claims.get("teacher_id"),
        "teaches":    claims.get("teaches", [])
    }), 200


# ── Password reset — self-service (email token flow) ────────────────────────

@auth_bp.post("/forgot-password")
@limiter.limit(_reset_rate_limit)
def forgot_password():
    """
    Issue a time-limited reset link.
    Body: { "email": "...", "role": "student" | "teacher" }

    Always returns 200 (prevents user enumeration by timing/response).
    The email is only sent if the account is found.
    """
    data  = request.get_json(silent=True) or {}
    email = safe_str(data, "email").lower()
    role  = safe_str(data, "role").lower()

    _GENERIC_OK = {"message": "If that email is registered you will receive a reset link shortly."}, 200

    if not email or role not in ("student", "teacher"):
        return jsonify(_GENERIC_OK[0]), 200

    # Look up the user
    collection = get_students() if role == "student" else get_teachers()
    user = collection.find_one({"email": email})

    if user and user.get("active"):
        s     = _get_reset_serializer()
        token = s.dumps({"email": email, "role": role})
        expires = current_app.config.get("PASSWORD_RESET_TOKEN_EXPIRES", 30)

        # Build reset link — in prod this should be an absolute URL
        # pointing at the frontend reset page, e.g.:
        #   https://oseducationcenter.com/reset-password?token=<token>
        reset_link = f"{request.host_url.rstrip('/')}/reset-password?token={token}"

        send_password_reset(
            recipient_email=email,
            reset_link=reset_link,
            name=user.get("name", "User"),
            expires_minutes=expires,
        )

    return jsonify(_GENERIC_OK[0]), 200


@auth_bp.post("/reset-password")
@limiter.limit("5 per minute")
def reset_password():
    """
    Consume a reset token and set a new password.
    Body: { "token": "...", "new_password": "..." }
    """
    data         = request.get_json(silent=True) or {}
    token        = safe_str(data, "token")
    new_password = safe_str(data, "new_password", strip=False)

    if not token or not new_password:
        return jsonify({"error": "token and new_password are required"}), 400

    if len(new_password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    expires = current_app.config.get("PASSWORD_RESET_TOKEN_EXPIRES", 30)
    s = _get_reset_serializer()

    try:
        payload = s.loads(token, max_age=expires * 60)
    except SignatureExpired:
        return jsonify({"error": "Reset link has expired. Please request a new one."}), 400
    except BadSignature:
        return jsonify({"error": "Invalid or tampered reset link."}), 400

    email = payload.get("email")
    role  = payload.get("role")

    collection = get_students() if role == "student" else get_teachers()
    user = collection.find_one({"email": email})
    if not user:
        return jsonify({"error": "Account not found."}), 404

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    collection.update_one({"email": email}, {"$set": {"password_hash": new_hash}})

    return jsonify({"message": "Password has been reset successfully. You can now log in."}), 200


# ── Admin force-reset (no email needed) ─────────────────────────────────────

@auth_bp.post("/admin/reset-password/<user_type>/<user_id>")
@jwt_required()
def admin_force_reset(user_type, user_id):
    """
    Admin can set a temporary password for any student or teacher.
    Body: { "new_password": "..." }
    Requires role=admin JWT.
    """
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    if user_type not in ("student", "teacher"):
        return jsonify({"error": "user_type must be 'student' or 'teacher'"}), 400

    # Sanitise user_id: only allow alphanumeric and hyphens (matches OSEC-STU-xxxxx pattern)
    import re
    if not re.match(r'^[A-Za-z0-9\-]{1,64}$', user_id):
        return jsonify({"error": "Invalid user ID format"}), 400

    data         = request.get_json(silent=True) or {}
    new_password = safe_str(data, "new_password", strip=False)
    if not new_password or len(new_password) < 8:
        return jsonify({"error": "new_password must be at least 8 characters"}), 400

    collection = get_students() if user_type == "student" else get_teachers()
    id_field   = "student_id" if user_type == "student" else "teacher_id"
    user       = collection.find_one({id_field: user_id})
    if not user:
        return jsonify({"error": f"{user_type.capitalize()} not found"}), 404

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    collection.update_one({id_field: user_id}, {"$set": {"password_hash": new_hash}})

    return jsonify({"message": f"Password reset for {user_type} {user_id}."}), 200


# ── Auth decorators (imported by other blueprints) ──────────────────────────

def teacher_or_admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("role") not in ["teacher", "admin"]:
            return jsonify({"error": "Teacher or admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def is_teacher_authorized_for_course(course_id):
    claims = get_jwt()
    role   = claims.get("role")
    if role == "admin":
        return True
    if role == "teacher":
        return course_id in claims.get("teaches", [])
    return False


def get_actor_id():
    claims = get_jwt()
    if claims.get("role") == "teacher":
        return claims.get("teacher_id")
    return "admin"


def get_teacher_teaches():
    claims = get_jwt()
    if claims.get("role") == "teacher":
        return claims.get("teaches", [])
    return []
