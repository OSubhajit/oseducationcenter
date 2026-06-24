"""
services/ai_grader.py — IMPROVED VERSION WITH BETTER ERROR LOGGING
--------------------------------------------------------------------
This version adds detailed error logging to help diagnose Groq API issues.

To use this:
1. Backup your current ai_grader.py
2. Replace it with this version
3. Restart your Flask server
4. Submit an exam and check the console for detailed error messages
"""
import json
import re
from flask import current_app
from groq import Groq


# ── Groq client ──────────────────────────────────────────────────

def _get_client() -> Groq:
    api_key = current_app.config["GROQ_API_KEY"]
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured in .env file")
    return Groq(api_key=api_key)


# ── Written answer grader ────────────────────────────────────────

def grade_written_answer(question: str,
                         student_answer: str,
                         rubric: str,
                         max_marks: int) -> dict:
    """
    Sends the question + student answer to Groq.
    Returns: {"score": int, "feedback": str, "reasoning": str}
    """
    try:
        client = _get_client()
        model  = current_app.config["GROQ_MODEL"]
        
        print(f"[Groq] Grading question with model: {model}")

        prompt = f"""You are a strict but fair exam evaluator for OS Education Center, Assam, India.

QUESTION:
{question}

MARKING RUBRIC (what a correct answer should cover):
{rubric}

MAXIMUM MARKS: {max_marks}

STUDENT'S ANSWER:
{student_answer}

INSTRUCTIONS:
- Award marks based ONLY on the rubric.
- Be strict. Do not award marks for irrelevant content.
- Feedback must be in simple English, helpful for the student.
- Score must be an integer between 0 and {max_marks}.
- Respond ONLY with valid JSON. No extra text, no markdown, no explanation outside JSON.

RESPOND IN THIS EXACT FORMAT:
{{
  "score": <integer 0 to {max_marks}>,
  "feedback": "<one or two sentences of feedback for the student>",
  "reasoning": "<brief internal reasoning for the score>"
}}"""

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,   # low temp = consistent grading
            max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()
        
        print(f"[Groq] Raw response: {raw[:200]}...")

        # strip markdown code fences if Groq adds them
        raw = re.sub(r"```(?:json)?", "", raw).strip()

        result = json.loads(raw)

        # Defensive: LLMs don't always perfectly follow the requested schema
        # (esp. under max_tokens limits). Missing keys here would otherwise
        # raise an uncaught KeyError later in grade_full_exam, causing a 500
        # and reopening the student's session. Always return all three keys.
        result.setdefault("score", 0)
        result.setdefault("feedback", "")
        result.setdefault("reasoning", "")

        # safety clamp — score must be within 0 to max_marks
        result["score"] = max(0, min(int(result["score"]), max_marks))
        
        print(f"[Groq] ✅ Success - Score: {result['score']}/{max_marks}")
        return result

    except json.JSONDecodeError as e:
        # fallback if Groq returns non-JSON
        error_msg = f"JSON parse error at position {e.pos}: {e.msg}"
        print(f"[Groq] ❌ JSON Decode Error: {error_msg}")
        print(f"[Groq] Raw response was: {raw[:500]}")
        return {
            "score"     : 0,
            "feedback"  : "Could not evaluate answer automatically. Please contact admin.",
            "reasoning" : f"{error_msg}. Raw: {raw[:200]}",
        }
    
    except ValueError as e:
        # API key or configuration error
        error_msg = str(e)
        print(f"[Groq] ❌ Configuration Error: {error_msg}")
        return {
            "score"     : 0,
            "feedback"  : "Grading service misconfigured.",
            "reasoning" : error_msg,
        }
    
    except Exception as e:
        # All other errors (API errors, network issues, etc.)
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"[Groq] ❌ {error_type}: {error_msg}")
        
        # Try to provide more specific error messages
        if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            feedback = "API key authentication failed. Check GROQ_API_KEY in .env"
        elif "rate" in error_msg.lower() or "limit" in error_msg.lower():
            feedback = "Rate limit exceeded. Please try again later."
        elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
            feedback = "Network connection error. Check internet connectivity."
        else:
            feedback = "Evaluation service unavailable."
        
        return {
            "score"     : 0,
            "feedback"  : feedback,
            "reasoning" : f"{error_type}: {error_msg}",
        }


# ── MCQ auto-grader (no AI needed) ──────────────────────────────

def grade_mcq(questions: list, student_answers: list) -> dict:
    """
    questions      : list of question dicts from the exam document
    student_answers: list of {"q_id": "Q001", "answer": "A"}

    Returns:
    {
      "total_mcq_marks": int,
      "scored_mcq_marks": int,
      "breakdown": [{"q_id","correct","student_answer","marks_awarded"}]
    }
    """
    # build answer lookup from student submission
    answer_map = {a["q_id"]: a["answer"] for a in student_answers}

    total  = 0
    scored = 0
    breakdown = []

    for q in questions:
        if q["type"] != "mcq":
            continue

        q_id           = q["q_id"]
        correct        = q["correct_answer"]
        marks          = q["marks"]
        student_ans    = answer_map.get(q_id, "")   # blank if not answered
        is_correct     = student_ans.strip().upper() == correct.strip().upper()
        marks_awarded  = marks if is_correct else 0

        total  += marks
        scored += marks_awarded

        breakdown.append({
            "q_id"          : q_id,
            "correct"       : is_correct,
            "student_answer": student_ans,
            "correct_answer": correct,
            "marks_awarded" : marks_awarded,
        })

    return {
        "total_mcq_marks" : total,
        "scored_mcq_marks": scored,
        "breakdown"       : breakdown,
    }


# ── Full exam grader (MCQ + Written combined) ────────────────────

def grade_full_exam(exam: dict, student_answers: list) -> dict:
    """
    exam           : full exam document from MongoDB
    student_answers: list of {"q_id", "answer"}

    Returns complete evaluation ready to store in results collection.
    {
      "total_marks"   : int,
      "scored_marks"  : int,
      "mcq_score"     : int,
      "written_score" : int,
      "ai_evaluation" : {"written_answers": [...]}
    }
    """
    questions    = exam["questions"]
    answer_map   = {a["q_id"]: a["answer"] for a in student_answers}

    # ── Step 1: Grade MCQs ───────────────────────────
    mcq_result   = grade_mcq(questions, student_answers)
    mcq_scored   = mcq_result["scored_mcq_marks"]

    # ── Step 2: Grade written answers via Groq ───────
    written_results = []
    written_scored  = 0

    for q in questions:
        if q["type"] != "written":
            continue

        student_ans = answer_map.get(q["q_id"], "")
        print(f"[AI Grader] Processing written question: {q['q_id']}")
        
        evaluation  = grade_written_answer(
            question       = q["question"],
            student_answer = student_ans if student_ans else "(No answer provided)",
            rubric         = q.get("ai_rubric", "Evaluate based on correctness and clarity."),
            max_marks      = q["marks"],
        )

        written_scored += evaluation["score"]
        written_results.append({
            "q_id"          : q["q_id"],
            "question"      : q["question"],
            "student_answer": student_ans,
            "max_marks"     : q["marks"],
            "score"         : evaluation["score"],
            "feedback"      : evaluation["feedback"],
            "reasoning"     : evaluation["reasoning"],
        })

    # ── Step 3: Totals ───────────────────────────────
    total_marks  = exam["total_marks"]
    scored_marks = mcq_scored + written_scored
    
    print(f"[AI Grader] Final scores - MCQ: {mcq_scored}, Written: {written_scored}, Total: {scored_marks}/{total_marks}")

    return {
        "total_marks"   : total_marks,
        "scored_marks"  : scored_marks,
        "mcq_score"     : mcq_scored,
        "written_score" : written_scored,
        "ai_evaluation" : {
            "mcq_breakdown"  : mcq_result["breakdown"],
            "written_answers": written_results,
        },
    }
