"""
routes/health.py
----------------
GET  /health          — simple liveness check (no auth required)
GET  /health/ready    — readiness check: DB ping + config sanity (no auth)

These endpoints are consumed by Render / Railway / Docker health checks
and any uptime monitoring service (e.g. UptimeRobot, BetterStack).

Response schema:
    {
        "status":    "ok" | "degraded" | "down",
        "checks": {
            "database": "ok" | "error: <msg>",
            "secrets":  "ok" | "warning: <list>"
        },
        "version": "<git sha or package version>"
    }

HTTP status codes:
    200 — healthy
    207 — degraded (some checks failed but app is partially functional)
    503 — down (DB unreachable)
"""
import os
from flask import Blueprint, jsonify, current_app

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def liveness():
    """
    Liveness probe — returns 200 as long as the Flask process is alive.
    Does NOT check the database (intentional: avoids cascading failures
    during DB maintenance restarting the container unnecessarily).
    """
    return jsonify({"status": "ok"}), 200


@health_bp.get("/health/ready")
def readiness():
    """
    Readiness probe — checks:
    1. MongoDB connectivity
    2. Critical config presence (no hardcoded dev secrets in prod)
    """
    from db import ping_db

    checks  = {}
    ok      = True
    warning = False

    # ── DB ping ─────────────────────────────────────────────────────
    try:
        db_up = ping_db()
        checks["database"] = "ok" if db_up else "error: ping returned False"
        if not db_up:
            ok = False
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        ok = False

    # ── Secret sanity (warn only — don't fail liveness for this) ───
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        weak = []
        defaults = {
            "SECRET_KEY":     "dev-secret-change-in-prod",
            "JWT_SECRET_KEY": "jwt-secret-change-in-prod",
            "ADMIN_PASSWORD": "admin123",
        }
        for key, bad_val in defaults.items():
            if current_app.config.get(key) == bad_val:
                weak.append(key)
        if weak:
            checks["secrets"] = f"warning: default values detected for {weak}"
            warning = True
        else:
            checks["secrets"] = "ok"
    else:
        checks["secrets"] = "skipped (non-production)"

    # ── Cloudinary config ────────────────────────────────────────────
    if not current_app.config.get("CLOUDINARY_CLOUD_NAME"):
        checks["storage"] = "warning: CLOUDINARY_CLOUD_NAME not set — file uploads will fail"
        warning = True
    else:
        checks["storage"] = "ok"

    # ── Response ─────────────────────────────────────────────────────
    if not ok:
        status_str = "down"
        http_code  = 503
    elif warning:
        status_str = "degraded"
        http_code  = 207
    else:
        status_str = "ok"
        http_code  = 200

    return jsonify({
        "status": status_str,
        "checks": checks,
        "version": os.getenv("APP_VERSION", "unknown"),
    }), http_code
