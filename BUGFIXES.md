# OSEC Production Readiness — Fix Log

## v7 (Production Hardening)

### Security fixes

**1. Rate limiting on login endpoints** ✅
- Added Flask-Limiter (`requirements.txt`)
- Default: 5 attempts/IP/minute, 20/IP/hour (configurable via `LOGIN_RATE_LIMIT` env var)
- Applies to all three login endpoints: `/api/auth/admin/login`, `/api/auth/student/login`, `/api/auth/teacher/login`
- Tunable to Redis-backed storage for multi-worker deployments via `RATELIMIT_STORAGE_URI`
- 429 responses return a human-readable JSON error

**2. CSRF protection** ✅
- `JWT_COOKIE_CSRF_PROTECT=True` was already in `ProductionConfig`; now `api.js` reads the `csrf_access_token` cookie and sends it as `X-CSRF-TOKEN` on all mutations (POST/PUT/DELETE/PATCH)
- `_getCsrfToken()` helper added to `api.js`

**3. JWT secret weak-default guard** ✅
- `validate_production_secrets()` in `config.py` runs at startup in `FLASK_ENV=production`
- Calls `sys.exit(1)` if `SECRET_KEY`, `JWT_SECRET_KEY`, or `ADMIN_PASSWORD` are still default values
- `.env.example` updated with rotation instructions and `APP_VERSION` hook

**4. File upload MIME + extension validation** ✅
- New `services/file_validator.py` — pure-Python `filetype` library for magic-byte MIME detection (no libmagic)
- Checks: double-extension attacks, extension allowlist, per-type extension check, MIME verification, per-type size caps
- Wired into `/api/resources/upload` (resources.py) and `/<assignment_id>/submit` (assignments.py)
- `MAX_CONTENT_LENGTH` global cap reduced to configurable 50 MB default (was hardcoded 100 MB)
- Per-type caps: document 20 MB, image 10 MB, video 500 MB, audio 50 MB, other 10 MB
- `BLOCKED_EXTENSIONS`: exe, bat, cmd, sh, ps1, php, py, rb, js, vbs, jar, dll, msi, dmg, apk, etc.
- Flask 413 handler added to return a clean JSON error (not an HTML exception page)

**5. ID sanitization in delete_course / delete_batch** ✅
- `_validate_osec_id()` helper added to `routes/admin.py`
- Rejects IDs that don't match `^[A-Za-z0-9\-]{1,64}$`
- Prevents path-traversal and NoSQL injection via URL-encoded characters in route params

---

### API route verification

All four routes called from the teacher/student pages exist and are confirmed:
- `POST /api/resources/upload` → `upload_resource_endpoint()` in routes/resources.py ✅
- `GET  /api/resources/course/<id>` → `get_resources_for_course_endpoint()` in routes/resources.py ✅
- `GET  /api/assignments/my/submissions` → `my_submissions_endpoint()` in routes/assignments.py ✅
- `PUT  /api/assignments/submissions/<id>/grade` → `grade_submission_endpoint()` in routes/assignments.py ✅
- `GET  /api/teacher/dashboard` → returns `courses_taught` ✅

---

### Input validation

**Assignment max_score / due_date** — already validated in `services/assignment_service.py::_validate_assignment_data()`:
- `due_date`: ISO 8601 parse + must-be-future check ✅
- `max_points`: positive number check ✅
- Update path (`update_assignment()`) also re-validates both fields ✅

---

### Missing features added

**6. Password reset flow** ✅
- Self-service: `POST /api/auth/forgot-password` + `POST /api/auth/reset-password`
- Uses `itsdangerous.URLSafeTimedSerializer` (signed + time-limited token, 30 min default)
- Sends email via Flask-Mail (suppressed if `MAIL_USERNAME` not set — no breaking change)
- Admin force-reset: `POST /api/auth/admin/reset-password/<student|teacher>/<user_id>` (admin JWT required)
- Enumeration-safe: `forgot-password` always returns 200 regardless of whether email is found
- Rate-limited: 3 requests/minute on the forgot-password endpoint

**7. Email notifications** ✅
- New `services/email_service.py` (Flask-Mail)
- `send_grade_posted()` called in `grade_submission_endpoint()` — student notified when graded
- `send_assignment_due_reminder()` — callable from a future cron job / Render scheduled task
- `send_password_reset()` — used by forgot-password flow
- `send_welcome()` — callable when creating new student/teacher accounts
- All functions are no-ops when `MAIL_USERNAME` is not set (`MAIL_SUPPRESS_SEND=True`)

**8. Resubmission guard** ✅ (was already implemented)
- Application-level check in `submit_submission()`: raises ValueError if submission exists
- Database-level: compound unique index `(assignment_id, student_id)` closes race window
- Confirmed working — no change needed

**9. File storage (Cloudinary)** ✅ (was already implemented)
- `services/storage_service.py` uses Cloudinary — works on Render/Railway
- No local disk dependency

**10. Pagination on submissions** ✅ (was already implemented)
- `get_submissions_for_assignment()` and `get_student_submissions()` both paginate

---

### Ops / deploy fixes

**11. Error monitoring (Sentry)** ✅
- `sentry-sdk[flask]` added to `requirements.txt`
- Initialised in `app.py::_init_sentry()` — no-op if `SENTRY_DSN` env var is not set
- `PyMongoIntegration` included for DB error traces
- 10% performance tracing sample rate (configurable)

**12. MongoDB connection pooling + timeouts** ✅
- `db.py::init_mongo()` injects pool params into the MONGO_URI if not already present:
  - `maxPoolSize`, `minPoolSize`, `connectTimeoutMS`, `serverSelectionTimeoutMS`, `socketTimeoutMS`, `retryWrites`, `retryReads`
- All tunable via env vars

**13. Additional DB indexes** ✅
- `assignments.created_by` — teacher dashboard filter
- `assignments.(course_id, active)` compound — list-by-course query
- `resources.uploaded_by` — teacher dashboard count
- `resources.(course_id, active)` compound — student resource listing
- `students.enrolled_courses` — course enrollment checks
- `students.active` — active student filter
- `results.student_id`, `results.exam_id`, `fees.student_id`, `fees.status`
- `assignment_submissions.submitted_at` — pagination sort

**14. Health check endpoint** ✅
- `GET /health` — liveness probe (always 200 while Flask is alive)
- `GET /health/ready` — readiness: pings MongoDB, checks secrets, checks Cloudinary config
- Returns `{"status": "ok"|"degraded"|"down", "checks": {...}}`
- HTTP 200 / 207 / 503 for monitoring tool threshold alerting
- Blueprint registered without `/api` prefix so uptime monitors can reach it cleanly

**15. Backup strategy** ✅
- Documented in `DEPLOY.md`:
  - Atlas M0: `mongodump` cron → upload to S3/GCS
  - Atlas M10+: Continuous Cloud Backup (point-in-time restore)
  - 30-day rolling retention script included
