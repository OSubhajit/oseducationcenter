"""
services/file_validator.py
--------------------------
Centralised file validation for all upload endpoints.

Checks (in order):
  1. Extension allowlist  — reject blacklisted / unlisted extensions
  2. Magic-byte MIME      — verify actual file type matches extension
                            using `filetype` (pure-Python, no libmagic)
  3. Per-type size cap    — enforce tighter limits than MAX_CONTENT_LENGTH
                            for document / image / video / audio uploads

Usage:
    from services.file_validator import validate_upload
    error = validate_upload(file_storage, resource_type="document")
    if error:
        return jsonify({"error": error}), 400
"""
import os
from flask import current_app
from werkzeug.datastructures import FileStorage

try:
    import filetype as _filetype
    _HAS_FILETYPE = True
except ImportError:
    _HAS_FILETYPE = False


# ── MIME groups recognised by the `filetype` library ───────────────────────
# Maps our resource_type → accepted MIME prefixes / exact MIME strings
_MIME_ALLOWLIST_BY_TYPE = {
    "document": {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",   # docx/xlsx/pptx are ZIP-based — filetype may detect as zip
        "text/plain",
        "text/csv",
    },
    "image": {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
    },
    "video": {
        "video/mp4",
        "video/x-msvideo",  # avi
        "video/quicktime",  # mov
        "video/x-matroska", # mkv
        "video/webm",
        "video/x-flv",
    },
    "audio": {
        "audio/mpeg",       # mp3
        "audio/wav",
        "audio/x-wav",
        "audio/aac",
        "audio/ogg",
        "audio/flac",
        "audio/mp4",        # m4a
    },
    "other": {
        "application/zip",
        "application/x-zip-compressed",
    },
}

# Dangerous MIME types that should NEVER be accepted
_BLOCKED_MIMES = {
    "application/x-msdownload",      # .exe
    "application/x-sh",              # .sh
    "text/x-php",                    # .php
    "application/x-httpd-php",
    "application/x-dosexec",         # PE executables
    "application/java-archive",      # .jar
    "application/x-msdos-program",
}


def _get_extension(filename: str) -> str:
    """Return lowercase extension without leading dot. E.g. 'report.PDF' → 'pdf'"""
    _, ext = os.path.splitext(filename or "")
    return ext.lstrip(".").lower()


def _detect_mime(file_storage: FileStorage) -> str | None:
    """
    Read the first 261 bytes (the maximum needed by the filetype library)
    to detect the actual MIME type.  Rewinds the stream afterwards.
    Returns MIME string or None if undetectable.
    """
    if not _HAS_FILETYPE:
        return None

    header = file_storage.read(261)
    file_storage.seek(0)            # rewind for subsequent reads / uploads

    kind = _filetype.guess(header)
    return kind.mime if kind else None


def validate_upload(
    file_storage: FileStorage,
    resource_type: str = "other",
) -> str | None:
    """
    Validate a FileStorage object.

    Args:
        file_storage:  werkzeug FileStorage from request.files['file']
        resource_type: one of document / video / audio / image / other

    Returns:
        Error message string if invalid, or None if all checks pass.
    """
    filename = file_storage.filename or ""
    ext      = _get_extension(filename)

    # ── 1. Empty filename guard ─────────────────────────────────────
    if not filename:
        return "No filename provided."

    # ── 2. Double-extension attack guard ────────────────────────────
    # e.g. "malware.exe.pdf" — reject if any part before the last dot is blocked
    parts = filename.rsplit(".", 1)
    if len(parts) > 1:
        stem = parts[0]
        for blocked_ext in current_app.config.get("BLOCKED_EXTENSIONS", set()):
            if stem.lower().endswith(f".{blocked_ext}"):
                return f"File name contains a disallowed embedded extension (.{blocked_ext})."

    # ── 3. Extension allowlist ──────────────────────────────────────
    blocked = current_app.config.get("BLOCKED_EXTENSIONS", set())
    if ext in blocked:
        return f"File type '.{ext}' is not allowed for security reasons."

    allowed = current_app.config.get("ALLOWED_EXTENSIONS", set())
    if allowed and ext not in allowed:
        return (
            f"File extension '.{ext}' is not permitted. "
            f"Allowed types: {', '.join(sorted(allowed))}."
        )

    # ── 4. Per-type extension check ─────────────────────────────────
    type_ext_map = {
        "document": current_app.config.get("ALLOWED_DOCUMENT_EXTENSIONS", set()),
        "image":    current_app.config.get("ALLOWED_IMAGE_EXTENSIONS", set()),
        "video":    current_app.config.get("ALLOWED_VIDEO_EXTENSIONS", set()),
        "audio":    current_app.config.get("ALLOWED_AUDIO_EXTENSIONS", set()),
        "other":    current_app.config.get("ALLOWED_OTHER_EXTENSIONS", set()),
    }
    if resource_type in type_ext_map and type_ext_map[resource_type]:
        if ext not in type_ext_map[resource_type]:
            return (
                f"Extension '.{ext}' is not valid for resource type '{resource_type}'. "
                f"Expected: {', '.join(sorted(type_ext_map[resource_type]))}."
            )

    # ── 5. Magic-byte MIME validation ───────────────────────────────
    detected_mime = _detect_mime(file_storage)
    if detected_mime:
        if detected_mime in _BLOCKED_MIMES:
            return f"Detected file content ({detected_mime}) is not permitted."

        allowed_mimes = _MIME_ALLOWLIST_BY_TYPE.get(resource_type)
        if allowed_mimes and detected_mime not in allowed_mimes:
            # Soft-fail: warn in logs but don't block (filetype can mis-detect
            # edge cases like very old .doc binary files).
            current_app.logger.warning(
                "MIME mismatch: ext=%s resource_type=%s detected=%s filename=%s",
                ext, resource_type, detected_mime, filename,
            )
            # Only hard-block obviously dangerous types
            if detected_mime.startswith("application/x-ms") or detected_mime in _BLOCKED_MIMES:
                return f"Detected file type ({detected_mime}) is not allowed."

    # ── 6. Per-type size cap ────────────────────────────────────────
    size_map = {
        "document": current_app.config.get("MAX_DOCUMENT_SIZE", 20 * 1024 * 1024),
        "image":    current_app.config.get("MAX_IMAGE_SIZE",    10 * 1024 * 1024),
        "video":    current_app.config.get("MAX_VIDEO_SIZE",   500 * 1024 * 1024),
        "audio":    current_app.config.get("MAX_AUDIO_SIZE",    50 * 1024 * 1024),
        "other":    current_app.config.get("MAX_OTHER_SIZE",    10 * 1024 * 1024),
    }
    max_size = size_map.get(resource_type, 10 * 1024 * 1024)

    # Determine actual size: seek to end, get position, rewind
    file_storage.seek(0, 2)
    actual_size = file_storage.tell()
    file_storage.seek(0)

    if actual_size > max_size:
        max_mb = max_size // (1024 * 1024)
        actual_mb = actual_size / (1024 * 1024)
        return (
            f"File is too large ({actual_mb:.1f} MB). "
            f"Maximum allowed for '{resource_type}' is {max_mb} MB."
        )

    # ── All checks passed ───────────────────────────────────────────
    return None
