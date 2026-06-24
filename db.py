"""
db.py — single place for all MongoDB access.
Import `mongo` and use mongo.db.<collection> anywhere.

Connection pooling and timeout settings are read from Config so they
can be tuned per environment without touching this file.
"""
from flask import current_app
from flask_pymongo import PyMongo
from pymongo import MongoClient

mongo = PyMongo()


# ── Collection accessors ────────────────────────────────────────────────────

def get_students():       return mongo.db.students
def get_courses():        return mongo.db.courses
def get_batches():        return mongo.db.batches
def get_fees():           return mongo.db.fees
def get_exams():          return mongo.db.exams
def get_exam_sessions():  return mongo.db.exam_sessions
def get_results():        return mongo.db.results
def get_certificates():   return mongo.db.certificates
def get_questions():      return mongo.db.questions
def get_assignments():    return mongo.db.assignments
def get_assignment_submissions(): return mongo.db.assignment_submissions
def get_resources():      return mongo.db.resources
def get_teachers():       return mongo.db.teachers
def get_admin():          return mongo.db.admin
<<<<<<< HEAD
def get_exam_papers():    return mongo.db.exam_papers
def get_exam_reports():   return mongo.db.exam_reports
=======
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c


def init_mongo(app):
    """
    Configure PyMongo with connection pool, timeout, and retry settings
    read from app.config, then call mongo.init_app().

    PyMongo 4 passes driver options via the URI query string or the
    MongoClient constructor; Flask-PyMongo forwards extra kwargs via
    MONGO_URI but the clearest approach is to inject them through the
    URI when they're not already present.

    We build the options dict and embed them via MONGO_URI so a single
    `mongo.init_app(app)` call picks up everything.
    """
    uri = app.config["MONGO_URI"]

    # Append connection-pool and timeout parameters if they're not already
    # in the URI (avoids doubling parameters for Atlas URIs that already
    # include them).
    pool_params = {
        "maxPoolSize":              app.config.get("MONGO_POOL_SIZE", 10),
        "minPoolSize":              app.config.get("MONGO_MIN_POOL_SIZE", 2),
        "connectTimeoutMS":         app.config.get("MONGO_CONNECT_TIMEOUT", 5000),
        "serverSelectionTimeoutMS": app.config.get("MONGO_SERVER_SELECT_MS", 5000),
        "socketTimeoutMS":          app.config.get("MONGO_SOCKET_TIMEOUT", 10000),
        "retryWrites":              "true",
        "retryReads":               "true",
    }

    # Only inject params that aren't already in the URI
    separator = "&" if "?" in uri else "?"
    additions = []
    for k, v in pool_params.items():
        lower_uri = uri.lower()
        if k.lower() not in lower_uri:
            additions.append(f"{k}={v}")

    if additions:
        uri = uri + separator + "&".join(additions)
        app.config["MONGO_URI"] = uri

    mongo.init_app(app)


def ping_db() -> bool:
    """
    Ping MongoDB to verify connectivity.
    Returns True on success, False on any error.
    Used by the /health endpoint.
    """
    try:
        mongo.db.command("ping")
        return True
    except Exception:
        return False


def create_indexes():
    # ── Unique identity indexes ─────────────────────────────────────
    get_students().create_index("student_id", unique=True)
    get_students().create_index("email", unique=True)
    get_courses().create_index("course_id", unique=True)
    get_batches().create_index("batch_id", unique=True)
    get_exams().create_index("exam_id", unique=True)
    get_results().create_index("result_id", unique=True)
    get_certificates().create_index("cert_id", unique=True)
    get_fees().create_index("fee_id", unique=True)
    get_questions().create_index("question_id", unique=True)
    get_teachers().create_index("teacher_id", unique=True)
    get_teachers().create_index("email", unique=True)

    # ── Assignment indexes ──────────────────────────────────────────
    get_assignments().create_index("assignment_id", unique=True)
    get_assignments().create_index("course_id")
    get_assignments().create_index("batch_id")
    get_assignments().create_index("due_date")
    get_assignments().create_index("created_by")           # teacher dashboard query
    get_assignments().create_index([("course_id", 1), ("active", 1)])   # list by course

    # ── Submission indexes ──────────────────────────────────────────
    get_assignment_submissions().create_index("submission_id", unique=True)
    get_assignment_submissions().create_index("assignment_id")
    get_assignment_submissions().create_index("student_id")
    get_assignment_submissions().create_index("status")
    get_assignment_submissions().create_index("submitted_at")
    # Compound unique — enforces ONE submission per student per assignment
    # at the DB layer (closes the race window on the app-level check).
    get_assignment_submissions().create_index(
        [("assignment_id", 1), ("student_id", 1)], unique=True
    )

    # ── Resource indexes ────────────────────────────────────────────
    get_resources().create_index("resource_id", unique=True)
    get_resources().create_index("course_id")
    get_resources().create_index("batch_id")
    get_resources().create_index("resource_type")
    get_resources().create_index("category")
    get_resources().create_index("tags")
    get_resources().create_index("uploaded_by")            # teacher dashboard query
    get_resources().create_index([("course_id", 1), ("active", 1)])

    # ── Student lookup ──────────────────────────────────────────────
    get_students().create_index("enrolled_courses")        # enrollment checks
    get_students().create_index("active")

    # ── Result / fee lookups ────────────────────────────────────────
    get_results().create_index("student_id")
    get_results().create_index("exam_id")
    get_fees().create_index("student_id")
    get_fees().create_index("status")

<<<<<<< HEAD
    # ── Exam extension indexes ──────────────────────────────────────
    get_exam_papers().create_index("paper_id", unique=True)
    get_exam_papers().create_index("teacher_id")
    get_exam_papers().create_index("course_id")
    get_exam_papers().create_index("status")
    get_exam_reports().create_index("report_id", unique=True)
    get_exam_reports().create_index("session_id")
    get_exam_reports().create_index("student_id")
    get_exam_reports().create_index("status")

=======
>>>>>>> 091fbe1a0bfbb2d98bc394e9b2093ff6a720c55c
    print("[DB] Indexes created.")
