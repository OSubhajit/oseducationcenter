"""
schemas.py — Document builders + 46 courses seed data
"""
from datetime import datetime
import shortuuid, bcrypt


def new_student_id():   return f"OSEC-STU-{shortuuid.ShortUUID().random(length=6).upper()}"
def new_batch_id():     return f"BATCH-{shortuuid.ShortUUID().random(length=6).upper()}"
def new_fee_id():       return f"FEE-{shortuuid.ShortUUID().random(length=6).upper()}"
def new_exam_id(cid):   return f"EXAM-{cid}-{shortuuid.ShortUUID().random(length=4).upper()}"
def new_session_id():   return f"SES-{shortuuid.ShortUUID().random(length=8).upper()}"
def new_result_id():    return f"RES-{shortuuid.ShortUUID().random(length=8).upper()}"
def new_cert_id():      return f"OSEC-CERT-{shortuuid.ShortUUID().random(length=8).upper()}"
def new_teacher_id():   return f"OSEC-TCH-{shortuuid.ShortUUID().random(length=6).upper()}"
def new_course_id():    return f"OSEC-CRS-{shortuuid.ShortUUID().random(length=6).upper()}"


def build_course(name, category, duration_weeks, fee=0, max_students=30,
                 description="", active=True):
    return {
        "course_id"      : new_course_id(),
        "name"           : name.strip(),
        "category"       : category.strip(),
        "duration_weeks" : int(duration_weeks),
        "fee"            : float(fee),
        "max_students"   : int(max_students),
        "description"    : description.strip(),
        "active"         : active,
        "created_at"     : datetime.utcnow(),
    }


def build_admin(username, plain_password, name, email):
    return {
        "username"      : username,
        "password_hash" : bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode(),
        "name"          : name,
        "email"         : email,
        "created_at"    : datetime.utcnow(),
    }


def build_student(name, email, phone, dob, gender,
                  address, guardian_name, guardian_phone,
                  plain_password, photo_url=""):
    return {
        "student_id"        : new_student_id(),
        "name"              : name,
        "email"             : email,
        "phone"             : phone,
        "dob"               : dob,
        "gender"            : gender,
        "address"           : address,
        "guardian_name"     : guardian_name,
        "guardian_phone"    : guardian_phone,
        "password_hash"     : bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode(),
        "photo_url"         : photo_url,
        "face_encoding"     : None,
        "enrolled_courses"  : [],
        "enrolled_batches"  : [],   # list of batch_ids; kept in sync by enrol/remove endpoints
        "active"            : True,
        "created_at"        : datetime.utcnow(),
    }


def build_teacher(name, email, phone, dob, gender, address,
                  subject_expertise, qualification, plain_password, photo_url="", teaches=None):
    if teaches is None:
        teaches = []
    return {
        "teacher_id"        : new_teacher_id(),
        "name"              : name,
        "email"             : email,
        "phone"             : phone,
        "dob"               : dob,
        "gender"            : gender,
        "address"           : address,
        "subject_expertise" : subject_expertise,
        "qualification"     : qualification,
        "password_hash"     : bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode(),
        "photo_url"         : photo_url,
        "teaches"           : teaches,  # List of course_ids the teacher is authorized to teach
        "active"            : True,
        "created_at"        : datetime.utcnow(),
    }


def build_batch(course_id, name, start_date, end_date, schedule, max_students=20):
    return {
        "batch_id"      : new_batch_id(),
        "course_id"     : course_id,
        "name"          : name.strip(),
        "start_date"    : start_date,
        "end_date"      : end_date,
        "schedule"      : schedule,
        "students"      : [],
        "max_students"  : max_students,
        "active"        : True,
        "created_at"    : datetime.utcnow(),
    }


def build_fee(student_id, course_id, batch_id, total_amount):
    return {
        "fee_id"        : new_fee_id(),
        "student_id"    : student_id,
        "course_id"     : course_id,
        "batch_id"      : batch_id,
        "total_amount"  : total_amount,
        "paid_amount"   : 0,
        "due_amount"    : total_amount,
        "payments"      : [],
        "status"        : "pending",
        "created_at"    : datetime.utcnow(),
    }


def build_exam(course_id, title, duration_minutes, total_marks, pass_marks, questions):
    return {
        "exam_id"           : new_exam_id(course_id),
        "course_id"         : course_id,
        "title"             : title,
        "duration_minutes"  : duration_minutes,
        "total_marks"       : total_marks,
        "pass_marks"        : pass_marks,
        "questions"         : questions,
        "active"            : True,
        "created_at"        : datetime.utcnow(),
    }


def build_exam_session(student_id: str, exam_id: str) -> dict:
    """
    Extended exam session (v2) — adds proctor_log, typing_data, and video_chunks
    to support the full AI-powered proctoring system.
    """
    return {
        "session_id"     : new_session_id(),
        "student_id"     : student_id,
        "exam_id"        : exam_id,
        "start_time"     : datetime.utcnow(),
        "end_time"       : None,
        "video_url"      : None,
        "video_chunks"   : [],
        "face_log"       : [],
        "proctor_log"    : [],
        "answers"        : [],
        "typing_data"    : {
            "wpm"                     : 0,
            "total_words"             : 0,
            "total_chars"             : 0,
            "tab_switches"            : 0,
            "idle_periods"            : 0,
            "avg_seconds_per_question": 0,
        },
        "status"         : "active",
    }


def build_proctor_event(event_type: str, detail: str, confidence: float = 0.0) -> dict:
    """
    A single proctoring event entry for session["proctor_log"].

    event_type: 'no_face' | 'multiple_faces' | 'looking_away' | 'tab_switch' | 'identity_mismatch'
    """
    return {
        "event_type" : event_type,
        "detail"     : detail,
        "confidence" : round(confidence, 3),
        "timestamp"  : datetime.utcnow().isoformat(),
    }


def build_result(student_id, exam_id, session_id,
                 total_marks, scored_marks,
                 mcq_score, written_score,
                 ai_evaluation, video_url, grade, passed=False):
    return {
        "result_id"      : new_result_id(),
        "student_id"     : student_id,
        "exam_id"        : exam_id,
        "session_id"     : session_id,
        "total_marks"    : total_marks,
        "scored_marks"   : scored_marks,
        "percentage"     : round((scored_marks / total_marks) * 100, 2) if total_marks > 0 else 0,
        "grade"          : grade,
        "passed"         : passed,
        "mcq_score"      : mcq_score,
        "written_score"  : written_score,
        "ai_evaluation"  : ai_evaluation,
        "video_url"      : video_url,
        "locked"         : True,
        "created_at"     : datetime.utcnow(),
    }


def build_certificate(student_id, course_id, result_id,
                      grade, percentage, cert_hash):
    cert_id = new_cert_id()
    return {
        "cert_id"       : cert_id,
        "student_id"    : student_id,
        "course_id"     : course_id,
        "result_id"     : result_id,
        "issued_date"   : datetime.utcnow(),
        "grade"         : grade,
        "percentage"    : percentage,
        "hash"          : cert_hash,
        "qr_data"       : f"/api/verify/{cert_id}/page",
        "pdf_url"       : None,
        "status"        : "valid",
    }



def new_report_id():  return f"RPT-{shortuuid.ShortUUID().random(length=8).upper()}"
def new_paper_id():   return f"PAPER-{shortuuid.ShortUUID().random(length=8).upper()}"


def calculate_grade(pct: float) -> str:
    if pct >= 90: return "A+"
    if pct >= 80: return "A"
    if pct >= 70: return "B+"
    if pct >= 60: return "B"
    if pct >= 50: return "C"
    if pct >= 40: return "D"
    return "F"


# ── 46 COURSES SEED ───────────────────────────────────────────────
COURSES_SEED = [
    # Computer Basics
    {"course_id":"OSEC-CB-001","name":"Computer Fundamentals & Hardware","category":"Computer Basics","duration_weeks":4,"fee":1500,"active":True},
    {"course_id":"OSEC-CB-002","name":"Typing Speed & Keyboard Mastery","category":"Computer Basics","duration_weeks":3,"fee":800,"active":True},
    {"course_id":"OSEC-CB-003","name":"Windows OS & File Management","category":"Computer Basics","duration_weeks":3,"fee":1000,"active":True},
    {"course_id":"OSEC-CB-004","name":"Linux for Beginners","category":"Computer Basics","duration_weeks":6,"fee":2000,"active":True},
    {"course_id":"OSEC-CB-005","name":"Microsoft Word (Advanced + Basic)","category":"Computer Basics","duration_weeks":4,"fee":1500,"active":True},
    {"course_id":"OSEC-CB-006","name":"Microsoft Excel (Basic to Intermediate)","category":"Computer Basics","duration_weeks":6,"fee":2000,"active":True},
    {"course_id":"OSEC-CB-007","name":"Microsoft PowerPoint","category":"Computer Basics","duration_weeks":3,"fee":1000,"active":True},
    {"course_id":"OSEC-CB-008","name":"Google Workspace (Docs, Sheets, Drive)","category":"Computer Basics","duration_weeks":3,"fee":1200,"active":True},
    {"course_id":"OSEC-CB-009","name":"Internet, Email & Digital Communication","category":"Computer Basics","duration_weeks":2,"fee":800,"active":True},
    {"course_id":"OSEC-CB-010","name":"Cyber Safety & Digital Literacy","category":"Computer Basics","duration_weeks":2,"fee":800,"active":True},
    # Programming & Development
    {"course_id":"OSEC-PD-011","name":"Python for Beginners","category":"Programming & Development","duration_weeks":8,"fee":3000,"active":True},
    {"course_id":"OSEC-PD-012","name":"C Programming Basics","category":"Programming & Development","duration_weeks":8,"fee":2500,"active":True},
    {"course_id":"OSEC-PD-013","name":"C++ Fundamentals","category":"Programming & Development","duration_weeks":8,"fee":2500,"active":True},
    {"course_id":"OSEC-PD-014","name":"Java Basics","category":"Programming & Development","duration_weeks":8,"fee":2500,"active":True},
    {"course_id":"OSEC-PD-015","name":"HTML & CSS (Web Design)","category":"Programming & Development","duration_weeks":6,"fee":2000,"active":True},
    {"course_id":"OSEC-PD-016","name":"JavaScript Basics","category":"Programming & Development","duration_weeks":6,"fee":2500,"active":True},
    {"course_id":"OSEC-PD-017","name":"PHP & MySQL Basics","category":"Programming & Development","duration_weeks":8,"fee":2500,"active":True},
    {"course_id":"OSEC-PD-018","name":"WordPress Website Building","category":"Programming & Development","duration_weeks":4,"fee":2000,"active":True},
    {"course_id":"OSEC-PD-019","name":"Scratch Programming (for Kids)","category":"Programming & Development","duration_weeks":4,"fee":1200,"active":True},
    {"course_id":"OSEC-PD-020","name":"Introduction to Data Structures","category":"Programming & Development","duration_weeks":8,"fee":3000,"active":True},
    # Design & Creative
    {"course_id":"OSEC-DC-021","name":"Canva for Beginners","category":"Design & Creative","duration_weeks":2,"fee":800,"active":True},
    {"course_id":"OSEC-DC-022","name":"Adobe Photoshop Basics","category":"Design & Creative","duration_weeks":6,"fee":2500,"active":True},
    {"course_id":"OSEC-DC-023","name":"Adobe Illustrator Basics","category":"Design & Creative","duration_weeks":6,"fee":2500,"active":True},
    {"course_id":"OSEC-DC-024","name":"GIMP (Free Photoshop Alternative)","category":"Design & Creative","duration_weeks":4,"fee":1200,"active":True},
    {"course_id":"OSEC-DC-025","name":"UI/UX Design Basics (Figma)","category":"Design & Creative","duration_weeks":6,"fee":2500,"active":True},
    {"course_id":"OSEC-DC-026","name":"Video Editing with CapCut / DaVinci Resolve","category":"Design & Creative","duration_weeks":6,"fee":2500,"active":True},
    {"course_id":"OSEC-DC-027","name":"YouTube Channel Creation & Management","category":"Design & Creative","duration_weeks":4,"fee":1500,"active":True},
    {"course_id":"OSEC-DC-028","name":"Logo & Poster Design","category":"Design & Creative","duration_weeks":4,"fee":1500,"active":True},
    # Accounting & Office Tools
    {"course_id":"OSEC-AO-029","name":"Tally Prime (Accounting Software)","category":"Accounting & Office Tools","duration_weeks":6,"fee":2500,"active":True},
    {"course_id":"OSEC-AO-030","name":"MS Excel for Data Entry & MIS","category":"Accounting & Office Tools","duration_weeks":4,"fee":1500,"active":True},
    {"course_id":"OSEC-AO-031","name":"QuickBooks Basics","category":"Accounting & Office Tools","duration_weeks":4,"fee":2000,"active":True},
    {"course_id":"OSEC-AO-032","name":"Busy Accounting Software","category":"Accounting & Office Tools","duration_weeks":4,"fee":2000,"active":True},
    # Networking & Security
    {"course_id":"OSEC-NS-033","name":"Computer Networking Basics (TCP/IP, LAN, WAN)","category":"Networking & Security","duration_weeks":6,"fee":2500,"active":True},
    {"course_id":"OSEC-NS-034","name":"Cybersecurity Awareness & Basics","category":"Networking & Security","duration_weeks":4,"fee":2000,"active":True},
    {"course_id":"OSEC-NS-035","name":"Ethical Hacking for Beginners","category":"Networking & Security","duration_weeks":10,"fee":4000,"active":True},
    {"course_id":"OSEC-NS-036","name":"Wi-Fi Security & Safety","category":"Networking & Security","duration_weeks":3,"fee":1200,"active":True},
    # Mobile & Modern Tech
    {"course_id":"OSEC-MT-037","name":"Android App Basics (MIT App Inventor — No Code)","category":"Mobile & Modern Tech","duration_weeks":4,"fee":1500,"active":True},
    {"course_id":"OSEC-MT-038","name":"Social Media Marketing & Management","category":"Mobile & Modern Tech","duration_weeks":4,"fee":2000,"active":True},
    {"course_id":"OSEC-MT-039","name":"AI Tools for Everyday Use (ChatGPT, Gemini, etc.)","category":"Mobile & Modern Tech","duration_weeks":3,"fee":1500,"active":True},
    {"course_id":"OSEC-MT-040","name":"Freelancing & Earning Online (Fiverr, Upwork)","category":"Mobile & Modern Tech","duration_weeks":4,"fee":1500,"active":True},
    {"course_id":"OSEC-MT-041","name":"E-Commerce & Selling Online (Amazon, Meesho)","category":"Mobile & Modern Tech","duration_weeks":4,"fee":1500,"active":True},
    {"course_id":"OSEC-MT-042","name":"MS Excel + Python for Data Analysis (Intro)","category":"Mobile & Modern Tech","duration_weeks":6,"fee":2500,"active":True},
    # Certification Prep
    {"course_id":"OSEC-CP-043","name":"CCC (Course on Computer Concepts) — NIELIT Prep","category":"Certification Prep","duration_weeks":10,"fee":3500,"active":True},
    {"course_id":"OSEC-CP-044","name":"BCC (Basic Computer Course) — NIELIT Prep","category":"Certification Prep","duration_weeks":6,"fee":2500,"active":True},
    {"course_id":"OSEC-CP-045","name":"O Level Computer Course — NIELIT Prep","category":"Certification Prep","duration_weeks":20,"fee":8000,"active":True},
    {"course_id":"OSEC-CP-046","name":"TCS iON Digital Certification Prep","category":"Certification Prep","duration_weeks":8,"fee":3000,"active":True},
]