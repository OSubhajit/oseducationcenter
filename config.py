import os
import sys
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Core ─────────────────────────────────────────
    SECRET_KEY          = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")
    FLASK_ENV           = os.getenv("FLASK_ENV", "development")
    DEBUG               = FLASK_ENV == "development"

    # ── MongoDB ──────────────────────────────────────
    MONGO_URI           = os.getenv("MONGO_URI", "mongodb://localhost:27017/oseducationcenter")
    # Connection pool + timeout settings (passed via URI options or PyMongo kwargs)
    MONGO_POOL_SIZE         = int(os.getenv("MONGO_POOL_SIZE", 10))
    MONGO_MIN_POOL_SIZE     = int(os.getenv("MONGO_MIN_POOL_SIZE", 2))
    MONGO_CONNECT_TIMEOUT   = int(os.getenv("MONGO_CONNECT_TIMEOUT_MS", 5000))   # ms
    MONGO_SERVER_SELECT_MS  = int(os.getenv("MONGO_SERVER_SELECT_MS", 5000))     # ms
    MONGO_SOCKET_TIMEOUT    = int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", 10000))   # ms

    # ── JWT ──────────────────────────────────────────
    JWT_SECRET_KEY           = os.getenv("JWT_SECRET_KEY", "jwt-secret-change-in-prod")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_HOURS", 8)))
    JWT_TOKEN_LOCATION       = ["headers", "cookies"]
    JWT_COOKIE_SECURE        = False   # overridden to True in ProductionConfig
    JWT_COOKIE_CSRF_PROTECT  = False   # overridden to True in ProductionConfig
    JWT_COOKIE_SAMESITE      = "Lax"

    # ── Rate limiting ─────────────────────────────────
    # Storage URI for Flask-Limiter. Defaults to in-memory (resets on restart).
    # Set RATELIMIT_STORAGE_URI=redis://localhost:6379/0 for persistent rate limits
    # across multiple workers (strongly recommended in production).
    RATELIMIT_STORAGE_URI   = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_STRATEGY      = "fixed-window"
    RATELIMIT_HEADERS_ENABLED = True  # expose X-RateLimit-* response headers

    # Login brute-force: 5 attempts per IP per minute, 20 per hour
    LOGIN_RATE_LIMIT        = os.getenv("LOGIN_RATE_LIMIT", "5 per minute;20 per hour")
    # Forgot/reset-password: stricter, since these send emails and allow
    # account enumeration probing if uncapped.
    PASSWORD_RESET_RATE_LIMIT = os.getenv("PASSWORD_RESET_RATE_LIMIT", "3 per minute;10 per hour")

    # ── Security headers (flask-talisman) ─────────────
    # force_https: redirect all HTTP -> HTTPS at the Flask level. Leave this
    # False (default) if a reverse proxy (nginx/Caddy/etc.) already terminates
    # TLS and forwards to this app over plain HTTP on the internal network —
    # forcing it here too would create a redirect loop or break health checks
    # that hit the app directly over HTTP. Set TALISMAN_FORCE_HTTPS=true only
    # if Flask itself is the TLS endpoint.
    TALISMAN_FORCE_HTTPS = os.getenv("TALISMAN_FORCE_HTTPS", "false").lower() == "true"

    # ── Structured logging ────────────────────────────
    LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO")
    # "json" for structured logs (recommended in production / when shipping
    # to a log aggregator), "text" for human-readable local dev output.
    LOG_FORMAT = os.getenv("LOG_FORMAT", "text")

    # ── Groq (written answer grading) ────────────────
    GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL    = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # ── Cloudinary ───────────────────────────────────
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY    = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

    # ── Email (Flask-Mail) ────────────────────────────
    MAIL_SERVER   = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT     = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS  = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "noreply@oseducationcenter.com")
    MAIL_SUPPRESS_SEND  = not os.getenv("MAIL_USERNAME")   # suppress if not configured

    # ── Sentry ────────────────────────────────────────
    SENTRY_DSN = os.getenv("SENTRY_DSN", "")

    # ── Password reset token TTL ──────────────────────
    PASSWORD_RESET_TOKEN_EXPIRES = int(os.getenv("PASSWORD_RESET_TOKEN_EXPIRES_MINUTES", 30))

    # ── Admin seed ───────────────────────────────────
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    ADMIN_NAME     = os.getenv("ADMIN_NAME", "Admin")
    ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL", "admin@oseducationcenter.com")

    # ── Center info (printed on certificates) ────────
    CENTER_NAME    = os.getenv("CENTER_NAME", "OS Education Center")
    CENTER_ADDRESS = os.getenv("CENTER_ADDRESS", "Assam, India")
    CENTER_WEBSITE = os.getenv("CENTER_WEBSITE", "https://oseducationcenter.com")
    CENTER_PHONE   = os.getenv("CENTER_PHONE", "+91-XXXXXXXXXX")

    # ── Upload limits ─────────────────────────────────
    # Flask-level hard cap (catches oversized requests before they reach Cloudinary)
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", 50)) * 1024 * 1024

    # Per-type file size caps enforced in file_validator.py (bytes)
    MAX_DOCUMENT_SIZE = 20 * 1024 * 1024   # 20 MB for PDFs, Office docs
    MAX_IMAGE_SIZE    = 10 * 1024 * 1024   # 10 MB for images
    MAX_VIDEO_SIZE    = 500 * 1024 * 1024  # 500 MB for videos (overrides MAX_CONTENT_LENGTH)
    MAX_AUDIO_SIZE    = 50 * 1024 * 1024   # 50 MB for audio
    MAX_OTHER_SIZE    = 10 * 1024 * 1024   # 10 MB for misc

    # Allowed file extensions (lowercase, no dot)
    ALLOWED_DOCUMENT_EXTENSIONS = {
        "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "csv", "md", "rtf"
    }
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "svg"}
    ALLOWED_VIDEO_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm", "flv"}
    ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "aac", "ogg", "flac", "m4a"}
    ALLOWED_OTHER_EXTENSIONS = {"zip"}  # archive only, no executables

    # All allowed together (union of the above)
    ALLOWED_EXTENSIONS = (
        ALLOWED_DOCUMENT_EXTENSIONS
        | ALLOWED_IMAGE_EXTENSIONS
        | ALLOWED_VIDEO_EXTENSIONS
        | ALLOWED_AUDIO_EXTENSIONS
        | ALLOWED_OTHER_EXTENSIONS
    )

    # Explicitly blocked dangerous extensions (belt-and-suspenders)
    BLOCKED_EXTENSIONS = {
        "exe", "bat", "cmd", "sh", "ps1", "php", "py", "rb", "js",
        "vbs", "jar", "dll", "msi", "dmg", "apk", "com", "pif",
        "scr", "hta", "wsf", "cpl", "reg",
    }


class ProductionConfig(Config):
    """
    Inherits all keys from Config.
    Overrides security-critical settings for production deployment.
    Set FLASK_ENV=production in your deployment environment to activate this.
    """
    DEBUG                   = False
    JWT_COOKIE_SECURE       = True   # enforce HTTPS
    JWT_COOKIE_CSRF_PROTECT = True   # frontend must send X-CSRF-TOKEN header on mutations
    LOG_FORMAT              = os.getenv("LOG_FORMAT", "json")

    # The frontend reads the csrf_access_token cookie (set by flask_jwt_extended
    # after login) and echoes it as X-CSRF-TOKEN on every POST/PUT/DELETE request.
    # api.js handles this automatically via the _getCsrfToken() helper.


def validate_production_secrets(app):
    """
    Called at startup in production. Raises SystemExit if dangerous defaults are detected.
    This prevents accidental production deployments with dev secrets.
    """
    WEAK_DEFAULTS = {
        "SECRET_KEY":     "dev-secret-change-in-prod",
        "JWT_SECRET_KEY": "jwt-secret-change-in-prod",
        "ADMIN_PASSWORD": "admin123",
    }
    errors = []
    for key, bad_value in WEAK_DEFAULTS.items():
        actual = app.config.get(key, "")
        if actual == bad_value:
            errors.append(f"  {key} is still the insecure default — set a strong random value in .env")

    if errors:
        print("\n[FATAL] Production deployment blocked — insecure defaults detected:")
        for e in errors:
            print(e)
        print("\nGenerate secrets with:  python -c \"import secrets; print(secrets.token_hex(32))\"")
        print("Then set them in your .env file and redeploy.\n")
        sys.exit(1)

    check_rate_limit_storage(app)


def check_rate_limit_storage(app):
    """
    Warn (don't block) if rate limiting will be ineffective in production.

    Flask-Limiter's default "memory://" storage keeps counters in the
    process's own memory. With Gunicorn/uWSGI running multiple worker
    processes, each worker has its OWN counter — a "5 per minute" limit
    becomes effectively "5 * workers per minute" per IP, since requests
    are load-balanced across workers with independent counts. It also
    resets on every deploy/restart.

    For a real multi-worker deployment, set RATELIMIT_STORAGE_URI to a
    shared backend (e.g. redis://host:6379/0) so all workers share counts.
    """
    storage_uri = app.config.get("RATELIMIT_STORAGE_URI", "memory://")
    workers = os.getenv("WEB_CONCURRENCY") or os.getenv("GUNICORN_WORKERS")
    if storage_uri.startswith("memory://"):
        msg = (
            "[WARNING] RATELIMIT_STORAGE_URI is 'memory://' — rate limits "
            "(login throttling, password reset) are per-process. "
        )
        if workers and workers.strip() not in ("0", "1", ""):
            msg += (
                f"With {workers} Gunicorn workers, the effective limit is "
                f"~{workers}x the configured value per IP, and counters "
                "reset on every restart/deploy. "
            )
        else:
            msg += (
                "If you run more than 1 worker process (e.g. gunicorn "
                "--workers > 1), the effective limit multiplies per worker "
                "and counters reset on every restart/deploy. "
            )
        msg += "Set RATELIMIT_STORAGE_URI=redis://<host>:6379/0 for a shared, persistent limit."
        print(msg)
