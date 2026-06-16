# OSEC Production Deployment Guide

## Pre-deploy checklist

- [ ] `FLASK_ENV=production` in environment
- [ ] `SECRET_KEY` and `JWT_SECRET_KEY` are strong random hex strings (not defaults)
- [ ] `ADMIN_PASSWORD` is changed from default
- [ ] `MONGO_URI` points to production Atlas cluster
- [ ] Cloudinary credentials set
- [ ] `python app.py --seed` has been run once to create admin + seed courses
- [ ] `python -c "from db import *; from app import create_app; a=create_app(); \
    ctx=a.app_context(); ctx.push(); create_indexes()"` has been run to create all DB indexes

---

## Hosting options

### Render (recommended for new deploys)

1. Connect GitHub repo → New Web Service → Python 3.11
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn app:create_app() --workers 1 --bind 0.0.0.0:$PORT --timeout 120`
4. Add all env vars from `.env.example` in the Render dashboard
5. Set FLASK_ENV=production

**Important — rate limiting across workers:**
The default `RATELIMIT_STORAGE_URI=memory://` keeps login-attempt counters
in each worker process's own memory. With `--workers 1` (the default
above), there's exactly one counter and the configured limit (e.g. "5 per
minute") is accurate. **If you increase `--workers` above 1, the limit
becomes inaccurate — `N workers x configured limit` per IP** (since each
worker independently allows up to the limit before blocking), and all
counters reset on every restart/deploy.

Before scaling to 2+ workers:
1. Add a Redis instance (Render/Railway both offer a one-click Redis add-on).
2. Set `RATELIMIT_STORAGE_URI=redis://<redis-url>` so all workers share one
   counter.
3. Then increase `--workers` to 2+.

A single worker comfortably handles a few dozen concurrent users (the
target for a small school deployment) — only scale workers once you've
set up shared rate-limit storage.

### Railway

Same as Render; use the same start command. Railway auto-injects `PORT`.

---

## MongoDB Atlas — indexes & backup

### Create indexes (run after first deploy)

```bash
# Via the Render/Railway shell or locally against prod URI
MONGO_URI=<prod-uri> FLASK_ENV=production python -c "
from app import create_app
from db import create_indexes
app = create_app()
with app.app_context():
    create_indexes()
    print('Done')
"
```

### Recommended Atlas indexes (verify in Atlas UI → Collections → Indexes)

The `create_indexes()` function in `db.py` creates these automatically, but confirm they are present:

| Collection              | Index fields                          | Purpose                          |
|-------------------------|---------------------------------------|----------------------------------|
| students                | student_id (unique)                   | Login / lookup                   |
| students                | email (unique)                        | Login                            |
| students                | enrolled_courses                      | Resource/assignment access checks|
| assignments             | course_id                             | Teacher dashboard list           |
| assignments             | created_by                            | Teacher own-assignment filter    |
| assignment_submissions  | (assignment_id, student_id) compound  | One-submission-per-student guard |
| assignment_submissions  | student_id                            | Student submission history       |
| resources               | course_id                             | Student resource listing         |
| resources               | uploaded_by                           | Teacher dashboard count          |
| fees                    | student_id                            | Fee lookup per student           |

### Backup strategy

**Atlas M0 (free tier):** No automated backups. Use scheduled exports.

```bash
# Export entire database to BSON (run from cron or Render scheduled job)
mongodump --uri="<MONGO_URI>" --out="backup_$(date +%Y%m%d_%H%M%S)" --gzip

# Restore
mongorestore --uri="<MONGO_URI>" --gzip backup_<timestamp>/
```

**Atlas M10+ (paid):** Enable Continuous Cloud Backup in Atlas UI:
- Atlas → Clusters → Backup → Configure → Continuous Backup
- Retention: 7 days (free), up to 1 year (paid)
- Point-in-time restore to any second within the retention window

**Recommended minimum for a live school:**
- Daily automated snapshot (mongodump → upload to S3 / Google Cloud Storage)
- Weekly full backup retained for 30 days
- Monthly full backup retained for 12 months

Example cron script (Render cron job or GitHub Actions scheduled workflow):

```bash
#!/bin/bash
DATE=$(date +%Y%m%d)
mongodump --uri="$MONGO_URI" --archive="/tmp/osec_backup_$DATE.gz" --gzip
# Upload to S3:
aws s3 cp "/tmp/osec_backup_$DATE.gz" "s3://<your-bucket>/osec-backups/$DATE.gz"
# Keep only last 30 days on S3:
aws s3 ls "s3://<your-bucket>/osec-backups/" | awk '{print $4}' | sort | head -n -30 | xargs -I{} aws s3 rm "s3://<your-bucket>/osec-backups/{}"
```

---

## Health checks

| Endpoint       | Purpose                                | Expected status |
|----------------|----------------------------------------|-----------------|
| GET /health    | Liveness (is Flask alive?)             | 200 always      |
| GET /health/ready | Readiness (DB + secrets + storage) | 200 / 207 / 503 |

Configure your uptime monitor (UptimeRobot, BetterStack, etc.) to ping `/health/ready` every 5 minutes.  
Set alert threshold: 503 → immediate alert; 207 → warning email.

---

## Error monitoring (Sentry)

1. Create a project at [sentry.io](https://sentry.io) (free hobby plan covers 5 k errors/month)
2. Copy the DSN
3. Set `SENTRY_DSN=https://...` in your env
4. Errors will appear in the Sentry dashboard automatically
5. Recommended alerts: P0 = any unhandled 500; P1 = login error spike

---

## Gunicorn tuning

```bash
# Single worker (default, no extra infra needed) — fine for a few dozen
# concurrent users. Rate-limit storage="memory://" is accurate at 1 worker.
gunicorn "app:create_app()" \
  --workers 1 \
  --worker-class sync \
  --timeout 120 \
  --bind 0.0.0.0:$PORT \
  --access-logfile - \
  --error-logfile -

# Scaling to 2+ workers — REQUIRES Redis first (see "Rate limiting in
# production" below), otherwise login-attempt limits become inaccurate
# (effectively N workers x configured limit):
#   RATELIMIT_STORAGE_URI=redis://<redis-url>
# gunicorn "app:create_app()" --workers 2 --worker-class sync --timeout 120 \
#   --bind 0.0.0.0:$PORT --access-logfile - --error-logfile -

# If you have Redis and want async upload support:
# --worker-class gevent --worker-connections 100
```

---

## JWT secret rotation

Rotating `JWT_SECRET_KEY` invalidates ALL active sessions (all users get logged out).  
Steps:
1. Set new `JWT_SECRET_KEY` in env
2. Redeploy
3. Inform users they will need to log in again

To rotate without a forced logout, implement a JWT denylist (out of scope for v1).

---

## Cloudinary — security notes

- OSEC uses `type="upload"` (public-read URLs). Access control is enforced at the Flask API layer via JWT + enrollment checks.
- The Cloudinary folder structure is `osec/uploads/` for resources and `assignments/` for submissions.
- Cloudinary's allowed formats can be restricted further in the Cloudinary dashboard under Settings → Upload → Upload presets.
- Enable Cloudinary's malware scanning add-on (free tier available) for extra defense against malicious file uploads.

---

## Authentication & CSRF architecture

The JWT lives **only** in an httpOnly `access_token_cookie` set by
`/api/auth/{admin,student,teacher}/login` via flask-jwt-extended's
`set_access_cookies()`. The browser sends it automatically on every
same-origin request — `static/js/api.js` does not store the token in
localStorage or send an `Authorization` header for normal page use.

`localStorage` only holds non-sensitive UI hints (`osec_role`, `osec_name`,
`osec_student_id`, `osec_teacher_id`) used for client-side routing
(`requireAdmin()`/`requireStudent()`/`requireTeacher()`) and greetings. These
are NOT bearer credentials — an XSS payload reading them gets a role/display
name, not something that can be replayed to impersonate the user. This is a
deliberate hardening over storing the JWT itself in localStorage (a stored-XSS
token-theft vector).

`set_access_cookies()` also sets a second, JS-readable `csrf_access_token`
cookie. `api.js`'s `_getCsrfToken()` reads it and sends it back as
`X-CSRF-TOKEN` on every `POST`/`PUT`/`DELETE` — this is the standard
double-submit-cookie CSRF defense, and is REQUIRED for mutations to succeed
once `JWT_COOKIE_CSRF_PROTECT=True` (the `ProductionConfig` default). If you
see `401 {"msg": "Missing CSRF token"}` on admin/teacher/student actions,
check that login went through `/api/auth/*/login` (not a stale session) and
that cookies are enabled for your domain.

The `token` field still returned in login JSON responses is for non-browser
API clients (curl/Postman/scripts) using `Authorization: Bearer <token>` —
header-based auth bypasses the cookie-CSRF check entirely (CSRF only applies
to cookie-authenticated requests), so this remains a simple path for
server-to-server/API use.

---



The `RATELIMIT_STORAGE_URI` env var controls where rate limit state is stored:

| URI scheme      | Works with multiple workers? | Notes                       |
|-----------------|------------------------------|-----------------------------|
| `memory://`     | ❌ (per-worker)               | OK for single-worker (`--workers 1`) deployments |
| `redis://...`   | ✅                            | Add Redis service on Render/Railway, then bump `--workers` |

At startup, `validate_production_secrets()` checks `RATELIMIT_STORAGE_URI`
and `WEB_CONCURRENCY`/`GUNICORN_WORKERS` and prints a `[WARNING]` if
`memory://` is in use with more than one worker configured — watch for this
in your deploy logs.

Limits applied (all per source IP, both configurable in `.env`):
- Login (`/auth/admin/login`, `/auth/student/login`, `/auth/teacher/login`):
  `LOGIN_RATE_LIMIT`, default **5 per minute; 20 per hour**.
- Password reset (`/auth/forgot-password`): `PASSWORD_RESET_RATE_LIMIT`,
  default **3 per minute; 10 per hour**.
- `/auth/reset-password`: fixed at 5 per minute.

These are enforced via `@limiter.limit(...)` decorators in `routes/auth.py`,
using the shared `Limiter` instance in `extensions.py` (required so the
decorator — not a runtime call — registers with Flask-Limiter's
before/after-request hooks).

---

## Security headers (flask-talisman)

Every response gets `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`, a `Content-Security-Policy`,
and (over HTTPS) `Strict-Transport-Security`.

The CSP allows `'unsafe-inline'` for `script-src`/`style-src` because every
template uses inline `<script>` blocks and inline `style=""` attributes (no
build step). This is a deliberate, documented tradeoff — it still gives a
same-origin `default-src`, blocks framing (`frame-ancestors 'none'`), and adds
HSTS, but does not fully mitigate injected-script XSS the way a nonce-based
CSP would. Migrating to per-template nonces is a larger follow-up.

`TALISMAN_FORCE_HTTPS=false` by default — leave this alone if a reverse proxy
(Render/Railway's edge, nginx, Caddy) terminates TLS and forwards plain HTTP
internally (the normal setup). Only set it `true` if Flask itself terminates
TLS.

---

## Structured logging & request IDs

`LOG_FORMAT=json` (the `ProductionConfig` default) emits one JSON log line per
request: `{"timestamp", "level", "request_id", "method", "path", "status",
"duration_ms", "remote_addr", ...}`. Every response also gets an
`X-Request-ID` header (generated, or echoed back if the client/proxy sent
one).

When a Sentry error fires, `request_id` is attached as a Sentry tag — search
your log aggregator for that same ID to see the full request context (method,
path, timing, and any app log lines for that request).

`LOG_FORMAT=text` / `LOG_LEVEL=DEBUG` for local development gives
human-readable console output.
