"""
services/email_service.py
-------------------------
Email notification helpers.

Flask-Mail is used under the hood; it's configured via config.py
and initialised in app.py.  All functions are no-ops when
MAIL_SUPPRESS_SEND is True (i.e. MAIL_USERNAME is not set), so the
rest of the app works without email credentials in development.

Exported helpers (all swallow exceptions and log on failure):
  send_assignment_due_reminder(student_email, student_name, assignment, course_name)
  send_grade_posted(student_email, student_name, assignment, submission)
  send_password_reset(recipient_email, reset_link, name)
  send_welcome(recipient_email, name, role, temp_password=None)
"""
import traceback
from flask import current_app
from flask_mail import Mail, Message

mail = Mail()


def _send(msg: Message) -> bool:
    """
    Internal helper: send a message and swallow exceptions.
    Returns True on success, False on failure.
    """
    try:
        if current_app.config.get("MAIL_SUPPRESS_SEND"):
            current_app.logger.debug("[Email suppressed] To: %s | Subject: %s", msg.recipients, msg.subject)
            return True
        mail.send(msg)
        current_app.logger.info("[Email sent] To: %s | Subject: %s", msg.recipients, msg.subject)
        return True
    except Exception:
        current_app.logger.error("[Email FAILED] To: %s\n%s", msg.recipients, traceback.format_exc())
        return False


# ── Public notification functions ────────────────────────────────────────────

def send_assignment_due_reminder(
    student_email: str,
    student_name: str,
    assignment: dict,
    course_name: str,
) -> bool:
    """Notify a student that an assignment is due soon."""
    center = current_app.config.get("CENTER_NAME", "OS Education Center")
    msg = Message(
        subject=f"[{center}] Assignment Due: {assignment.get('title', 'Assignment')}",
        recipients=[student_email],
    )
    msg.body = (
        f"Dear {student_name},\n\n"
        f"This is a reminder that the following assignment is due soon:\n\n"
        f"  Title   : {assignment.get('title')}\n"
        f"  Course  : {course_name}\n"
        f"  Due Date: {assignment.get('due_date')}\n\n"
        f"Please submit before the deadline to avoid late penalties.\n\n"
        f"— {center}"
    )
    return _send(msg)


def send_grade_posted(
    student_email: str,
    student_name: str,
    assignment: dict,
    submission: dict,
    course_name: str,
) -> bool:
    """Notify a student that their assignment has been graded."""
    center     = current_app.config.get("CENTER_NAME", "OS Education Center")
    max_points = assignment.get("max_points", 100)
    score      = submission.get("score", "N/A")
    feedback   = submission.get("feedback") or "No feedback provided."
    msg = Message(
        subject=f"[{center}] Your assignment has been graded: {assignment.get('title')}",
        recipients=[student_email],
    )
    msg.body = (
        f"Dear {student_name},\n\n"
        f"Your submission for the following assignment has been graded:\n\n"
        f"  Title    : {assignment.get('title')}\n"
        f"  Course   : {course_name}\n"
        f"  Score    : {score} / {max_points}\n"
        f"  Feedback : {feedback}\n\n"
        f"Log in to the student portal to view the full result.\n\n"
        f"— {center}"
    )
    return _send(msg)


def send_password_reset(
    recipient_email: str,
    reset_link: str,
    name: str,
    expires_minutes: int = 30,
) -> bool:
    """Send a password-reset link."""
    center = current_app.config.get("CENTER_NAME", "OS Education Center")
    msg = Message(
        subject=f"[{center}] Password Reset Request",
        recipients=[recipient_email],
    )
    msg.body = (
        f"Dear {name},\n\n"
        f"A password reset was requested for your account.\n\n"
        f"Use the link below to set a new password (expires in {expires_minutes} minutes):\n\n"
        f"  {reset_link}\n\n"
        f"If you did not request a reset, you can safely ignore this email.\n"
        f"Your password will not change unless you use the link above.\n\n"
        f"— {center}"
    )
    return _send(msg)


def send_welcome(
    recipient_email: str,
    name: str,
    role: str,
    temp_password: str | None = None,
) -> bool:
    """Send a welcome email when a new account is created."""
    center  = current_app.config.get("CENTER_NAME", "OS Education Center")
    website = current_app.config.get("CENTER_WEBSITE", "")
    msg = Message(
        subject=f"[{center}] Welcome, {name}!",
        recipients=[recipient_email],
    )
    pwd_line = (
        f"\nYour temporary password is: {temp_password}\n"
        f"Please change it immediately after your first login.\n"
        if temp_password else ""
    )
    msg.body = (
        f"Dear {name},\n\n"
        f"Welcome to {center}! Your {role} account has been created.\n"
        f"{pwd_line}\n"
        f"Log in at: {website}\n\n"
        f"— {center}"
    )
    return _send(msg)
