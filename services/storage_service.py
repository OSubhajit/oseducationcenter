"""
services/storage_service.py — Generic file upload to Cloudinary
"""
import cloudinary
import cloudinary.uploader
import uuid
from flask import current_app
from werkzeug.datastructures import FileStorage


def _init_cloudinary():
    cloudinary.config(
        cloud_name = current_app.config["CLOUDINARY_CLOUD_NAME"],
        api_key    = current_app.config["CLOUDINARY_API_KEY"],
        api_secret = current_app.config["CLOUDINARY_API_SECRET"],
        secure     = True,
    )


def upload_file(file_storage: FileStorage, folder: str = "osec/uploads", resource_type: str = "auto") -> dict:
    """
    Upload a file to Cloudinary.

    Args:
        file_storage: Werkzeug FileStorage object from request.files['file']
        folder: Cloudinary folder to store the file (default: osec/uploads)
        resource_type: "image", "video", "raw", or "auto" (lets Cloudinary detect)

    Returns:
        {"success": True,  "url": "https://...", "public_id": "..."}
        {"success": False, "url": None, "error": "..."}
    """
    _init_cloudinary()
    try:
        # Generate a unique public ID to avoid collisions
        public_id = str(uuid.uuid4())
        # Optional: keep original filename as part of public_id for readability?
        # But UUID is fine.

        result = cloudinary.uploader.upload(
            file_storage,
            resource_type=resource_type,
            folder=folder,
            public_id=public_id,
            overwrite=False,
            # Use "upload" (public-read). Access control is enforced at the
            # Flask API layer (JWT + enrollment checks); private Cloudinary URLs
            # return 401 when handed directly to browsers as download links.
            type="upload",
        )
        return {
            "success": True,
            "url": result["secure_url"],
            "public_id": result["public_id"],
        }
    except Exception as e:
        return {
            "success": False,
            "url": None,
            "error": str(e),
        }


def upload_file_from_path(file_path: str, folder: str = "osec/uploads", resource_type: str = "auto") -> dict:
    """
    Upload a file from local path to Cloudinary.
    Useful for temporary files.
    """
    _init_cloudinary()
    try:
        public_id = str(uuid.uuid4())
        result = cloudinary.uploader.upload(
            file_path,
            resource_type=resource_type,
            folder=folder,
            public_id=public_id,
            overwrite=False,
            type="upload",   # public-read; access enforced at API layer
        )
        return {
            "success": True,
            "url": result["secure_url"],
            "public_id": result["public_id"],
        }
    except Exception as e:
        return {
            "success": False,
            "url": None,
            "error": str(e),
        }


def delete_file(public_id: str, resource_type: str = "image") -> dict:
    """
    Delete a file from Cloudinary by public_id.
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
            "result": result,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }