"""
app.py — Flask application factory + seed runner
Run:   python app.py
Seed:  python app.py --seed
"""
import os
import sys
from flask import Flask, jsonify, g
from flask_jwt_extended import JWTManager
from flask_talisman import Talisman
from config import Config, ProductionConfig, validate_production_secrets
from db import init_mongo, create_indexes
from extensions import limiter
from logging_setup import configure_logging, register_request_logging

# ── Sentry (optional — only initialised when SENTRY_DSN is set) ────────────
def _init_sentry(dsn: str, env: str):
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.pymongo import PyMongoIntegration
        sentry_sdk.init(
            dsn=dsn,
            environment=env,
            integrations=[FlaskIntegration(), PyMongoIntegration()],
            traces_sample_rate=0.1,   # 10 % of requests for performance tracing
            send_default_pii=False,   # no PII in error reports
        )
        print("[Sentry] Error monitoring active.")
    except ImportError:
        print("[Sentry] sentry-sdk not installed — error monitoring disabled.")


def create_app():
    app = Flask(__name__)

    # ── Config ──────────────────────────────────────────────────────────
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        app.config.from_object(ProductionConfig)
        validate_production_secrets(app)
    else:
        app.config.from_object(Config)

    # ── Structured logging + request correlation IDs ─────────────────────
    configure_logging(app)
    register_request_logging(app)

    # ── Sentry ──────────────────────────────────────────────────────────
    _init_sentry(app.config.get("SENTRY_DSN", ""), env)

    # ── Security headers (Talisman) ───────────────────────────────────────
    # CSP allows 'unsafe-inline' for script-src/style-src because every page
    # in this app uses inline <script> blocks and inline style="" attributes
    # (no build step / bundler). This is a known tradeoff: it still gives us
    # X-Frame-Options, X-Content-Type-Options, Referrer-Policy, HSTS (in
    # prod), and a same-origin-only default-src, but does not fully mitigate
    # injected-script XSS the way a nonce-based CSP would. Migrating every
    # template to nonce-based inline scripts is a larger follow-up.
    csp = {
        "default-src": "'self'",
        "script-src": "'self' 'unsafe-inline'",
        "style-src": "'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src": "'self' https://fonts.gstatic.com",
        "img-src": "'self' data: https://res.cloudinary.com",
        "connect-src": "'self'",
        "object-src": "'none'",
        "base-uri": "'self'",
        "frame-ancestors": "'none'",
    }
    Talisman(
        app,
        force_https=app.config.get("TALISMAN_FORCE_HTTPS", False),
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        strict_transport_security_include_subdomains=True,
        frame_options="DENY",
        content_security_policy=csp,
        content_security_policy_nonce_in=None,
        referrer_policy="strict-origin-when-cross-origin",
        session_cookie_secure=app.config.get("JWT_COOKIE_SECURE", False),
    )

    # ── Extensions ──────────────────────────────────────────────────────
    init_mongo(app)     # PyMongo with connection pool + timeouts
    JWTManager(app)

    # Flask-Limiter — storage_uri is read from app.config["RATELIMIT_STORAGE_URI"]
    # (set by Config/ProductionConfig) since the Limiter instance in
    # extensions.py was constructed without one.
    limiter.init_app(app)

    # Flask-Mail
    from services.email_service import mail
    mail.init_app(app)

    # ── Error handlers ────────────────────────────────────────────────
    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({
            "error": "Too many requests. Please wait a moment before trying again.",
            "retry_after": getattr(e, "retry_after", None),
        }), 429

    @app.errorhandler(413)
    def payload_too_large(e):
        max_mb = app.config.get("MAX_CONTENT_LENGTH", 50 * 1024 * 1024) // (1024 * 1024)
        return jsonify({"error": f"File is too large. Maximum allowed is {max_mb} MB."}), 413

    # ── Blueprints ────────────────────────────────────────────────────
    from routes.health import health_bp
    app.register_blueprint(health_bp)

    from routes.pages import pages_bp
    app.register_blueprint(pages_bp)

    from routes.questions import questions_bp
    app.register_blueprint(questions_bp, url_prefix="/api/questions")

    from routes.assignments import assignments_bp
    app.register_blueprint(assignments_bp, url_prefix="/api/assignments")

    from routes.resources import resources_bp
    app.register_blueprint(resources_bp, url_prefix="/api/resources")

    from routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/api/auth")

    from routes.admin import admin_bp
    app.register_blueprint(admin_bp,   url_prefix="/api/admin")

    from routes.exam import exam_bp
    app.register_blueprint(exam_bp,    url_prefix="/api/exam")

    from routes.student import student_bp
    app.register_blueprint(student_bp, url_prefix="/api/student")

    from routes.teacher import teacher_bp
    app.register_blueprint(teacher_bp, url_prefix="/api/teacher")

    from routes.verify import verify_bp
    app.register_blueprint(verify_bp,  url_prefix="/api/verify")

    return app


def seed_database(app):
    """
    First-run seed:
    - Creates admin account
    - Inserts all 46 courses (skips duplicates)
    """
    from models.schemas import build_admin, COURSES_SEED
    from db import get_admin, get_courses

    with app.app_context():
        create_indexes()

        # ── Admin ─────────────────────────────────────────
        existing = get_admin().find_one({"username": app.config["ADMIN_USERNAME"]})
        if not existing:
            admin_doc = build_admin(
                app.config["ADMIN_USERNAME"],
                app.config["ADMIN_PASSWORD"],
                app.config["ADMIN_NAME"],
                app.config["ADMIN_EMAIL"],
            )
            get_admin().insert_one(admin_doc)
            print(f"[Seed] Admin created: {app.config['ADMIN_USERNAME']}")
        else:
            print("[Seed] Admin already exists — skipped.")

        # ── Courses ───────────────────────────────────────
        inserted = 0
        for course in COURSES_SEED:
            if not get_courses().find_one({"course_id": course["course_id"]}):
                get_courses().insert_one(course)
                inserted += 1
        print(f"[Seed] Courses inserted: {inserted} / {len(COURSES_SEED)}")
        print("[Seed] Done.")


if __name__ == "__main__":
    app = create_app()

    if "--seed" in sys.argv:
        seed_database(app)
    else:
        print("=" * 50)
        print("  OS Education Center — Backend")
        print("  Running on http://localhost:5000")
        print("  First time? Run:  python app.py --seed")
        print("=" * 50)
        app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=5000)
