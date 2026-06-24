"""
models/resource.py — Resource/Learning material model and ID generation
"""
from datetime import datetime
import shortuuid


def new_resource_id():   return f"RES-{shortuuid.ShortUUID().random(length=6).upper()}"


def build_resource(
    title: str,
    description: str,
    resource_type: str,  # document, video, link, etc.
    course_id: str,
    batch_id: str = None,
    file_url: str = None,          # for uploaded files (documents, videos)
    external_url: str = None,      # for links
    thumbnail_url: str = None,     # preview image (auto-generated for videos/documents)
    category: str = "",
    tags=None,
    uploaded_by: str = None,       # admin/teacher ID who uploaded
    active: bool = True
):
    """
    Build a resource document for storage in MongoDB.
    Returns a dict ready for insertion.
    """
    if tags is None:
        tags = []

    # Basic validation (service layer should do thorough validation)
    valid_types = ["document", "video", "link", "audio", "image", "other"]
    if resource_type not in valid_types:
        raise ValueError(f"resource_type must be one of {valid_types}")
    if resource_type == "link" and not external_url:
        raise ValueError("External URL is required for link resources")
    if resource_type in ("document", "video", "audio", "image") and not file_url:
        raise ValueError(f"File URL is required for {resource_type} resources")
    if not title:
        raise ValueError("Title is required")
    if not course_id:
        raise ValueError("Course ID is required")

    return {
        "resource_id": new_resource_id(),
        "title": title.strip(),
        "description": description.strip(),
        "resource_type": resource_type,
        "course_id": course_id.strip(),
        "batch_id": batch_id.strip() if batch_id else None,
        "file_url": file_url,
        "external_url": external_url,
        "thumbnail_url": thumbnail_url,
        "category": category.strip(),
        "tags": [t.strip() for t in tags if t.strip()],
        "uploaded_by": uploaded_by,
        "active": active,
        "view_count": 0,  # optional tracking
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }