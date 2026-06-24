"""
services/exam_report_service.py
--------------------------------
Generates a comprehensive AI performance report for a completed exam.

Inputs:
  - Graded answers with per-question feedback (from ai_grader)
  - Typing data (wpm, total chars, time per question)
  - Proctoring summary (suspicious events, face log stats)
  - Exam and student metadata

Output:
  A structured report document for the exam_reports collection.
  Status starts as "pending_approval" — admin must approve before
  student/teacher can access it.

Public API
----------
generate_exam_report(session_id, result_doc, exam_doc, student_doc,
                     typing_data, proctor_summary)
    → dict  (report document ready to insert)
"""

import json
import re
from datetime import datetime


# ── Prompt builder ───────────────────────────────────────────────────────────

def _build_report_prompt(result_doc, exam_doc, student_doc,
                         typing_data, proctor_summary) -> str:
    ai_eval     = result_doc.get("ai_evaluation", {})
    written     = ai_eval.get("written_answers", [])
    percentage  = result_doc.get("percentage", 0)
    scored      = result_doc.get("scored_marks", 0)
    total       = result_doc.get("total_marks", 100)

    # Summarise per-question performance for the prompt
    q_summary = "\n".join(
        f"  Q{i+1}: score {w.get('score',0)}/{w.get('max_marks',0)} — {w.get('feedback','')[:200]}"
        for i, w in enumerate(written)
    )

    # Typing stats
    wpm          = typing_data.get("wpm", 0)
    total_words  = typing_data.get("total_words", 0)
    avg_time_per = typing_data.get("avg_seconds_per_question", 0)
    idle_periods = typing_data.get("idle_periods", 0)

    # Proctoring stats
    suspicious_count  = proctor_summary.get("suspicious_events", 0)
    no_face_count     = proctor_summary.get("no_face_detected", 0)
    multi_face_count  = proctor_summary.get("multiple_faces", 0)
    tab_switches      = typing_data.get("tab_switches", 0)
    total_pings       = proctor_summary.get("total_pings", 1)
    integrity_pct     = max(0, 100 - round((suspicious_count / max(total_pings, 1)) * 100))

    student_name = student_doc.get("name", "Student")
    exam_title   = exam_doc.get("title", "Exam")
    course_id    = exam_doc.get("course_id", "")

    return f"""You are an academic performance analyst for an IT training institute.
Analyse the following exam data and generate a detailed, objective performance report.

STUDENT: {student_name}
EXAM: {exam_title} ({course_id})
SCORE: {scored}/{total} marks ({percentage:.1f}%)
PASSED: {result_doc.get('passed', False)}

PER-QUESTION PERFORMANCE:
{q_summary if q_summary else "No question data available."}

TYPING BEHAVIOUR:
- Average typing speed: {wpm} words per minute
- Total words written: {total_words}
- Average time per question: {avg_time_per:.0f} seconds
- Idle periods (>60s without typing): {idle_periods}
- Tab/window switches detected: {tab_switches}

PROCTORING INTEGRITY:
- Total face-check pings: {total_pings}
- Suspicious events flagged: {suspicious_count}
- No-face-detected events: {no_face_count}
- Multiple-faces-detected events: {multi_face_count}
- Integrity score: {integrity_pct}%

TASK: Generate a structured JSON report with these exact keys:
{{
  "overall_assessment": "One paragraph summary of overall performance (2-3 sentences).",
  "problem_solving_skills": {{
    "score": <1-10>,
    "description": "Assessment of how the student approached problems, logical reasoning, completeness of answers.",
    "strengths": ["strength 1", "strength 2"],
    "areas_for_improvement": ["area 1", "area 2"]
  }},
  "knowledge_depth": {{
    "score": <1-10>,
    "description": "How well the student demonstrated conceptual understanding vs surface-level recall.",
    "strong_topics": ["topic 1", "topic 2"],
    "weak_topics": ["topic 1", "topic 2"]
  }},
  "writing_and_expression": {{
    "score": <1-10>,
    "description": "Clarity, structure, and quality of written responses."
  }},
  "typing_speed_analysis": {{
    "wpm": {wpm},
    "category": "<'Slow (<20 wpm)', 'Average (20-40 wpm)', 'Fast (40-60 wpm)', or 'Very Fast (60+ wpm)'>",
    "description": "What the typing speed and behaviour patterns suggest about exam approach.",
    "idle_periods_note": "<explanation of what {idle_periods} idle periods might indicate>"
  }},
  "exam_integrity": {{
    "integrity_score": {integrity_pct},
    "tab_switches": {tab_switches},
    "suspicious_events": {suspicious_count},
    "assessment": "<'Excellent', 'Good', 'Moderate Concern', or 'High Concern'>",
    "notes": "Brief professional note about proctoring observations."
  }},
  "recommendations": [
    "Specific, actionable recommendation 1",
    "Specific, actionable recommendation 2",
    "Specific, actionable recommendation 3"
  ],
  "instructor_notes": "Private note for teacher/admin with honest assessment.",
  "grade_justification": "Why this score reflects the student's demonstrated knowledge."
}}

Output ONLY valid JSON. No markdown. No preamble."""


# ── Main public function ─────────────────────────────────────────────────────

def generate_exam_report(session_id: str, result_doc: dict,
                         exam_doc: dict, student_doc: dict,
                         typing_data: dict, proctor_summary: dict) -> dict:
    """
    Call Groq to generate a comprehensive exam report.
    Returns report document ready for exam_reports collection.
    Does NOT insert — caller handles that.
    """
    from flask import current_app
    from groq import Groq

    prompt  = _build_report_prompt(result_doc, exam_doc, student_doc,
                                    typing_data, proctor_summary)

    client  = Groq(api_key=current_app.config["GROQ_API_KEY"])
    model   = current_app.config.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise academic analyst. "
                    "Always respond with valid JSON only — no markdown, no preamble."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2048,
    )

    raw       = response.choices[0].message.content.strip()
    raw_clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw_clean = re.sub(r"\s*```$",           "", raw_clean, flags=re.MULTILINE).strip()

    try:
        report_content = json.loads(raw_clean)
    except json.JSONDecodeError:
        # Fallback: store raw text so report isn't lost
        report_content = {
            "overall_assessment": raw[:500],
            "parse_error": "Report generated but JSON parsing failed.",
        }

    import shortuuid
    report_id = f"RPT-{shortuuid.ShortUUID().random(length=8).upper()}"

    return {
        "report_id"         : report_id,
        "session_id"        : session_id,
        "result_id"         : result_doc.get("result_id"),
        "student_id"        : result_doc.get("student_id"),
        "exam_id"           : result_doc.get("exam_id"),
        "scored_marks"      : result_doc.get("scored_marks"),
        "total_marks"       : result_doc.get("total_marks"),
        "percentage"        : result_doc.get("percentage"),
        "grade"             : result_doc.get("grade"),
        "passed"            : result_doc.get("passed"),
        "typing_data"       : typing_data,
        "proctor_summary"   : proctor_summary,
        "report_content"    : report_content,
        "status"            : "pending_approval",   # admin must approve
        "pdf_url"           : None,                 # set after PDF generation
        "generated_at"      : datetime.utcnow(),
        "approved_at"       : None,
        "approved_by"       : None,
    }


# ── Report PDF (ReportLab) ───────────────────────────────────────────────────

def generate_report_pdf(report_doc: dict, student_name: str,
                        exam_title: str, course_name: str) -> bytes:
    """
    Generate a PDF version of the report using ReportLab.
    Returns raw PDF bytes.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Table, TableStyle, HRFlowable)
    from io import BytesIO

    buf    = BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                                leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    BLACK  = colors.HexColor("#0A0A0A")
    BLUE   = colors.HexColor("#0047FF")
    GRAY   = colors.HexColor("#555555")
    LGRAY  = colors.HexColor("#F4F4F4")

    H1 = ParagraphStyle("H1", parent=styles["Heading1"],
                         fontSize=20, textColor=BLACK,
                         fontName="Helvetica-Bold", spaceAfter=4)
    H2 = ParagraphStyle("H2", parent=styles["Heading2"],
                         fontSize=12, textColor=BLUE,
                         fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6)
    BODY = ParagraphStyle("BODY", parent=styles["Normal"],
                           fontSize=9.5, textColor=BLACK,
                           leading=14, spaceAfter=6)
    SMALL = ParagraphStyle("SMALL", parent=styles["Normal"],
                            fontSize=8.5, textColor=GRAY, leading=12)
    LABEL = ParagraphStyle("LABEL", parent=styles["Normal"],
                            fontSize=8, textColor=GRAY,
                            fontName="Helvetica-Bold",
                            spaceAfter=2, textTransform="uppercase")

    content = report_doc.get("report_content", {})
    rc      = content  # alias

    story = []

    # ── Header ──────────────────────────────────────────────────────
    story.append(Paragraph("OS EDUCATION CENTER", LABEL))
    story.append(Paragraph("Student Performance Report", H1))
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
    story.append(Spacer(1, 0.3*cm))

    # ── Meta table ──────────────────────────────────────────────────
    meta = [
        ["Student", student_name,   "Exam",   exam_title],
        ["Course",  course_name,    "Score",  f"{report_doc.get('scored_marks',0)}/{report_doc.get('total_marks',100)} ({report_doc.get('percentage',0):.1f}%)"],
        ["Grade",   report_doc.get("grade","—"),
         "Status",  "PASSED" if report_doc.get("passed") else "FAILED"],
        ["Report ID", report_doc.get("report_id","—"),
         "Date",    report_doc.get("generated_at", datetime.utcnow()).strftime("%d %b %Y") if report_doc.get("generated_at") else ""],
    ]
    t = Table(meta, colWidths=[3*cm, 6.5*cm, 3*cm, 6*cm])
    t.setStyle(TableStyle([
        ("FONTNAME",  (0,0),(-1,-1), "Helvetica"),
        ("FONTSIZE",  (0,0),(-1,-1), 9),
        ("FONTNAME",  (0,0),(0,-1), "Helvetica-Bold"),
        ("FONTNAME",  (2,0),(2,-1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0,0),(0,-1), BLUE),
        ("TEXTCOLOR", (2,0),(2,-1), BLUE),
        ("BACKGROUND",(0,0),(-1,-1), LGRAY),
        ("GRID",      (0,0),(-1,-1), 0.5, colors.white),
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[LGRAY, colors.white]),
        ("VALIGN",    (0,0),(-1,-1), "MIDDLE"),
        ("PADDING",   (0,0),(-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.4*cm))

    # ── Overall Assessment ──────────────────────────────────────────
    story.append(Paragraph("Overall Assessment", H2))
    story.append(Paragraph(rc.get("overall_assessment", "N/A"), BODY))

    # ── Scores table ────────────────────────────────────────────────
    story.append(Paragraph("Skill Scores", H2))
    ps  = rc.get("problem_solving_skills", {})
    kd  = rc.get("knowledge_depth", {})
    we  = rc.get("writing_and_expression", {})
    ei  = rc.get("exam_integrity", {})

    scores_data = [
        ["Skill", "Score /10", "Assessment"],
        ["Problem Solving", f"{ps.get('score','—')}/10", ps.get("description","")[:80]+"…" if ps.get("description","") else ""],
        ["Knowledge Depth", f"{kd.get('score','—')}/10", kd.get("description","")[:80]+"…" if kd.get("description","") else ""],
        ["Writing & Expression", f"{we.get('score','—')}/10", we.get("description","")[:80]+"…" if we.get("description","") else ""],
        ["Exam Integrity", f"{ei.get('integrity_score','—')}%", ei.get("assessment","")],
    ]
    st = Table(scores_data, colWidths=[5*cm, 2.5*cm, 11*cm])
    st.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(-1,0), BLACK),
        ("TEXTCOLOR",   (0,0),(-1,0), colors.white),
        ("FONTNAME",    (0,0),(-1,0), "Helvetica-Bold"),
        ("FONTSIZE",    (0,0),(-1,-1), 9),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, LGRAY]),
        ("GRID",        (0,0),(-1,-1), 0.5, LGRAY),
        ("VALIGN",      (0,0),(-1,-1), "TOP"),
        ("PADDING",     (0,0),(-1,-1), 7),
    ]))
    story.append(st)
    story.append(Spacer(1, 0.3*cm))

    # ── Typing Speed ────────────────────────────────────────────────
    ts = rc.get("typing_speed_analysis", {})
    story.append(Paragraph("Typing & Behaviour Analysis", H2))
    story.append(Paragraph(
        f"<b>Speed:</b> {ts.get('wpm',0)} WPM — {ts.get('category','')}", BODY
    ))
    story.append(Paragraph(ts.get("description",""), BODY))

    # ── Recommendations ─────────────────────────────────────────────
    recs = rc.get("recommendations", [])
    if recs:
        story.append(Paragraph("Recommendations", H2))
        for i, r in enumerate(recs, 1):
            story.append(Paragraph(f"{i}. {r}", BODY))

    # ── Footer ──────────────────────────────────────────────────────
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=LGRAY))
    story.append(Paragraph(
        f"Generated by OS Education Center · Report ID: {report_doc.get('report_id','')} · "
        f"This report is confidential and intended for academic use only.",
        SMALL
    ))

    doc.build(story)
    return buf.getvalue()
