from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .ai import evaluate_submission_with_openai, ensure_openai_ready
from .database import get_db, init_db, json_loads, row_to_dict, rows_to_dicts
from .reports import generate_report
from .schemas import (
    EvaluationOut,
    EvaluationUpdate,
    ExamCreate,
    ExamOut,
    StartEvaluationOut,
    SubmissionCreated,
    SubmissionOut,
)
from .settings import settings


app = FastAPI(title="BmsitAi API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def clean_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._")
    return safe or "answer-sheet"


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key),
        "model": settings.openai_model,
    }


def _exam_from_row(row: dict[str, Any]) -> ExamOut:
    return ExamOut(
        id=row["id"],
        title=row["title"],
        subject=row["subject"],
        total_marks=row["total_marks"],
        instructions=row["instructions"],
        questions=json_loads(row["questions_json"], []),
        created_at=row["created_at"],
    )


def _get_exam_or_404(exam_id: str) -> dict[str, Any]:
    with get_db() as conn:
        row = row_to_dict(conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="Exam not found.")
    row["questions"] = json_loads(row["questions_json"], [])
    return row


@app.post("/exams", response_model=ExamOut)
def create_exam(payload: ExamCreate) -> ExamOut:
    exam_id = new_id("exam")
    created_at = now_iso()
    questions = [question.model_dump() for question in payload.questions]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO exams (id, title, subject, total_marks, instructions, questions_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exam_id,
                payload.title or "Untitled Exam",
                payload.subject,
                payload.total_marks,
                payload.instructions,
                json.dumps(questions),
                created_at,
            ),
        )
    return ExamOut(
        id=exam_id,
        title=payload.title or "Untitled Exam",
        subject=payload.subject,
        total_marks=float(payload.total_marks or 0),
        instructions=payload.instructions,
        questions=questions,
        created_at=created_at,
    )


@app.get("/exams", response_model=list[ExamOut])
def list_exams() -> list[ExamOut]:
    with get_db() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM exams ORDER BY created_at DESC").fetchall())
    return [_exam_from_row(row) for row in rows]


@app.get("/exams/{exam_id}", response_model=ExamOut)
def get_exam(exam_id: str) -> ExamOut:
    exam = _get_exam_or_404(exam_id)
    return _exam_from_row({**exam, "questions_json": json.dumps(exam["questions"])})


@app.post("/exams/{exam_id}/submissions", response_model=SubmissionCreated)
async def create_submission(
    exam_id: str,
    student_name: str = Form(...),
    usn: str = Form(""),
    files: list[UploadFile] = File(...),
) -> SubmissionCreated:
    _get_exam_or_404(exam_id)
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one answer sheet file.")
    if not student_name.strip():
        raise HTTPException(status_code=422, detail="Student name is required.")

    created_at = now_iso()
    submission_id = new_id("sub")
    upload_root = settings.upload_dir / submission_id
    upload_root.mkdir(parents=True, exist_ok=True)

    saved_files: list[tuple[str, str, str, str, int]] = []
    for index, upload in enumerate(files, start=1):
        original = clean_filename(upload.filename or f"sheet-{index}")
        stored_name = f"{index:02d}_{uuid.uuid4().hex[:8]}_{original}"
        stored_path = upload_root / stored_name
        with stored_path.open("wb") as file_handle:
            shutil.copyfileobj(upload.file, file_handle)
        saved_files.append(
            (
                new_id("file"),
                original,
                str(stored_path),
                upload.content_type or "application/octet-stream",
                stored_path.stat().st_size,
            )
        )

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO submissions
            (id, exam_id, student_name, usn, status, total_marks, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'uploaded', ?, ?, ?)
            """,
            (submission_id, exam_id, student_name.strip(), usn.strip(), 0, created_at, created_at),
        )
        conn.executemany(
            """
            INSERT INTO submission_files
            (id, submission_id, original_name, stored_path, mime_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (file_id, submission_id, original, stored_path, mime, size, created_at)
                for file_id, original, stored_path, mime, size in saved_files
            ],
        )

    return SubmissionCreated(
        id=submission_id,
        exam_id=exam_id,
        student_name=student_name.strip(),
        usn=usn.strip(),
        status="uploaded",
    )


def _submission_bundle(submission_id: str) -> SubmissionOut:
    with get_db() as conn:
        submission = row_to_dict(
            conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        )
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found.")
        files = rows_to_dicts(
            conn.execute(
                "SELECT id, original_name, mime_type, size_bytes FROM submission_files WHERE submission_id = ?",
                (submission_id,),
            ).fetchall()
        )
        evaluations = rows_to_dicts(
            conn.execute(
                "SELECT * FROM evaluations WHERE submission_id = ? ORDER BY question_id",
                (submission_id,),
            ).fetchall()
        )

    return SubmissionOut(
        **{
            **submission,
            "weak_areas": json_loads(submission["weak_areas_json"], []),
            "files": files,
            "evaluations": [
                {
                    **item,
                    "review_required": bool(item["review_required"]),
                    "missing_points": json_loads(item["missing_points_json"], []),
                }
                for item in evaluations
            ],
        }
    )


@app.get("/exams/{exam_id}/submissions", response_model=list[SubmissionOut])
def list_submissions(exam_id: str) -> list[SubmissionOut]:
    _get_exam_or_404(exam_id)
    with get_db() as conn:
        rows = rows_to_dicts(
            conn.execute(
                "SELECT id FROM submissions WHERE exam_id = ? ORDER BY created_at DESC", (exam_id,)
            ).fetchall()
        )
    return [_submission_bundle(row["id"]) for row in rows]


@app.get("/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: str) -> SubmissionOut:
    return _submission_bundle(submission_id)


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def _recalculate_submission(conn: Any, submission_id: str) -> None:
    rows = rows_to_dicts(
        conn.execute(
            "SELECT final_score, max_marks, confidence FROM evaluations WHERE submission_id = ?",
            (submission_id,),
        ).fetchall()
    )
    total_score = sum(float(row["final_score"]) for row in rows)
    total_marks = sum(float(row["max_marks"]) for row in rows)
    avg_confidence = (
        sum(float(row["confidence"]) for row in rows) / len(rows) if rows else 0
    )
    conn.execute(
        """
        UPDATE submissions
        SET total_score = ?, total_marks = ?, average_confidence = ?, updated_at = ?
        WHERE id = ?
        """,
        (total_score, total_marks, avg_confidence, now_iso(), submission_id),
    )


def _run_evaluation(submission_id: str) -> None:
    try:
        with get_db() as conn:
            submission = row_to_dict(
                conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            )
            if not submission:
                return
            exam = row_to_dict(
                conn.execute("SELECT * FROM exams WHERE id = ?", (submission["exam_id"],)).fetchone()
            )
            files = rows_to_dicts(
                conn.execute(
                    "SELECT stored_path FROM submission_files WHERE submission_id = ? ORDER BY original_name",
                    (submission_id,),
                ).fetchall()
            )

        if not exam:
            raise RuntimeError("Exam not found.")
        exam["questions"] = json_loads(exam["questions_json"], [])
        result = evaluate_submission_with_openai(
            exam=exam,
            student_name=submission["student_name"],
            usn=submission["usn"],
            file_paths=[Path(row["stored_path"]) for row in files],
        )

        question_map = {question["id"]: question for question in exam["questions"]}
        created_at = now_iso()
        with get_db() as conn:
            conn.execute("DELETE FROM evaluations WHERE submission_id = ?", (submission_id,))
            for item in result.get("questions", []):
                question_id = str(item.get("question_id", "")).strip()
                question = question_map.get(question_id)
                if not question:
                    continue
                max_marks = float(question["max_marks"])
                score = _clamp(float(item.get("score", 0)), 0, max_marks)
                confidence = _clamp(float(item.get("confidence", 0)), 0, 100)
                review_required = bool(item.get("review_required")) or confidence < 80
                conn.execute(
                    """
                    INSERT INTO evaluations
                    (id, submission_id, question_id, question_text, answer_text, score, max_marks,
                     final_score, confidence, review_required, reason, missing_points_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("eval"),
                        submission_id,
                        question_id,
                        question["text"],
                        str(item.get("answer_text", "")),
                        score,
                        max_marks,
                        score,
                        confidence,
                        1 if review_required else 0,
                        str(item.get("reason", "")),
                        json.dumps(item.get("missing_points", [])),
                        created_at,
                        created_at,
                    ),
                )
            summary = result.get("summary", {})
            conn.execute(
                """
                UPDATE submissions
                SET status = 'completed', error = '', overall_feedback = ?, weak_areas_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(summary.get("overall_feedback", "")),
                    json.dumps(summary.get("weak_areas", [])),
                    now_iso(),
                    submission_id,
                ),
            )
            _recalculate_submission(conn, submission_id)
    except Exception as exc:
        with get_db() as conn:
            conn.execute(
                """
                UPDATE submissions
                SET status = 'failed', error = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(exc), now_iso(), submission_id),
            )


@app.post("/submissions/{submission_id}/evaluate", response_model=StartEvaluationOut)
def start_evaluation(submission_id: str, background_tasks: BackgroundTasks) -> StartEvaluationOut:
    try:
        ensure_openai_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    submission = _submission_bundle(submission_id)
    if not submission.files:
        raise HTTPException(status_code=400, detail="Upload at least one answer sheet file.")
    if submission.status == "running":
        return StartEvaluationOut(
            submission_id=submission_id,
            status="running",
            message="Evaluation already running.",
        )

    with get_db() as conn:
        conn.execute(
            "UPDATE submissions SET status = 'running', error = '', updated_at = ? WHERE id = ?",
            (now_iso(), submission_id),
        )

    background_tasks.add_task(_run_evaluation, submission_id)
    return StartEvaluationOut(
        submission_id=submission_id,
        status="running",
        message="Evaluation started.",
    )


@app.patch("/evaluations/{evaluation_id}", response_model=EvaluationOut)
def update_evaluation(evaluation_id: str, payload: EvaluationUpdate) -> EvaluationOut:
    with get_db() as conn:
        current = row_to_dict(
            conn.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone()
        )
        if not current:
            raise HTTPException(status_code=404, detail="Evaluation not found.")

        final_score = current["final_score"]
        if payload.final_score is not None:
            final_score = _clamp(float(payload.final_score), 0, float(current["max_marks"]))
        reason = current["reason"] if payload.reason is None else payload.reason
        review_required = (
            current["review_required"]
            if payload.review_required is None
            else (1 if payload.review_required else 0)
        )

        conn.execute(
            """
            UPDATE evaluations
            SET final_score = ?, reason = ?, review_required = ?, updated_at = ?
            WHERE id = ?
            """,
            (final_score, reason, review_required, now_iso(), evaluation_id),
        )
        _recalculate_submission(conn, current["submission_id"])
        updated = row_to_dict(
            conn.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone()
        )

    return EvaluationOut(
        **{
            **updated,
            "review_required": bool(updated["review_required"]),
            "missing_points": json_loads(updated["missing_points_json"], []),
        }
    )


@app.get("/submissions/{submission_id}/report")
def export_report(submission_id: str) -> FileResponse:
    submission = _submission_bundle(submission_id)
    if submission.status != "completed":
        raise HTTPException(status_code=400, detail="Complete evaluation before exporting.")
    exam = _get_exam_or_404(submission.exam_id)
    evaluations = [item.model_dump() for item in submission.evaluations]
    destination = settings.report_dir / f"{submission_id}.pdf"
    generate_report(
        destination=destination,
        exam=exam,
        submission=submission.model_dump(),
        evaluations=evaluations,
    )
    return FileResponse(
        destination,
        media_type="application/pdf",
        filename=f"{submission.student_name or 'student'}-evaluation.pdf",
    )
