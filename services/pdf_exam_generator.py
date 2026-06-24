"""
services/pdf_exam_generator.py
-------------------------------
Reads an uploaded PDF, extracts its text, then asks Groq to generate
a UNIQUE 100-mark question paper (Short Answer + Long Answer only).

Every call produces a different structure — the marks distribution,
question count, writing style, section order, and question emphasis
all vary because Groq is seeded with a random token each time.

Public API
----------
generate_paper_from_pdf(pdf_bytes, course_name, teacher_id)
    → dict  (paper document ready to insert into exam_papers collection)
"""

import io
import json
import random
import string
import re
from datetime import datetime

# PDF text extraction — pdfplumber preferred, PyPDF2 as fallback
def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        text = "\n\n".join(pages).strip()
        if text:
            return text
    except Exception:
        pass

    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        pages  = [reader.pages[i].extract_text() or "" for i in range(len(reader.pages))]
        return "\n\n".join(pages).strip()
    except Exception as e:
        raise ValueError(f"Could not extract text from PDF: {e}")


# ── Unique paper structure generator ────────────────────────────────────────
# These helpers ensure every paper looks structurally different.

_STYLE_PREFIXES = [
    "Explain in detail",
    "Describe the concept of",
    "With suitable examples, discuss",
    "Analyze and elaborate on",
    "Define and illustrate",
    "Compare and contrast",
    "Critically evaluate",
    "Write a comprehensive note on",
    "Discuss the significance of",
    "Examine the role of",
]

_LONG_STYLE_PREFIXES = [
    "Write an in-depth essay on",
    "Provide a detailed analysis of",
    "With appropriate examples and diagrams, explain",
    "Discuss comprehensively",
    "Critically examine and evaluate",
    "Write a detailed account of",
    "Elaborate extensively on",
]

def _random_token(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def _pick_structure() -> dict:
    """
    Returns a random (but valid) marks distribution summing to exactly 100.
    Varies the number of short and long questions and their per-question marks.
    """
    structures = [
        # (short_count, short_marks, long_count, long_marks)  → total
        (8,  5, 4, 15),   # 40 + 60 = 100
        (10, 4, 4, 15),   # 40 + 60 = 100
        (6,  5, 5, 14),   # 30 + 70 = 100
        (5,  4, 6, 13),   # 20 + 78... actually 20+80 off — let me fix
        (10, 5, 5, 10),   # 50 + 50 = 100
        (6,  4, 4, 19),   # 24 + 76... off
        (8,  4, 4, 17),   # 32 + 68 = 100
        (5,  6, 5, 14),   # 30 + 70 = 100
        (6,  5, 4, 17+1), # just use verified ones
    ]
    # Only use verified structures
    verified = [
        {"short_count": 8,  "short_marks": 5,  "long_count": 4, "long_marks": 15, "short_total": 40, "long_total": 60},
        {"short_count": 10, "short_marks": 4,  "long_count": 4, "long_marks": 15, "short_total": 40, "long_total": 60},
        {"short_count": 6,  "short_marks": 5,  "long_count": 5, "long_marks": 14, "short_total": 30, "long_total": 70},
        {"short_count": 10, "short_marks": 5,  "long_count": 5, "long_marks": 10, "short_total": 50, "long_total": 50},
        {"short_count": 8,  "short_marks": 4,  "long_count": 4, "long_marks": 17, "short_total": 32, "long_total": 68},
        {"short_count": 5,  "short_marks": 6,  "long_count": 5, "long_marks": 14, "short_total": 30, "long_total": 70},
        {"short_count": 12, "short_marks": 3,  "long_count": 4, "long_marks": 16, "short_total": 36, "long_total": 64},
        {"short_count": 7,  "short_marks": 5,  "long_count": 5, "long_marks": 13, "short_total": 35, "long_total": 65},
    ]
    # Verify totals
    valid = [s for s in verified if s["short_total"] + s["long_total"] == 100]
    # Fix any off ones: 32+66=98, 35+65=100 ok, 36+64=100 ok
    # Recheck manually:
    rechecked = []
    for s in verified:
        sc = s["short_count"] * s["short_marks"]
        lc = s["long_count"] * s["long_marks"]
        if sc + lc == 100:
            s["short_total"] = sc
            s["long_total"] = lc
            rechecked.append(s)

    if not rechecked:
        return {"short_count": 8, "short_marks": 5, "long_count": 4, "long_marks": 15,
                "short_total": 40, "long_total": 60}
    return random.choice(rechecked)


# ── System prompt ────────────────────────────────────────────────────────────

def _build_prompt(pdf_text: str, course_name: str, structure: dict, seed: str) -> str:
    short_style  = random.choice(_STYLE_PREFIXES)
    long_style   = random.choice(_LONG_STYLE_PREFIXES)
    q_labels     = random.choice([
        ("Section A", "Section B"),
        ("Part I", "Part II"),
        ("Group A", "Group B"),
    ])

    return f"""You are an expert academic examiner for "{course_name}".
Your task: generate a complete 100-mark examination paper from the study material below.
Uniqueness seed (vary your output based on this): {seed}

STRUCTURE (MANDATORY — do not change totals):
- {q_labels[0]}: {structure["short_count"]} Short Answer questions × {structure["short_marks"]} marks each = {structure["short_total"]} marks
- {q_labels[1]}: {structure["long_count"]} Long Answer questions × {structure["long_marks"]} marks each = {structure["long_total"]} marks
- TOTAL: 100 marks

RULES:
1. Questions MUST come directly from the study material provided.
2. Short answer questions: Prefer style "{short_style}..." (but vary between questions).
3. Long answer questions: Prefer style "{long_style}..." (but vary between questions).
4. Every question must be different — no repetition of topics.
5. ai_rubric must list specific marking criteria (how to award partial marks).
6. model_answer must be a concise but complete ideal answer.
7. Output ONLY valid JSON — no markdown, no code fences, no preamble.

STUDY MATERIAL:
---
{pdf_text[:12000]}
---

OUTPUT FORMAT (exact JSON, no extra text):
{{
  "paper_title": "{course_name} — Examination Paper",
  "section_a_name": "{q_labels[0]} — Short Answer Questions",
  "section_b_name": "{q_labels[1]} — Long Answer Questions",
  "instructions": "Answer ALL questions. Write clearly and concisely. Total marks: 100. Duration: 3 hours.",
  "questions": [
    {{
      "q_id": "Q001",
      "section": "A",
      "type": "short",
      "question": "...",
      "marks": {structure["short_marks"]},
      "ai_rubric": "Award 1 mark for each of the following points: ...",
      "model_answer": "..."
    }},
    {{
      "q_id": "Q{str(structure['short_count']+1).zfill(3)}",
      "section": "B",
      "type": "long",
      "question": "...",
      "marks": {structure["long_marks"]},
      "ai_rubric": "Full marks ({structure['long_marks']}) for: ... Partial marks for: ...",
      "model_answer": "..."
    }}
  ]
}}

Generate exactly {structure["short_count"]} Section A questions followed by {structure["long_count"]} Section B questions."""


# ── Main public function ─────────────────────────────────────────────────────

def generate_paper_from_pdf(pdf_bytes: bytes, course_name: str,
                             teacher_id: str, course_id: str) -> dict:
    """
    Analyse the PDF and generate a unique 100-mark exam paper via Groq.

    Returns a paper_doc dict ready for the exam_papers collection.
    Raises ValueError on extraction failure, RuntimeError on Groq failure.
    """
    from flask import current_app
    from groq import Groq

    # 1. Extract text
    pdf_text = _extract_pdf_text(pdf_bytes)
    if len(pdf_text.strip()) < 200:
        raise ValueError(
            "PDF contains too little readable text. "
            "Please upload a text-based PDF (not a scanned image)."
        )

    # 2. Pick random structure
    structure = _pick_structure()
    seed      = _random_token(12)

    # 3. Build prompt
    prompt = _build_prompt(pdf_text, course_name, structure, seed)

    # 4. Call Groq
    client  = Groq(api_key=current_app.config["GROQ_API_KEY"])
    model   = current_app.config.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert exam paper setter. "
                    "You ALWAYS respond with valid JSON only — no markdown, no explanation."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,     # high temp → more variation between calls
        max_tokens=4096,
    )

    raw = response.choices[0].message.content.strip()

    # 5. Parse JSON — strip stray fences if model sneaks them in
    raw_clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw_clean = re.sub(r"\s*```$", "", raw_clean, flags=re.MULTILINE).strip()

    try:
        paper_data = json.loads(raw_clean)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Groq returned malformed JSON. Error: {e}. "
            "Please try again — the model occasionally produces imperfect output."
        )

    # 6. Validate totals
    questions = paper_data.get("questions", [])
    if not questions:
        raise RuntimeError("Groq did not generate any questions. Please try again.")

    total = sum(q.get("marks", 0) for q in questions)
    if total != 100:
        # Attempt to fix: scale marks proportionally
        if total > 0:
            scale = 100 / total
            for q in questions:
                q["marks"] = round(q["marks"] * scale)
            # correct any rounding drift
            diff = 100 - sum(q["marks"] for q in questions)
            if diff != 0:
                questions[-1]["marks"] += diff

    # 7. Build paper document
    import shortuuid
    paper_id = f"PAPER-{shortuuid.ShortUUID().random(length=8).upper()}"

    return {
        "paper_id"       : paper_id,
        "course_id"      : course_id,
        "course_name"    : course_name,
        "teacher_id"     : teacher_id,
        "paper_title"    : paper_data.get("paper_title", f"{course_name} — Exam Paper"),
        "instructions"   : paper_data.get("instructions", "Answer all questions."),
        "section_a_name" : paper_data.get("section_a_name", "Section A — Short Answer"),
        "section_b_name" : paper_data.get("section_b_name", "Section B — Long Answer"),
        "questions"      : questions,
        "total_marks"    : 100,
        "pass_marks"     : 40,
        "duration_minutes": 180,
        "structure"      : structure,
        "seed"           : seed,
        "pdf_text_len"   : len(pdf_text),
        "status"         : "draft",      # teacher reviews before publishing
        "created_at"     : datetime.utcnow(),
        "published_at"   : None,
        "exam_id"        : None,         # set when teacher publishes → creates exam
    }
