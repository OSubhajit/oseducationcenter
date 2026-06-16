"""
logging_setup.py
-----------------
Structured logging + per-request correlation IDs.

Why this exists: with Sentry wired up for error monitoring, an error
report tells you WHAT broke, but not which request sequence led there.
Every request gets a request_id (taken from an incoming X-Request-ID
header if present — useful when behind a proxy/load balancer that
already assigns one — otherwise generated). It is:
  - attached to flask.g for use anywhere in the request
  - echoed back in the X-Request-ID response header (so a user/client
    can report it, and it can be correlated with proxy/CDN logs)
  - attached to the Sentry scope as a tag, so a Sentry error and the
    matching access-log line can be found via the same ID
  - included in every log line for that request

LOG_FORMAT=json (the ProductionConfig default) emits one JSON object per
log line — easy to ingest into a log aggregator (CloudWatch, Loki,
Datadog, etc.) and grep/filter by request_id, status, path, etc.
LOG_FORMAT=text (dev default) keeps human-readable console output.
"""
import json
import logging
import sys
import time
import uuid

from flask import g, request


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if not request_id:
            try:
                request_id = getattr(g, "request_id", None)
            except RuntimeError:
                request_id = None
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Allow callers to pass arbitrary structured fields via extra={"extra_fields": {...}}
        extra_fields = getattr(record, "extra_fields", None)
        if extra_fields:
            payload.update(extra_fields)
        return json.dumps(payload)


def configure_logging(app):
    """Set up the root + Flask app logger according to app.config."""
    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    log_format = app.config.get("LOG_FORMAT", "text")

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(name)s: %(message)s "
            "(request_id=%(request_id)s)"
        ))
        # text formatter references %(request_id)s — inject a default via filter
        handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)
    app.logger.setLevel(log_level)


class _RequestIdFilter(logging.Filter):
    """Ensures every LogRecord has a request_id attribute (for the text formatter)."""
    def filter(self, record):
        if not hasattr(record, "request_id"):
            try:
                record.request_id = getattr(g, "request_id", "-")
            except RuntimeError:
                record.request_id = "-"
        return True


def register_request_logging(app):
    """
    Attach before_request / after_request hooks that:
    - assign/propagate a request ID
    - log a structured access-log line per request with timing
    - tag the Sentry scope with the request ID (if Sentry is active)
    """

    @app.before_request
    def _assign_request_id():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        g.request_start_time = time.time()

        try:
            import sentry_sdk
            sentry_sdk.set_tag("request_id", g.request_id)
        except ImportError:
            pass

    @app.after_request
    def _log_request(response):
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        duration_ms = int((time.time() - g.get("request_start_time", time.time())) * 1000)

        app.logger.info(
            "%s %s -> %s (%dms)",
            request.method, request.path, response.status_code, duration_ms,
            extra={
                "request_id": g.get("request_id", "-"),
                "extra_fields": {
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
                },
            },
        )
        return response
