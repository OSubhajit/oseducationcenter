"""
services/resource_service.py — Business logic for resource operations
"""
from bson import ObjectId
from datetime import datetime
from pymongo.errors import DuplicateKeyError
from flask import current_app
from models.resource import new_resource_id, build_resource
from db import get_resources, get_courses, get_batches, get_students
import re


def _validate_resource_data(data):
    """Validate resource-specific fields."""
    if not data.get("title"):
        raise ValueError("Title is required")
    if not data.get("description"):
        raise ValueError("Description is required")
    if not data.get("resource_type"):
        raise ValueError("Resource type is required")
    valid_types = ["document", "video", "link", "audio", "image", "other"]
    if data["resource_type"] not in valid_types:
        raise ValueError(f"Resource type must be one of {valid_types}")
    if not data.get("course_id"):
        raise ValueError("Course ID is required")
    # Validate course exists
    if not get_courses().find_one({"course_id": data["course_id"]}):
        raise ValueError("Course not found")
    batch_id = data.get("batch_id")
    if batch_id:
        if not get_batches().find_one({"batch_id": batch_id}):
            raise ValueError("Batch not found")
        # Optional: verify batch belongs to course
        batch = get_batches().find_one({"batch_id": batch_id})
        if batch["course_id"] != data["course_id"]:
            raise ValueError("Batch does not belong to the specified course")
    # For link type, external_url required
    if data["resource_type"] == "link" and not data.get("external_url"):
        raise ValueError("External URL is required for link resources")
    # For non-link types, file_url required (will be provided during upload)
    if data["resource_type"] != "link" and not data.get("file_url"):
        # Not validating here because upload service will provide it;
        # but for direct creation (if any) we should require.
        pass  # We'll allow None; service upload will set it.
    # Tags validation
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        raise ValueError("Tags must be a list")
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError("Each tag must be a string")
        if not tag.strip():
            raise ValueError("Tags cannot be empty strings")


def create_resource(data):
    """
    Create a new resource.
    Expects dict with keys: title, description, resource_type, course_id, batch_id (optional),
    file_url (for uploaded files), external_url (for links), thumbnail_url (optional),
    category, tags (list), uploaded_by.
    Returns the created resource document (with _id and resource_id as strings).
    Raises ValueError on validation error.
    """
    _validate_resource_data(data)

    # Build resource document
    resource_doc = build_resource(
        title=data["title"],
        description=data["description"],
        resource_type=data["resource_type"],
        course_id=data["course_id"],
        batch_id=data.get("batch_id"),
        file_url=data.get("file_url"),
        external_url=data.get("external_url"),
        thumbnail_url=data.get("thumbnail_url"),
        category=data.get("category", ""),
        tags=data.get("tags", []),
        uploaded_by=data.get("uploaded_by"),
        active=data.get("active", True)
    )

    # Insert into DB
    try:
        result = get_resources().insert_one(resource_doc)
        resource_doc["_id"] = str(result.inserted_id)
        return resource_doc
    except DuplicateKeyError:
        raise ValueError("A resource with this ID already exists (unexpected)")


def get_resource(resource_id):
    """
    Fetch a resource by its resource_id (e.g., RES-ABC123).
    Returns resource document with _id as string, or None if not found.
    """
    doc = get_resources().find_one({"resource_id": resource_id, "active": True})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_resource_by_mongo_id(mongo_id):
    """
    Fetch a resource by MongoDB _id.
    Useful for internal lookups.
    """
    try:
        doc = get_resources().find_one({"_id": ObjectId(mongo_id), "active": True})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except Exception:
        return None


def update_resource(resource_id, updates):
    """
    Update a resource by resource_id.
    Only allows updating certain fields; resource_id and course_id cannot be changed.
    Returns updated resource document, or None if not found.
    """
    # Prevent changing immutable fields
    immutable = {"resource_id", "course_id", "created_at"}
    filtered_updates = {k: v for k, v in updates.items() if k not in immutable}
    if not filtered_updates:
        # Nothing to update
        return get_resource(resource_id)

    # Validate updates if they affect validated fields
    if "resource_type" in filtered_updates:
        if filtered_updates["resource_type"] not in ["document", "video", "link", "audio", "image", "other"]:
            raise ValueError("Invalid resource type")
    if filtered_updates.get("resource_type") == "link" and not filtered_updates.get("external_url"):
        # If changing to link, need external_url
        raise ValueError("External URL is required for link resources")
    # If changing away from link, external_url can be kept or cleared; we'll allow.

    # Set updated_at
    filtered_updates["updated_at"] = datetime.utcnow()

    result = get_resources().update_one(
        {"resource_id": resource_id, "active": True},
        {"$set": filtered_updates}
    )
    if result.matched_count == 0:
        return None
    return get_resource(resource_id)


def delete_resource(resource_id):
    """
    Soft-delete a resource by setting active=False.
    Returns True if deleted, False if not found.
    """
    result = get_resources().update_one(
        {"resource_id": resource_id},
        {"$set": {"active": False, "updated_at": datetime.utcnow()}}
    )
    return result.modified_count > 0


def list_resources(filters=None, page=1, per_page=20, search=None, sort_by="created_at", sort_order=-1):
    """
    List resources with filtering, searching, and pagination.
    Returns tuple (resources_list, total_count).
    filters: dict of field->value equality filters.
        For tags, provide a list of tags to match any of them (uses $in).
    search: text to search in title or description (case-insensitive regex)
    """
    query = {"active": True}
    if filters:
        for key, value in filters.items():
            if key == "tags":
                if isinstance(value, list) and value:
                    # Match any of the provided tags
                    query["tags"] = {"$in": value}
                elif isinstance(value, str):
                    # Single tag as string
                    query["tags"] = value
                # else ignore empty
            elif key in ["course_id", "batch_id", "resource_type", "category"]:
                query[key] = value
            # Add other filterable fields as needed
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}}
        ]

    cursor = get_resources().find(query)
    total  = get_resources().count_documents(query)   # cursor.count() removed in PyMongo 4
    # Apply sorting
    if sort_order == 1:
        cursor = cursor.sort(sort_by, 1)
    else:
        cursor = cursor.sort(sort_by, -1)
    # Apply pagination
    cursor = cursor.skip((page - 1) * per_page).limit(per_page)

    resources = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        resources.append(doc)

    return resources, total


def increment_view_count(resource_id):
    """
    Increment the view count for a resource.
    Returns updated resource document.
    """
    result = get_resources().update_one(
        {"resource_id": resource_id},
        {"$inc": {"view_count": 1}, "$set": {"updated_at": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        return None
    return get_resource(resource_id)


# Resource upload handling (using storage service)

def upload_resource_file(file_storage, folder="osec/resources") -> dict:
    """
    Upload a file for a resource using the storage service.
    Returns dict with success, url, public_id.
    """
    from services.storage_service import upload_file
    return upload_file(file_storage, folder=folder)


def create_resource_from_upload(
    title: str,
    description: str,
    resource_type: str,
    course_id: str,
    batch_id: str,
    file_storage,
    uploaded_by: str,
    category: str = "",
    tags=None
):
    """
    High-level function to upload a file and create a resource record.
    """
    if tags is None:
        tags = []
    # Upload file
    upload_result = upload_resource_file(file_storage, folder=f"osec/resources/{resource_type}")
    if not upload_result["success"]:
        raise ValueError(f"File upload failed: {upload_result.get('error')}")
    file_url = upload_result["url"]
    # Generate thumbnail for certain types? Could be done later; for now None.
    thumbnail_url = None
    # Prepare data
    data = {
        "title": title,
        "description": description,
        "resource_type": resource_type,
        "course_id": course_id,
        "batch_id": batch_id,
        "file_url": file_url,
        "external_url": None,
        "thumbnail_url": thumbnail_url,
        "category": category,
        "tags": tags,
        "uploaded_by": uploaded_by,
        "active": True
    }
    # Validate and create
    return create_resource(data)