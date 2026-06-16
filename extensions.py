"""
extensions.py
--------------
Shared Flask extension instances.

These are created here WITHOUT an app bound, so both app.py and any
route blueprint can import them without causing circular imports.
app.py is responsible for calling .init_app(app) on each of these
inside create_app().

Why this file exists:
Flask-Limiter's @limiter.limit(...) MUST be applied as a decorator at
route-registration time — Flask-Limiter hooks into the request via
before_request/after_request handlers that look up limits registered
against the matched view function. Calling limiter.limit(...)(fn)()
dynamically inside a request handler does NOT register anything with
that machinery and silently does nothing (this was the bug in the
previous implementation — login endpoints were unprotected despite
looking rate-limited).

To use @limiter.limit(...) as a decorator in routes/auth.py, that
module needs to import the SAME Limiter instance that app.py calls
init_app() on. Defining it in app.py and importing it from routes/auth.py
would create a circular import (app.py imports routes.auth, which would
import app). Defining it here breaks the cycle.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# storage_uri is intentionally left unset here — app.py sets
# app.config["RATELIMIT_STORAGE_URI"] before calling limiter.init_app(app),
# and Flask-Limiter reads RATELIMIT_STORAGE_URI from app.config at init time
# when no storage_uri was passed to the constructor.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],            # no global default — limits are applied per-route
    headers_enabled=True,         # expose X-RateLimit-* response headers
)
