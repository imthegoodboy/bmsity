from __future__ import annotations

import json
import base64
import hashlib
import hmac
import re
import secrets
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .ai import evaluate_submission_with_openai, extract_schema_with_openai, ensure_openai_ready
from .database import get_db, init_db, json_loads, row_to_dict, rows_to_dicts
from .reports import generate_report
from .schemas import (
    EvaluationOut,
    EvaluationUpdate,
    ExamCreate,
    ExamOut,
    AuthOut,
    LoginIn,
    PasswordChangeIn,
    StartEvaluationOut,
    SubmissionCreated,
    SubmissionOut,
    StudentPortalOut,
)
from .settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="BmsitAi API", lifespan=lifespan)

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


def normalize_usn(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _token_signature(payload: str) -> str:
    digest = hmac.new(
        settings.auth_secret.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _b64_encode(digest)


def create_token(*, role: str, subject: str, force_password_change: bool = False) -> str:
    payload = {
        "role": role,
        "sub": subject,
        "force_password_change": force_password_change,
        "exp": int(time.time()) + settings.auth_token_ttl_minutes * 60,
    }
    encoded = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{encoded}.{_token_signature(encoded)}"


@dataclass(frozen=True)
class AuthUser:
    role: str
    subject: str
    force_password_change: bool = False


def _decode_token(token: str) -> AuthUser:
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid session token.") from exc

    expected = _token_signature(encoded)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid session token.")

    try:
        payload = json.loads(_b64_decode(encoded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid session token.") from exc

    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Session expired.")

    role = str(payload.get("role", ""))
    subject = str(payload.get("sub", ""))
    if role not in {"teacher", "student"} or not subject:
        raise HTTPException(status_code=401, detail="Invalid session token.")

    return AuthUser(
        role=role,
        subject=subject,
        force_password_change=bool(payload.get("force_password_change", False)),
    )


def current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Use a bearer session token.")
    return _decode_token(token)


def require_teacher(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher access required.")
    return user


def require_student(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Student access required.")
    return user


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    rounds = 260_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), rounds)
    return f"pbkdf2_sha256${rounds}${salt}${digest.hex()}"


def _verify_password(encoded: str, password: str) -> bool:
    try:
        algorithm, rounds_text, salt, expected = encoded.split("$", 3)
        rounds = int(rounds_text)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), rounds)
    return hmac.compare_digest(digest.hex(), expected)


def _ensure_student_account(conn: Any, usn: str) -> dict[str, Any] | None:
    normalized = normalize_usn(usn)
    if not normalized:
        return None
    current = row_to_dict(
        conn.execute("SELECT * FROM student_accounts WHERE usn = ?", (normalized,)).fetchone()
    )
    if current:
        return current
    created_at = now_iso()
    conn.execute(
        """
        INSERT INTO student_accounts (usn, password_hash, force_password_change, created_at, updated_at)
        VALUES (?, '', 1, ?, ?)
        """,
        (normalized, created_at, created_at),
    )
    return {
        "usn": normalized,
        "password_hash": "",
        "force_password_change": 1,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _submission_owner_usn(submission_id: str) -> str:
    with get_db() as conn:
        row = row_to_dict(conn.execute("SELECT usn FROM submissions WHERE id = ?", (submission_id,)).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="Submission not found.")
    return normalize_usn(row["usn"])


def require_submission_access(
    submission_id: str,
    user: AuthUser = Depends(current_user),
) -> AuthUser:
    if user.role == "teacher":
        return user
    if user.role == "student" and _submission_owner_usn(submission_id) == user.subject:
        return user
    raise HTTPException(status_code=403, detail="You can only access your own results.")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key),
        "model": settings.openai_model,
    }


@app.post("/auth/teacher/login", response_model=AuthOut)
def teacher_login(payload: LoginIn) -> AuthOut:
    if not hmac.compare_digest(payload.identifier.lower(), settings.teacher_email.lower()):
        raise HTTPException(status_code=401, detail="Invalid teacher credentials.")
    if not hmac.compare_digest(payload.password, settings.teacher_password):
        raise HTTPException(status_code=401, detail="Invalid teacher credentials.")

    return AuthOut(
        token=create_token(role="teacher", subject=settings.teacher_email),
        role="teacher",
        display_name="BMSIT&M Teacher",
        identifier=settings.teacher_email,
    )


@app.post("/auth/student/login", response_model=AuthOut)
def student_login(payload: LoginIn) -> AuthOut:
    usn = normalize_usn(payload.identifier)
    if not usn:
        raise HTTPException(status_code=422, detail="USN is required.")

    with get_db() as conn:
        submission = row_to_dict(
            conn.execute(
                """
                SELECT student_name, usn FROM submissions
                WHERE UPPER(usn) = ? AND status = 'completed' AND published = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (usn,),
            ).fetchone()
        )
        if not submission:
            raise HTTPException(status_code=401, detail="No published result found for this USN.")
        account = _ensure_student_account(conn, usn)

    if not account:
        raise HTTPException(status_code=401, detail="No student account found.")

    if account["password_hash"]:
        valid_password = _verify_password(account["password_hash"], payload.password)
    else:
        valid_password = hmac.compare_digest(normalize_usn(payload.password), usn)
    if not valid_password:
        raise HTTPException(status_code=401, detail="Invalid student credentials.")

    force_change = bool(account["force_password_change"])
    return AuthOut(
        token=create_token(role="student", subject=usn, force_password_change=force_change),
        role="student",
        display_name=submission["student_name"] or usn,
        identifier=usn,
        force_password_change=force_change,
    )


@app.get("/auth/me", response_model=AuthOut)
def auth_me(user: AuthUser = Depends(current_user)) -> AuthOut:
    if user.role == "teacher":
        return AuthOut(
            token=create_token(role="teacher", subject=user.subject),
            role="teacher",
            display_name="BMSIT&M Teacher",
            identifier=user.subject,
        )

    with get_db() as conn:
        account = _ensure_student_account(conn, user.subject)
        submission = row_to_dict(
            conn.execute(
                """
                SELECT student_name FROM submissions
                WHERE UPPER(usn) = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user.subject,),
            ).fetchone()
        )
    force_change = bool(account and account["force_password_change"])
    return AuthOut(
        token=create_token(role="student", subject=user.subject, force_password_change=force_change),
        role="student",
        display_name=(submission or {}).get("student_name") or user.subject,
        identifier=user.subject,
        force_password_change=force_change,
    )


@app.post("/auth/student/change-password", response_model=AuthOut)
def student_change_password(
    payload: PasswordChangeIn,
    user: AuthUser = Depends(require_student),
) -> AuthOut:
    with get_db() as conn:
        account = _ensure_student_account(conn, user.subject)
        submission = row_to_dict(
            conn.execute(
                """
                SELECT student_name FROM submissions
                WHERE UPPER(usn) = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user.subject,),
            ).fetchone()
        )
        if not account:
            raise HTTPException(status_code=404, detail="Student account not found.")

        if account["password_hash"]:
            current_valid = _verify_password(account["password_hash"], payload.current_password)
        else:
            current_valid = hmac.compare_digest(normalize_usn(payload.current_password), user.subject)
        if not current_valid:
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        if hmac.compare_digest(payload.new_password, user.subject):
            raise HTTPException(status_code=422, detail="Choose a password different from your USN.")

        conn.execute(
            """
            UPDATE student_accounts
            SET password_hash = ?, force_password_change = 0, updated_at = ?
            WHERE usn = ?
            """,
            (_hash_password(payload.new_password), now_iso(), user.subject),
        )

    return AuthOut(
        token=create_token(role="student", subject=user.subject, force_password_change=False),
        role="student",
        display_name=(submission or {}).get("student_name") or user.subject,
        identifier=user.subject,
        force_password_change=False,
    )


def _exam_from_row(row: dict[str, Any]) -> ExamOut:
    return ExamOut(
        id=row["id"],
        title=row["title"],
        subject=row["subject"],
        total_marks=row["total_marks"],
        max_questions_to_grade=row.get("max_questions_to_grade"),
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


def _insert_exam(payload: ExamCreate) -> ExamOut:
    exam_id = new_id("exam")
    created_at = now_iso()
    questions = [question.model_dump() for question in payload.questions]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO exams (
                id, title, subject, total_marks, max_questions_to_grade,
                instructions, questions_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exam_id,
                payload.title or "Untitled Exam",
                payload.subject,
                payload.total_marks,
                payload.max_questions_to_grade,
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
        max_questions_to_grade=payload.max_questions_to_grade,
        instructions=payload.instructions,
        questions=questions,
        created_at=created_at,
    )


@app.post("/exams", response_model=ExamOut)
def create_exam(payload: ExamCreate, _: AuthUser = Depends(require_teacher)) -> ExamOut:
    return _insert_exam(payload)


@app.post("/schema/extract", response_model=ExamOut)
async def create_exam_from_schema_image(
    subject: str = Form("General"),
    title: str = Form("Answer Schema"),
    default_marks: float | None = Form(None),
    file: UploadFile = File(...),
    _: AuthUser = Depends(require_teacher),
) -> ExamOut:
    try:
        ensure_openai_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if default_marks is not None and default_marks <= 0:
        raise HTTPException(status_code=422, detail="Marks must be greater than zero.")
    fallback_marks = float(default_marks or 10)

    schema_root = settings.upload_dir / "_schemas"
    schema_root.mkdir(parents=True, exist_ok=True)
    original = clean_filename(file.filename or "answer-schema")
    stored_path = schema_root / f"{uuid.uuid4().hex[:12]}_{original}"
    with stored_path.open("wb") as file_handle:
        shutil.copyfileobj(file.file, file_handle)

    try:
        extracted = extract_schema_with_openai(
            file_path=stored_path,
            subject=subject.strip() or "General",
            title=title.strip() or "Answer Schema",
            default_marks=fallback_marks,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    questions: list[dict[str, Any]] = []
    for index, question in enumerate(extracted.get("questions", []), start=1):
        text = str(question.get("text", "")).strip()
        model_answer = str(question.get("model_answer", "")).strip()
        if not text or not model_answer:
            continue
        max_marks = _as_positive_float(question.get("max_marks")) or fallback_marks
        questions.append(
            {
                "id": str(question.get("id") or f"Q{index}").strip() or f"Q{index}",
                "text": text,
                "max_marks": max(0.5, float(max_marks)),
                "model_answer": model_answer,
                "marking_rules": str(question.get("marking_rules", "")).strip(),
                "keywords": [
                    str(keyword).strip()
                    for keyword in question.get("keywords", [])
                    if str(keyword).strip()
                ],
            }
        )

    if not questions:
        raise HTTPException(
            status_code=400,
            detail="Could not find a question and answer schema in the uploaded image.",
        )

    extracted_total_marks = _as_positive_float(extracted.get("total_marks"))
    extracted_choice_limit = _as_positive_int(extracted.get("max_questions_to_grade"))
    choice_rule = str(extracted.get("choice_rule", "")).strip()
    extracted_instructions = str(extracted.get("instructions") or "").strip()
    choice_text = " ".join(
        [
            choice_rule,
            extracted_instructions,
            str(extracted.get("title") or title or ""),
            " ".join(question["text"] for question in questions),
        ]
    )
    if not extracted_choice_limit:
        extracted_choice_limit = _infer_choice_limit(choice_text, len(questions))
    questions, total_marks, max_questions_to_grade = _normalize_schema_questions(
        questions=questions,
        total_marks=extracted_total_marks,
        max_questions_to_grade=extracted_choice_limit,
        default_marks=fallback_marks,
    )
    instructions = "\n".join(
        part for part in [extracted_instructions, choice_rule] if part
    ).strip()
    if max_questions_to_grade:
        normalized_rule = f"Grading rule: best {max_questions_to_grade} of {len(questions)} questions count."
        if normalized_rule.lower() not in instructions.lower():
            instructions = "\n".join(part for part in [instructions, normalized_rule] if part).strip()

    payload = ExamCreate(
        title=str(extracted.get("title") or title or "Answer Schema").strip(),
        subject=str(extracted.get("subject") or subject or "General").strip(),
        instructions=instructions,
        total_marks=total_marks,
        max_questions_to_grade=max_questions_to_grade,
        questions=questions,
    )
    return _insert_exam(payload)


@app.get("/exams", response_model=list[ExamOut])
def list_exams(_: AuthUser = Depends(require_teacher)) -> list[ExamOut]:
    with get_db() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM exams ORDER BY created_at DESC").fetchall())
    return [_exam_from_row(row) for row in rows]


@app.get("/exams/{exam_id}", response_model=ExamOut)
def get_exam(exam_id: str, _: AuthUser = Depends(require_teacher)) -> ExamOut:
    exam = _get_exam_or_404(exam_id)
    return _exam_from_row({**exam, "questions_json": json.dumps(exam["questions"])})


@app.post("/exams/{exam_id}/submissions", response_model=SubmissionCreated)
async def create_submission(
    exam_id: str,
    student_name: str = Form(...),
    usn: str = Form(""),
    files: list[UploadFile] = File(...),
    _: AuthUser = Depends(require_teacher),
) -> SubmissionCreated:
    _get_exam_or_404(exam_id)
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one answer sheet file.")
    if not student_name.strip():
        raise HTTPException(status_code=422, detail="Student name is required.")
    normalized_usn = normalize_usn(usn)

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
            (submission_id, exam_id, student_name.strip(), normalized_usn, 0, created_at, created_at),
        )
        _ensure_student_account(conn, normalized_usn)
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
        usn=normalized_usn,
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
                    "attempted": bool(item["attempted"]),
                    "counts_toward_total": bool(item["counts_toward_total"]),
                    "review_required": bool(item["review_required"]),
                    "missing_points": json_loads(item["missing_points_json"], []),
                }
                for item in evaluations
            ],
        }
    )


@app.get("/exams/{exam_id}/submissions", response_model=list[SubmissionOut])
def list_submissions(exam_id: str, _: AuthUser = Depends(require_teacher)) -> list[SubmissionOut]:
    _get_exam_or_404(exam_id)
    with get_db() as conn:
        rows = rows_to_dicts(
            conn.execute(
                "SELECT id FROM submissions WHERE exam_id = ? ORDER BY created_at DESC", (exam_id,)
            ).fetchall()
        )
    return [_submission_bundle(row["id"]) for row in rows]


@app.get("/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(
    submission_id: str,
    _: AuthUser = Depends(require_submission_access),
) -> SubmissionOut:
    return _submission_bundle(submission_id)


@app.get("/students/me", response_model=StudentPortalOut)
def student_portal(user: AuthUser = Depends(require_student)) -> StudentPortalOut:
    with get_db() as conn:
        account = _ensure_student_account(conn, user.subject)
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT
                    s.id AS submission_id,
                    s.student_name,
                    s.usn,
                    e.id AS exam_id,
                    e.title,
                    e.subject,
                    e.total_marks AS exam_total_marks,
                    e.max_questions_to_grade,
                    e.created_at AS exam_created_at
                FROM submissions s
                JOIN exams e ON e.id = s.exam_id
                WHERE UPPER(s.usn) = ? AND s.status = 'completed' AND s.published = 1
                ORDER BY s.created_at DESC
                """,
                (user.subject,),
            ).fetchall()
        )

    submissions: list[dict[str, Any]] = []
    student_name = user.subject
    for row in rows:
        bundle = _submission_bundle(row["submission_id"])
        student_name = bundle.student_name or student_name
        submissions.append(
            {
                "id": bundle.id,
                "exam": {
                    "id": row["exam_id"],
                    "title": row["title"],
                    "subject": row["subject"],
                    "total_marks": row["exam_total_marks"],
                    "max_questions_to_grade": row["max_questions_to_grade"],
                    "created_at": row["exam_created_at"],
                },
                "student_name": bundle.student_name,
                "usn": bundle.usn,
                "status": bundle.status,
                "published": bool(bundle.published),
                "total_score": bundle.total_score,
                "total_marks": bundle.total_marks,
                "average_confidence": bundle.average_confidence,
                "error": bundle.error,
                "overall_feedback": bundle.overall_feedback,
                "weak_areas": bundle.weak_areas,
                "evaluations": bundle.evaluations,
                "created_at": bundle.created_at,
                "updated_at": bundle.updated_at,
            }
        )

    return StudentPortalOut(
        student_name=student_name,
        usn=user.subject,
        force_password_change=bool(account and account["force_password_change"]),
        submissions=submissions,
    )


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _as_positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _missing_answer_text(answer_text: str) -> bool:
    normalized = answer_text.strip().lower()
    if not normalized:
        return True
    missing_markers = [
        "no distinct answer",
        "no separate answer",
        "not found",
        "not visible",
        "no explicit response",
    ]
    return any(marker in normalized for marker in missing_markers)


def _infer_choice_limit(text: str, question_count: int) -> int | None:
    normalized = text.lower()
    patterns = [
        r"(?:answer|attempt|solve)\s+(?:any\s+)?(\d+)",
        r"(?:answer|attempt|solve)\s+(?:any\s+)?(one|two|three|four|five|six|seven|eight|nine|ten)",
        r"(\d+)\s+(?:out\s+of|of)\s+\d+",
        r"(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:out\s+of|of)\s+\w+",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        raw = match.group(1)
        value = int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw)
        if value and 0 < value <= question_count:
            return value
    return None


def _infer_choice_limit_from_total(questions: list[dict[str, Any]], total_marks: float | None) -> int | None:
    if not total_marks:
        return None
    running = 0.0
    for index, mark in enumerate(sorted((float(question["max_marks"]) for question in questions), reverse=True), start=1):
        running += mark
        if abs(running - total_marks) < 0.01:
            return index
    return None


def _normalize_schema_questions(
    *,
    questions: list[dict[str, Any]],
    total_marks: float | None,
    max_questions_to_grade: int | None,
    default_marks: float,
) -> tuple[list[dict[str, Any]], float | None, int | None]:
    if max_questions_to_grade and max_questions_to_grade > len(questions):
        max_questions_to_grade = None
    marks = [float(question["max_marks"]) for question in questions]
    inferred_choice_limit = _infer_choice_limit_from_total(questions, total_marks)
    if total_marks and inferred_choice_limit and sum(marks) > total_marks + 0.01:
        if (
            not max_questions_to_grade
            or max_questions_to_grade >= len(questions)
        ):
            max_questions_to_grade = inferred_choice_limit
    if not max_questions_to_grade:
        max_questions_to_grade = inferred_choice_limit

    if total_marks and max_questions_to_grade:
        expected_per_question = total_marks / max_questions_to_grade
        uniform = marks and all(abs(mark - marks[0]) < 0.01 for mark in marks)
        top_total = sum(sorted(marks, reverse=True)[:max_questions_to_grade])
        if expected_per_question > 0 and uniform and abs(top_total - total_marks) >= 0.01:
            suspicious_total_as_question_mark = marks[0] >= total_marks or marks[0] > expected_per_question * 1.5
            suspicious_default_as_total = abs(marks[0] - default_marks) < 0.01 and default_marks > expected_per_question * 1.5
            if suspicious_total_as_question_mark or suspicious_default_as_total:
                for question in questions:
                    question["max_marks"] = expected_per_question
                marks = [float(question["max_marks"]) for question in questions]

        matching_expected = sum(1 for mark in marks if abs(mark - expected_per_question) < 0.01)
        if (
            expected_per_question > 0
            and len(marks) >= 3
            and matching_expected / len(marks) >= 0.7
        ):
            for question in questions:
                mark = float(question["max_marks"])
                if 0 < mark < expected_per_question:
                    question["max_marks"] = expected_per_question

    if not total_marks:
        marks = sorted((float(question["max_marks"]) for question in questions), reverse=True)
        total_marks = (
            sum(marks[:max_questions_to_grade])
            if max_questions_to_grade
            else sum(marks)
        )

    return questions, total_marks, max_questions_to_grade


def _recalculate_submission(conn: Any, submission_id: str) -> None:
    exam = row_to_dict(
        conn.execute(
            """
            SELECT e.total_marks, e.max_questions_to_grade
            FROM submissions s
            JOIN exams e ON e.id = s.exam_id
            WHERE s.id = ?
            """,
            (submission_id,),
        ).fetchone()
    )
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT id, answer_text, attempted, final_score, max_marks, confidence
            FROM evaluations
            WHERE submission_id = ?
            """,
            (submission_id,),
        ).fetchall()
    )
    selected_ids: set[str]
    max_questions = exam and exam.get("max_questions_to_grade")
    if max_questions:
        candidates = [
            row
            for row in rows
            if row["attempted"] or str(row["answer_text"]).strip() or float(row["final_score"]) > 0
        ]
        selected = sorted(
            candidates,
            key=lambda row: (float(row["final_score"]), float(row["confidence"])),
            reverse=True,
        )[: int(max_questions)]
        selected_ids = {row["id"] for row in selected}
        total_score = sum(float(row["final_score"]) for row in selected)
        total_marks = float(exam["total_marks"]) if exam else sum(float(row["max_marks"]) for row in selected)
        confidence_rows = selected or candidates or rows
    else:
        selected_ids = {row["id"] for row in rows}
        total_score = sum(float(row["final_score"]) for row in rows)
        total_marks = sum(float(row["max_marks"]) for row in rows)
        confidence_rows = rows
    avg_confidence = (
        sum(float(row["confidence"]) for row in confidence_rows) / len(confidence_rows)
        if confidence_rows
        else 0
    )
    for row in rows:
        conn.execute(
            "UPDATE evaluations SET counts_toward_total = ? WHERE id = ?",
            (1 if row["id"] in selected_ids else 0, row["id"]),
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

        question_map = {str(question["id"]): question for question in exam["questions"]}
        seen_question_ids: set[str] = set()
        created_at = now_iso()
        with get_db() as conn:
            conn.execute("DELETE FROM evaluations WHERE submission_id = ?", (submission_id,))
            for item in result.get("questions", []):
                question_id = str(item.get("question_id", "")).strip()
                question = question_map.get(question_id)
                if not question or question_id in seen_question_ids:
                    continue
                seen_question_ids.add(question_id)
                max_marks = float(question["max_marks"])
                answer_text = str(item.get("answer_text", ""))
                attempted_raw = item.get("attempted")
                attempted = bool(attempted_raw) or not _missing_answer_text(answer_text)
                if not attempted:
                    answer_text = ""
                score = _clamp(float(item.get("score", 0)), 0, max_marks) if attempted else 0
                confidence = _clamp(float(item.get("confidence", 0)), 0, 100)
                review_required = (bool(item.get("review_required")) or confidence < 80) if attempted else False
                conn.execute(
                    """
                    INSERT INTO evaluations
                    (id, submission_id, question_id, question_text, answer_text, attempted, counts_toward_total,
                     score, max_marks, final_score, confidence, review_required, reason, missing_points_json,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("eval"),
                        submission_id,
                        question_id,
                        question["text"],
                        answer_text,
                        1 if attempted else 0,
                        0,
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
            for question_id, question in question_map.items():
                if question_id in seen_question_ids:
                    continue
                max_marks = float(question["max_marks"])
                conn.execute(
                    """
                    INSERT INTO evaluations
                    (id, submission_id, question_id, question_text, answer_text, attempted, counts_toward_total,
                     score, max_marks, final_score, confidence, review_required, reason, missing_points_json,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("eval"),
                        submission_id,
                        question_id,
                        question["text"],
                        "",
                        0,
                        0,
                        0,
                        max_marks,
                        0,
                        0,
                        1,
                        "The evaluation agent did not return this question. Teacher review is required before publishing.",
                        json.dumps(["No AI evaluation was returned for this question."]),
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
def start_evaluation(
    submission_id: str,
    background_tasks: BackgroundTasks,
    _: AuthUser = Depends(require_teacher),
) -> StartEvaluationOut:
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
            "UPDATE submissions SET status = 'running', error = '', published = 0, updated_at = ? WHERE id = ?",
            (now_iso(), submission_id),
        )

    background_tasks.add_task(_run_evaluation, submission_id)
    return StartEvaluationOut(
        submission_id=submission_id,
        status="running",
        message="Evaluation started.",
    )


@app.post("/submissions/{submission_id}/publish", response_model=SubmissionOut)
def publish_submission(
    submission_id: str,
    _: AuthUser = Depends(require_teacher),
) -> SubmissionOut:
    submission = _submission_bundle(submission_id)
    if submission.status != "completed":
        raise HTTPException(status_code=400, detail="Complete evaluation before publishing.")
    if not submission.evaluations:
        raise HTTPException(status_code=400, detail="Publish requires at least one evaluated question.")

    with get_db() as conn:
        conn.execute(
            "UPDATE submissions SET published = 1, updated_at = ? WHERE id = ?",
            (now_iso(), submission_id),
        )
    return _submission_bundle(submission_id)


@app.patch("/evaluations/{evaluation_id}", response_model=EvaluationOut)
def update_evaluation(
    evaluation_id: str,
    payload: EvaluationUpdate,
    _: AuthUser = Depends(require_teacher),
) -> EvaluationOut:
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
        attempted = 1 if current["attempted"] or float(final_score) > 0 else 0

        conn.execute(
            """
            UPDATE evaluations
            SET final_score = ?, reason = ?, review_required = ?, attempted = ?, updated_at = ?
            WHERE id = ?
            """,
            (final_score, reason, review_required, attempted, now_iso(), evaluation_id),
        )
        _recalculate_submission(conn, current["submission_id"])
        updated = row_to_dict(
            conn.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone()
        )

    return EvaluationOut(
        **{
            **updated,
            "attempted": bool(updated["attempted"]),
            "counts_toward_total": bool(updated["counts_toward_total"]),
            "review_required": bool(updated["review_required"]),
            "missing_points": json_loads(updated["missing_points_json"], []),
        }
    )


@app.get("/submissions/{submission_id}/report")
def export_report(
    submission_id: str,
    user: AuthUser = Depends(require_submission_access),
) -> FileResponse:
    submission = _submission_bundle(submission_id)
    if submission.status != "completed":
        raise HTTPException(status_code=400, detail="Complete evaluation before exporting.")
    if user.role == "student" and not submission.published:
        raise HTTPException(status_code=403, detail="This result has not been published yet.")
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
