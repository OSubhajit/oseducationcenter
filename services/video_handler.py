"""
services/video_handler.py
--------------------------
Handles all file uploads to Cloudinary:
  - Exam hall video footage
  - Student photo (during enrolment)
  - Certificate PDF
"""
import cloudinary
import cloudinary.uploader
from flask import current_app


# ── Cloudinary init ──────────────────────────────────────────────

def _init_cloudinary():
    cloudinary.config(
        cloud_name = current_app.config["CLOUDINARY_CLOUD_NAME"],
        api_key    = current_app.config["CLOUDINARY_API_KEY"],
        api_secret = current_app.config["CLOUDINARY_API_SECRET"],
        secure     = True,
    )


# ── Upload exam video ────────────────────────────────────────────

def upload_exam_video(file_path: str, session_id: str) -> dict:
    """
    Uploads the exam hall recording video to Cloudinary.
    Stored under: osec/exam_videos/<session_id>

    Args:
        file_path  : local path to the video file
        session_id : exam session ID (used as public_id)

    Returns:
        {"success": True,  "url": "https://...", "public_id": "..."}
        {"success": False, "url": None, "error": "..."}
    """
    _init_cloudinary()
    try:
        result = cloudinary.uploader.upload(
            file_path,
            resource_type = "video",
            folder        = "osec/exam_videos",
            public_id     = session_id,
            overwrite     = True,
            # restrict access — only accessible via signed URL
            type          = "upload",      # public-read; access enforced at API layer
        )
        return {
            "success"   : True,
            "url"       : result["secure_url"],
            "public_id" : result["public_id"],
        }
    except Exception as e:
        return {
            "success" : False,
            "url"     : None,
            "error"   : str(e),
        }


# ── Upload student photo ─────────────────────────────────────────

def upload_student_photo(b64_image: str, student_id: str) -> dict:
    """
    Uploads student's enrolment photo.
    Accepts base64-encoded image string.
    Stored under: osec/student_photos/<student_id>

    Returns:
        {"success": True,  "url": "https://..."}
        {"success": False, "url": None, "error": "..."}
    """
    _init_cloudinary()
    try:
        # Cloudinary accepts base64 data URIs directly
        if not b64_image.startswith("data:"):
            b64_image = f"data:image/jpeg;base64,{b64_image}"

        result = cloudinary.uploader.upload(
            b64_image,
            resource_type = "image",
            folder        = "osec/student_photos",
            public_id     = student_id,
            overwrite     = True,
            # auto-crop to face for clean profile photos
            transformation= [
                {"width": 400, "height": 400,
                 "crop": "thumb", "gravity": "face"}
            ],
        )
        return {
            "success": True,
            "url"    : result["secure_url"],
        }
    except Exception as e:
        return {
            "success": False,
            "url"    : None,
            "error"  : str(e),
        }


# ── Upload certificate PDF ───────────────────────────────────────

def upload_certificate_pdf(pdf_bytes: bytes, cert_id: str) -> dict:
    """
    Uploads the generated certificate PDF to Cloudinary.
    Stored under: osec/certificates/<cert_id>
    Public access — anyone with the URL can download.

    Returns:
        {"success": True,  "url": "https://..."}
        {"success": False, "url": None, "error": "..."}
    """
    _init_cloudinary()
    try:
        result = cloudinary.uploader.upload(
            pdf_bytes,
            resource_type = "raw",         # raw = any file type (PDF)
            folder        = "osec/certificates",
            public_id     = f"{cert_id}.pdf",
            overwrite     = True,
            type          = "upload",      # public access
        )
        return {
            "success": True,
            "url"    : result["secure_url"],
        }
    except Exception as e:
        return {
            "success": False,
            "url"    : None,
            "error"  : str(e),
        }


# ── Delete a file (admin only) ───────────────────────────────────

def delete_file(public_id: str, resource_type: str = "image") -> dict:
    """
    Deletes a file from Cloudinary.
    resource_type: "image" | "video" | "raw"
    Only called from admin delete operations.
    """
    _init_cloudinary()
    try:
        result = cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type,
            invalidate=True,
        )
        return {
            "success": result.get("result") == "ok",
            "result" : result,
        }
    except Exception as e:
        return {
            "success": False,
            "error"  : str(e),
        }
