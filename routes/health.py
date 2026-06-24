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
<<<<<<< HEAD
from extensions import limiter
=======
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
<<<<<<< HEAD
@limiter.exempt   # health checks must never be blocked by rate limits
=======
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c
def liveness():
    """
    Liveness probe — returns 200 as long as the Flask process is alive.
    Does NOT check the database (intentional: avoids cascading failures
    during DB maintenance restarting the container unnecessarily).
    """
    return jsonify({"status": "ok"}), 200


@health_bp.get("/health/ready")
<<<<<<< HEAD
@limiter.exempt   # health checks must never be blocked by rate limits
=======
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c
def readiness():
    """
    Readiness probe — checks:
    1. MongoDB connectivity
    2. Critical config presence (no hardcoded dev secrets in prod)
<<<<<<< HEAD
    3. Talisman security-header middleware is active
    4. Flask-Limiter storage backend is reachable
=======
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c
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

<<<<<<< HEAD
    # ── Fix 5a: Talisman security-header middleware ─────────────────
    # Talisman wraps app.wsgi_app; its class name is 'Talisman'.
    # If the middleware is missing, CSP / HSTS / X-Frame-Options headers
    # are silently absent — the app looks secure in code but isn't in practice.
    try:
        talisman_active = "Talisman" in type(current_app.wsgi_app).__name__
        if talisman_active:
            force_https = current_app.config.get("TALISMAN_FORCE_HTTPS", False)
            checks["security_headers"] = (
                f"ok (Talisman active, force_https={force_https})"
            )
            if env == "production" and not force_https:
                checks["security_headers"] += (
                    " — warning: TALISMAN_FORCE_HTTPS=false in production; "
                    "ensure your reverse proxy enforces HTTPS"
                )
                warning = True
        else:
            checks["security_headers"] = (
                "error: Talisman middleware not detected — "
                "CSP/HSTS/X-Frame-Options headers are NOT being set"
            )
            ok = False
    except Exception as e:
        checks["security_headers"] = f"error checking Talisman: {e}"
        warning = True

    # ── Fix 5b: Rate-limiter storage reachability ───────────────────
    # A cold storage-probe failure is the most common cause of the
    # "limiter registers but doesn't block" no-op bug (swallow_errors
    # hides storage errors; setting swallow_errors=False makes them
    # visible, but we also surface the storage status here for ops).
    try:
        storage_uri = current_app.config.get("RATELIMIT_STORAGE_URI", "memory://")
        scheme      = storage_uri.split("://")[0]

        if storage_uri.startswith("memory://"):
            worker_count = os.getenv("WEB_CONCURRENCY") or os.getenv("GUNICORN_WORKERS", "1")
            if env == "production" and str(worker_count).strip() not in ("", "0", "1"):
                checks["rate_limiter"] = (
                    f"warning: in-memory storage with {worker_count} workers — "
                    "each worker has independent counters; set RATELIMIT_STORAGE_URI "
                    "to a Redis URL for a shared counter"
                )
                warning = True
            else:
                checks["rate_limiter"] = f"ok (storage: {scheme})"
        else:
            # For Redis / Memcached, do a quick ping via the limiter's storage
            try:
                limiter._storage.check()   # raises if unreachable
                checks["rate_limiter"] = f"ok (storage: {scheme}, reachable)"
            except Exception as storage_err:
                checks["rate_limiter"] = f"error: {scheme} storage unreachable — {storage_err}"
                ok = False
    except Exception as e:
        checks["rate_limiter"] = f"error checking rate-limiter storage: {e}"
        warning = True

=======
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c
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
