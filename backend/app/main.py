from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import mimetypes
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

from .ai import (
    detect_attempted_questions_with_openai,
    evaluate_submission_with_openai,
    extract_schema_with_openai,
    ensure_openai_ready,
    verify_evaluation_with_openai,
    verify_schema_with_openai,
)
from .database import get_db, init_db, json_loads, row_to_dict, rows_to_dicts
from .reports import generate_report, reportable_evaluations
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


SUPPORTED_UPLOAD_EXTENSIONS = {".jpeg", ".jpg", ".pdf", ".png", ".webp"}
SUPPORTED_UPLOAD_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
UPLOAD_EXTENSION_BY_MIME_TYPE = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="BmsitAi API", lifespan=lifespan)

LOCAL_FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([settings.frontend_origin, *LOCAL_FRONTEND_ORIGINS])),
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


@dataclass(frozen=True)
class CheckingScope:
    ids: tuple[str, ...]
    parent_ids: frozenset[str]
    whole_parent_ids: frozenset[str]
    part_ids_by_parent: dict[str, frozenset[str]]
    limited: bool = False

    @property
    def active(self) -> bool:
        return self.limited or bool(self.ids)


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
        "schema_model": settings.openai_schema_model,
        "evaluation_model": settings.openai_evaluation_model,
        "verifier_model": settings.openai_verifier_model,
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
        choice_rules=json_loads(row.get("choice_rules_json", "[]"), []),
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
    row["choice_rules"] = json_loads(row.get("choice_rules_json", "[]"), [])
    return row


def _insert_exam(payload: ExamCreate) -> ExamOut:
    exam_id = new_id("exam")
    created_at = now_iso()
    questions = [question.model_dump() for question in payload.questions]
    choice_rules = [rule.model_dump() for rule in payload.choice_rules] or _clean_choice_rules(
        [],
        questions,
        payload.max_questions_to_grade,
        payload.instructions,
    )
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO exams (
                id, title, subject, total_marks, max_questions_to_grade,
                choice_rules_json, instructions, questions_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exam_id,
                payload.title or "Untitled Exam",
                payload.subject,
                payload.total_marks,
                payload.max_questions_to_grade,
                json.dumps(choice_rules),
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
        choice_rules=choice_rules,
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
    schema_files: list[UploadFile] | None = File(None),
    question_files: list[UploadFile] | None = File(None),
    file: UploadFile | None = File(None),
    _: AuthUser = Depends(require_teacher),
) -> ExamOut:
    try:
        ensure_openai_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if default_marks is not None and default_marks <= 0:
        raise HTTPException(status_code=422, detail="Marks must be greater than zero.")
    fallback_marks = float(default_marks or 10)

    uploads = list(schema_files or [])
    if file:
        uploads.append(file)
    if not uploads:
        raise HTTPException(status_code=400, detail="Upload at least one answer scheme file.")
    _validate_ai_uploads(uploads, "answer scheme")
    _validate_ai_uploads(list(question_files or []), "question paper")

    schema_root = settings.upload_dir / "_schemas" / uuid.uuid4().hex[:12]
    schema_paths = _save_uploads(schema_root / "answer-scheme", uploads, "answer-scheme")
    question_paths = _save_uploads(schema_root / "question-paper", list(question_files or []), "question-paper")

    try:
        extracted = extract_schema_with_openai(
            schema_paths=schema_paths,
            question_paper_paths=question_paths,
            subject=subject.strip() or "General",
            title=title.strip() or "Answer Schema",
            default_marks=fallback_marks,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    schema_verifier_warning = ""
    try:
        extracted = verify_schema_with_openai(
            schema_paths=schema_paths,
            question_paper_paths=question_paths,
            draft_schema=extracted,
            subject=subject.strip() or "General",
            title=title.strip() or "Answer Schema",
            default_marks=fallback_marks,
        )
    except RuntimeError:
        schema_verifier_warning = (
            "Review note: schema verifier could not complete, so this exam was saved "
            "from the first extraction pass. Please confirm the extracted question rules "
            "before checking submissions."
        )

    questions: list[dict[str, Any]] = []
    for index, question in enumerate(extracted.get("questions", []), start=1):
        text = str(question.get("text", "")).strip()
        model_answer = str(question.get("model_answer", "")).strip()
        if not text:
            continue
        raw_parts = question.get("parts", [])
        raw_parts_payload = raw_parts if isinstance(raw_parts, list) else []
        raw_part_marks = [
            mark
            for mark in (
                _as_positive_float(part.get("max_marks"))
                for part in raw_parts_payload
                if isinstance(part, dict)
            )
            if mark
        ]
        max_marks = _as_positive_float(question.get("max_marks")) or sum(raw_part_marks) or fallback_marks
        question_id = str(question.get("id") or f"Q{index}").strip() or f"Q{index}"
        parts = _clean_question_parts(
            parent_id=question_id,
            raw_parts=raw_parts_payload,
            parent_max_marks=max_marks,
            fallback_marks=fallback_marks,
        )
        part_total = sum(float(part["max_marks"]) for part in parts)
        if parts and (not _as_positive_float(question.get("max_marks")) or part_total > max_marks):
            max_marks = part_total
        if not model_answer and parts:
            model_answer = "Grade using the extracted subpart model answers and marking rules."
        if not model_answer:
            continue
        questions.append(
            {
                "id": question_id,
                "text": text,
                "max_marks": max(0.5, float(max_marks)),
                "model_answer": model_answer,
                "marking_rules": str(question.get("marking_rules", "")).strip(),
                "keywords": [
                    str(keyword).strip()
                    for keyword in question.get("keywords", [])
                    if str(keyword).strip()
                ],
                "parts": parts,
            }
        )

    if not questions:
        raise HTTPException(
            status_code=400,
            detail="Could not find a question and answer schema in the uploaded files.",
        )

    extracted_total_marks = _as_positive_float(extracted.get("total_marks"))
    extracted_choice_limit = _as_positive_int(extracted.get("max_questions_to_grade"))
    choice_rule = str(extracted.get("choice_rule", "")).strip()
    extracted_instructions = str(extracted.get("instructions") or "").strip()
    raw_choice_rules = extracted.get("choice_rules", [])
    has_structured_choice_rules = _raw_choice_rules_have_structured_choice(raw_choice_rules)
    choice_text = " ".join(
        [
            choice_rule,
            extracted_instructions,
            str(extracted.get("title") or title or ""),
            " ".join(question["text"] for question in questions),
        ]
    )
    if not extracted_choice_limit and not has_structured_choice_rules:
        extracted_choice_limit = _infer_choice_limit(choice_text, len(questions))
    questions, total_marks, max_questions_to_grade = _normalize_schema_questions(
        questions=questions,
        total_marks=extracted_total_marks,
        max_questions_to_grade=extracted_choice_limit,
        default_marks=fallback_marks,
        infer_choice_from_total=not has_structured_choice_rules,
    )
    choice_rules = _clean_choice_rules(
        raw_choice_rules,
        questions,
        max_questions_to_grade,
        choice_rule,
    )
    simple_best_rule = _simple_best_n_rule(choice_rules, questions)
    if choice_rules:
        if simple_best_rule:
            max_questions_to_grade = _as_positive_int(simple_best_rule.get("count")) or max_questions_to_grade
        else:
            max_questions_to_grade = None
        if not total_marks:
            total_marks = _choice_rules_total_capacity(questions, choice_rules)
    instructions = "\n".join(
        part for part in [extracted_instructions, choice_rule, schema_verifier_warning] if part
    ).strip()
    if max_questions_to_grade and (not choice_rules or simple_best_rule):
        instructions = _remove_conflicting_all_question_claims(instructions)
        normalized_rule = f"Grading rule: best {max_questions_to_grade} of {len(questions)} questions count."
        if normalized_rule.lower() not in instructions.lower():
            instructions = "\n".join(part for part in [instructions, normalized_rule] if part).strip()

    payload = ExamCreate(
        title=str(extracted.get("title") or title or "Answer Schema").strip(),
        subject=str(extracted.get("subject") or subject or "General").strip(),
        instructions=instructions,
        total_marks=total_marks,
        max_questions_to_grade=max_questions_to_grade,
        choice_rules=choice_rules,
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
    attempt_hints: str = Form(""),
    files: list[UploadFile] = File(...),
    _: AuthUser = Depends(require_teacher),
) -> SubmissionCreated:
    exam = _get_exam_or_404(exam_id)
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one answer sheet file.")
    _validate_ai_uploads(files, "answer sheet")
    if not student_name.strip():
        raise HTTPException(status_code=422, detail="Student name is required.")
    normalized_usn = normalize_usn(usn)
    parsed_attempt_hints = _parse_attempt_hints(
        attempt_hints,
        valid_question_ids=_question_hint_ids(exam["questions"]),
    )

    created_at = now_iso()
    submission_id = new_id("sub")
    upload_root = settings.upload_dir / submission_id
    upload_root.mkdir(parents=True, exist_ok=True)

    saved_files: list[tuple[str, str, str, str, int]] = []
    for index, upload in enumerate(files, start=1):
        original = _ai_storage_filename(upload, f"sheet-{index}")
        stored_name = f"{index:02d}_{uuid.uuid4().hex[:8]}_{original}"
        stored_path = upload_root / stored_name
        with stored_path.open("wb") as file_handle:
            shutil.copyfileobj(upload.file, file_handle)
        size_bytes = stored_path.stat().st_size
        if size_bytes <= 0:
            raise HTTPException(status_code=400, detail="Uploaded answer sheet file is empty.")
        saved_files.append(
            (
                new_id("file"),
                original,
                str(stored_path),
                upload.content_type or "application/octet-stream",
                size_bytes,
            )
        )

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO submissions
            (id, exam_id, student_name, usn, status, total_marks, attempt_hints_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'uploaded', ?, ?, ?, ?)
            """,
            (
                submission_id,
                exam_id,
                student_name.strip(),
                normalized_usn,
                0,
                json.dumps(parsed_attempt_hints),
                created_at,
                created_at,
            ),
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
                "SELECT * FROM evaluations WHERE submission_id = ? ORDER BY rowid",
                (submission_id,),
            ).fetchall()
        )

    return SubmissionOut(
        **{
            **submission,
            "weak_areas": json_loads(submission["weak_areas_json"], []),
            "attempt_hints": json_loads(submission.get("attempt_hints_json", "[]"), []),
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
                    e.choice_rules_json,
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
                    "choice_rules": json_loads(row.get("choice_rules_json", "[]"), []),
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
    if not math.isfinite(value):
        return min_value
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
    return number if math.isfinite(number) and number > 0 else None


def _as_positive_int(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _as_float(value: Any, fallback: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _save_uploads(root: Path, uploads: list[UploadFile], fallback_prefix: str) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for index, upload in enumerate(uploads, start=1):
        original = _ai_storage_filename(upload, f"{fallback_prefix}-{index}")
        stored_path = root / f"{index:02d}_{uuid.uuid4().hex[:8]}_{original}"
        with stored_path.open("wb") as file_handle:
            shutil.copyfileobj(upload.file, file_handle)
        if stored_path.stat().st_size <= 0:
            raise HTTPException(status_code=400, detail=f"Uploaded {fallback_prefix} file is empty.")
        saved.append(stored_path)
    return saved


def _upload_content_type(upload: UploadFile, filename: str) -> str:
    guessed_type, _ = mimetypes.guess_type(filename)
    return (upload.content_type or guessed_type or "").split(";", 1)[0].strip().lower()


def _ai_storage_filename(upload: UploadFile, fallback_name: str) -> str:
    original = clean_filename(upload.filename or fallback_name) or fallback_name
    extension = Path(original).suffix.lower()
    content_type = _upload_content_type(upload, original)
    if extension in SUPPORTED_UPLOAD_EXTENSIONS:
        return original
    fallback_extension = UPLOAD_EXTENSION_BY_MIME_TYPE.get(content_type)
    if fallback_extension:
        stem = Path(original).stem or fallback_name
        return clean_filename(f"{stem}{fallback_extension}")
    return original


def _validate_ai_uploads(uploads: list[UploadFile], label: str) -> None:
    for upload in uploads:
        original = clean_filename(upload.filename or "")
        extension = Path(original).suffix.lower()
        content_type = _upload_content_type(upload, original)
        supported_extension = extension in SUPPORTED_UPLOAD_EXTENSIONS
        supported_mime = content_type in SUPPORTED_UPLOAD_MIME_TYPES
        if not supported_extension and not supported_mime:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported {label} file '{original or 'upload'}'. "
                    "Upload PDF, PNG, JPG, JPEG, or WEBP files."
                ),
            )


EXPLICIT_QUESTION_REF_RE = re.compile(
    r"\b(?:q(?:uestion)?|ans(?:wer)?)\.?\s*(?:no\.?)?\s*[:#-]?\s*"
    r"(\d{1,3})(?:\s*(?:[\.\-]|\()\s*([a-zA-Z]{1,3}|[ivxIVX]{1,6})\s*\)?)?",
    re.IGNORECASE,
)
COMPACT_QUESTION_REF_RE = re.compile(
    r"^(?:q\.?)?(\d{1,3})(?:[\.\-\(]?([a-zA-Z]{1,3}|[ivxIVX]{1,6})\)?)?$",
    re.IGNORECASE,
)


def _question_hint_ids(questions: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for question in questions:
        question_id = str(question.get("id") or "").strip()
        if question_id:
            ids.append(question_id)
        for part in question.get("parts") or []:
            if isinstance(part, dict):
                part_id = str(part.get("id") or "").strip()
                if part_id:
                    ids.append(part_id)
    return ids


def _parse_attempt_hints(value: str, valid_question_ids: list[str] | None = None) -> list[str]:
    if not value.strip():
        return []
    hints: list[str] = []
    seen: set[str] = set()

    valid_lookup: dict[str, str] = {}
    for question_id in valid_question_ids or []:
        cleaned_id = str(question_id).strip()
        if not cleaned_id:
            continue
        canonical = _canonical_question_key(cleaned_id)
        valid_lookup[cleaned_id.upper()] = cleaned_id
        if canonical:
            valid_lookup[canonical] = cleaned_id

    def add_hint(raw_hint: str) -> bool:
        canonical = _canonical_question_key(raw_hint)
        if not canonical or not re.search(r"\d", canonical):
            return False
        normalized = canonical
        if valid_lookup:
            normalized = valid_lookup.get(raw_hint.strip().upper()) or valid_lookup.get(canonical) or ""
            if not normalized:
                return False
        dedupe_key = _canonical_question_key(normalized) or normalized.upper()
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            hints.append(normalized)
        return True

    def add_part_continuation(question_number: str, part_token: str) -> bool:
        cleaned_part = part_token.strip().strip("().,:;")
        if not cleaned_part:
            return False
        if add_hint(f"Q{question_number}.{cleaned_part}"):
            return True
        is_compact_letter_group = (
            bool(valid_lookup)
            and cleaned_part.isalpha()
            and len(cleaned_part) > 1
            and not re.fullmatch(r"[ivxIVX]+", cleaned_part)
        )
        if is_compact_letter_group:
            added = False
            for label in cleaned_part:
                added = add_hint(f"Q{question_number}.{label}") or added
            return added
        return False

    def process_free_text(text: str, current_question_number: str | None) -> str | None:
        last_question_number = current_question_number
        for token in re.split(r"[,;\n/|]+|\s+|\band\b|\bor\b", text, flags=re.IGNORECASE):
            cleaned = token.strip().strip("().,:;")
            if not cleaned:
                continue
            match = COMPACT_QUESTION_REF_RE.fullmatch(cleaned)
            if match:
                number, part = match.groups()
                if add_hint(f"Q{number}{'.' + part if part else ''}"):
                    last_question_number = number
                continue
            if last_question_number and re.fullmatch(r"[a-zA-Z]{1,6}|[ivxIVX]{1,6}", cleaned):
                add_part_continuation(last_question_number, cleaned)
        return last_question_number

    last_question_number: str | None = None
    position = 0
    for match in EXPLICIT_QUESTION_REF_RE.finditer(value):
        last_question_number = process_free_text(value[position:match.start()], last_question_number)
        number, part = match.groups()
        if add_hint(f"Q{number}{'.' + part if part else ''}"):
            last_question_number = number
        position = match.end()
    process_free_text(value[position:], last_question_number)
    return hints[:40]


def _canonical_question_key(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip()).upper()
    text = (
        text.replace("QUESTIONNO", "Q")
        .replace("QUESTION", "Q")
        .replace("QNO", "Q")
        .replace("ANSWER", "")
        .replace("ANS", "")
    )
    text = re.sub(r"^Q[\.\-:]+", "Q", text)
    text = text.strip(":.")
    if not text:
        return ""
    match = re.fullmatch(r"Q?(\d+)$", text)
    if match:
        return f"Q{match.group(1)}"
    match = re.fullmatch(r"Q?(\d+)[\.\-\(]?([A-Z]+|[IVX]+)\)?", text)
    if match:
        return f"Q{match.group(1)}.{match.group(2).lower()}"
    return text


def _question_id_lookup(questions: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for question in questions:
        question_id = str(question["id"])
        lookup[question_id] = question_id
        canonical = _canonical_question_key(question_id)
        if canonical:
            lookup[canonical] = question_id
    return lookup


def _part_parent_lookup(
    questions: list[dict[str, Any]],
) -> dict[str, tuple[str, dict[str, Any]]]:
    lookup: dict[str, tuple[str, dict[str, Any]]] = {}
    for question in questions:
        parent_id = str(question["id"])
        for part in question.get("parts") or []:
            part_id = str(part.get("id") or "")
            if not part_id:
                continue
            lookup[part_id] = (parent_id, part)
            canonical = _canonical_question_key(part_id)
            if canonical:
                lookup[canonical] = (parent_id, part)
            label = str(part.get("label") or "")
            if label:
                lookup[_canonical_question_key(f"{parent_id}.{label}")] = (parent_id, part)
    return {key: value for key, value in lookup.items() if key}


def _question_scope_from_hints(
    questions: list[dict[str, Any]],
    attempt_hints: list[str],
) -> CheckingScope:
    question_lookup = _question_id_lookup(questions)
    part_lookup = _part_parent_lookup(questions)
    scoped_ids: list[str] = []
    parent_ids: set[str] = set()
    whole_parent_ids: set[str] = set()
    part_ids_by_parent: dict[str, set[str]] = {}
    for hint in attempt_hints:
        hint_text = str(hint or "").strip()
        if not hint_text:
            continue
        canonical = _canonical_question_key(hint_text)
        parent_id = question_lookup.get(hint_text) or question_lookup.get(canonical)
        if parent_id:
            parent_ids.add(parent_id)
            whole_parent_ids.add(parent_id)
            if parent_id not in scoped_ids:
                scoped_ids.append(parent_id)
            continue
        part_entry = part_lookup.get(hint_text) or part_lookup.get(canonical)
        if part_entry:
            part_parent_id, part = part_entry
            part_id = str(part.get("id") or "").strip()
            if not part_id:
                continue
            parent_ids.add(part_parent_id)
            part_ids_by_parent.setdefault(part_parent_id, set()).add(part_id)
            if part_id not in scoped_ids:
                scoped_ids.append(part_id)
    return CheckingScope(
        ids=tuple(scoped_ids),
        parent_ids=frozenset(parent_ids),
        whole_parent_ids=frozenset(whole_parent_ids),
        part_ids_by_parent={
            parent_id: frozenset(part_ids)
            for parent_id, part_ids in part_ids_by_parent.items()
        },
        limited=bool(scoped_ids),
    )


def _scope_allows_parent(scope: CheckingScope, parent_id: str) -> bool:
    return not scope.active or parent_id in scope.parent_ids


def _scope_allows_part(scope: CheckingScope, parent_id: str, part_id: str) -> bool:
    if not scope.active:
        return True
    if parent_id in scope.whole_parent_ids:
        return True
    return part_id in scope.part_ids_by_parent.get(parent_id, frozenset())


def _scope_requires_part_level(scope: CheckingScope, parent_id: str) -> bool:
    return (
        scope.active
        and parent_id not in scope.whole_parent_ids
        and bool(scope.part_ids_by_parent.get(parent_id))
    )


def _scope_max_marks_for_question(question: dict[str, Any], scope: CheckingScope) -> float:
    parent_id = str(question["id"])
    if not _scope_requires_part_level(scope, parent_id):
        return float(question["max_marks"])
    allowed_part_ids = scope.part_ids_by_parent.get(parent_id, frozenset())
    scoped_total = sum(
        float(part.get("max_marks") or 0)
        for part in question.get("parts") or []
        if str(part.get("id") or "") in allowed_part_ids
    )
    return scoped_total if scoped_total > 0 else float(question["max_marks"])


def _empty_checking_scope() -> CheckingScope:
    return CheckingScope((), frozenset(), frozenset(), {})


def _empty_limited_checking_scope() -> CheckingScope:
    return CheckingScope((), frozenset(), frozenset(), {}, limited=True)


def _checking_scope_intersection(
    first: CheckingScope,
    second: CheckingScope,
    questions: list[dict[str, Any]],
) -> CheckingScope:
    if not first.active:
        return second
    if not second.active:
        return first

    scoped_ids: list[str] = []
    parent_ids: set[str] = set()
    whole_parent_ids: set[str] = set()
    part_ids_by_parent: dict[str, set[str]] = {}

    def add_parent(parent_id: str) -> None:
        parent_ids.add(parent_id)
        whole_parent_ids.add(parent_id)
        if parent_id not in scoped_ids:
            scoped_ids.append(parent_id)

    def add_part(parent_id: str, part_id: str) -> None:
        parent_ids.add(parent_id)
        part_ids_by_parent.setdefault(parent_id, set()).add(part_id)
        if part_id not in scoped_ids:
            scoped_ids.append(part_id)

    for question in questions:
        parent_id = str(question["id"])
        if not _scope_allows_parent(first, parent_id) or not _scope_allows_parent(second, parent_id):
            continue
        first_whole = parent_id in first.whole_parent_ids
        second_whole = parent_id in second.whole_parent_ids
        parts = [str(part.get("id") or "") for part in question.get("parts") or []]
        parts = [part_id for part_id in parts if part_id]

        if first_whole and second_whole:
            add_parent(parent_id)
        elif first_whole:
            for part_id in second.part_ids_by_parent.get(parent_id, frozenset()):
                add_part(parent_id, part_id)
            if not second.part_ids_by_parent.get(parent_id) and not parts:
                add_parent(parent_id)
        elif second_whole:
            for part_id in first.part_ids_by_parent.get(parent_id, frozenset()):
                add_part(parent_id, part_id)
            if not first.part_ids_by_parent.get(parent_id) and not parts:
                add_parent(parent_id)
        else:
            shared_parts = first.part_ids_by_parent.get(parent_id, frozenset()).intersection(
                second.part_ids_by_parent.get(parent_id, frozenset())
            )
            for part_id in shared_parts:
                add_part(parent_id, part_id)

    return CheckingScope(
        ids=tuple(scoped_ids),
        parent_ids=frozenset(parent_ids),
        whole_parent_ids=frozenset(whole_parent_ids),
        part_ids_by_parent={
            parent_id: frozenset(part_ids)
            for parent_id, part_ids in part_ids_by_parent.items()
        },
        limited=True,
    )


def _detected_question_ids(result: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for key in ("attempted_question_ids", "uncertain_question_ids"):
        raw_ids = result.get(key, [])
        if not isinstance(raw_ids, list):
            continue
        for raw_id in raw_ids:
            question_id = str(raw_id or "").strip()
            if not question_id:
                continue
            dedupe_key = _canonical_question_key(question_id) or question_id.upper()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            ids.append(question_id)
    return ids


def _clean_choice_rules(
    raw_rules: Any,
    questions: list[dict[str, Any]],
    max_questions_to_grade: int | None,
    choice_rule_text: str,
) -> list[dict[str, Any]]:
    question_lookup = _question_id_lookup(questions)
    all_question_ids = [str(question["id"]) for question in questions]
    rules: list[dict[str, Any]] = []
    if isinstance(raw_rules, list):
        for raw_rule in raw_rules:
            if not isinstance(raw_rule, dict):
                continue
            rule_type = str(raw_rule.get("type") or "").strip().lower().replace("-", "_")
            if rule_type in {"answer_any", "section_answer_any", "section_best_n"}:
                rule_type = "best_n"
            if rule_type in {"required", "must_answer", "all"}:
                rule_type = "compulsory"
            if rule_type not in {"best_n", "compulsory"}:
                continue
            count = _as_positive_int(raw_rule.get("count"))
            question_ids: list[str] = []
            for raw_id in raw_rule.get("question_ids", []):
                resolved = question_lookup.get(str(raw_id).strip()) or question_lookup.get(_canonical_question_key(raw_id))
                if resolved and resolved not in question_ids:
                    question_ids.append(resolved)
            if not question_ids:
                question_ids = all_question_ids
            if rule_type == "best_n" and (not count or count >= len(question_ids)):
                rule_type = "compulsory"
                count = None
            if rule_type == "best_n" and count:
                rules.append(
                    {
                        "type": "best_n",
                        "count": count,
                        "question_ids": question_ids,
                        "description": str(raw_rule.get("description") or choice_rule_text).strip(),
                    }
                )
            elif rule_type == "compulsory":
                rules.append(
                    {
                        "type": "compulsory",
                        "count": None,
                        "question_ids": question_ids,
                        "description": str(raw_rule.get("description") or "Compulsory questions").strip(),
                    }
                )
    if (
        rules
        and max_questions_to_grade
        and max_questions_to_grade < len(all_question_ids)
        and len(rules) == 1
        and rules[0]["type"] == "compulsory"
        and set(rules[0]["question_ids"]) == set(all_question_ids)
    ):
        rules = []
    if not rules and max_questions_to_grade and max_questions_to_grade < len(all_question_ids):
        rules.append(
            {
                "type": "best_n",
                "count": max_questions_to_grade,
                "question_ids": all_question_ids,
                "description": choice_rule_text or f"Best {max_questions_to_grade} of {len(all_question_ids)} questions.",
            }
        )
    return rules


def _raw_choice_rules_have_structured_choice(raw_rules: Any) -> bool:
    if not isinstance(raw_rules, list):
        return False
    usable_rules = [
        rule
        for rule in raw_rules
        if isinstance(rule, dict) and str(rule.get("type") or "").strip()
    ]
    if len(usable_rules) > 1:
        return True
    if not usable_rules:
        return False
    rule_type = str(usable_rules[0].get("type") or "").strip().lower().replace("-", "_")
    return rule_type in {"answer_any", "best_n", "section_answer_any", "section_best_n"}


def _simple_best_n_rule(
    choice_rules: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(choice_rules) != 1:
        return None
    rule = choice_rules[0]
    all_question_ids = {str(question["id"]) for question in questions}
    rule_question_ids = {str(question_id) for question_id in rule.get("question_ids", [])}
    if (
        rule.get("type") == "best_n"
        and _as_positive_int(rule.get("count"))
        and rule_question_ids == all_question_ids
    ):
        return rule
    return None


def _choice_rules_total_capacity(
    questions: list[dict[str, Any]],
    choice_rules: list[dict[str, Any]],
) -> float | None:
    question_marks = {str(question["id"]): _as_float(question.get("max_marks")) for question in questions}
    selected_capacity: set[str] = set()
    for rule in choice_rules:
        if not isinstance(rule, dict):
            continue
        question_ids = [
            str(question_id)
            for question_id in rule.get("question_ids", [])
            if str(question_id) in question_marks
        ]
        if not question_ids:
            continue
        if rule.get("type") == "best_n":
            count = _as_positive_int(rule.get("count"))
            if not count:
                continue
            capacity_ids = sorted(
                question_ids,
                key=lambda question_id: question_marks[question_id],
                reverse=True,
            )[:count]
            selected_capacity.update(capacity_ids)
        elif rule.get("type") == "compulsory":
            selected_capacity.update(question_ids)
    if not selected_capacity:
        return None
    return sum(question_marks[question_id] for question_id in selected_capacity)


def _clean_question_parts(
    *,
    parent_id: str,
    raw_parts: list[Any],
    parent_max_marks: float,
    fallback_marks: float,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    usable_parts: list[dict[str, Any]] = []
    for index, raw_part in enumerate(raw_parts, start=1):
        if not isinstance(raw_part, dict):
            continue
        text = str(raw_part.get("text", "")).strip()
        model_answer = str(raw_part.get("model_answer", "")).strip()
        if not text and not model_answer:
            continue
        label = str(raw_part.get("label") or "").strip()
        part_id = str(raw_part.get("id") or "").strip()
        if not label and "." in part_id:
            label = part_id.rsplit(".", 1)[-1]
        if not label:
            label = chr(96 + index) if index <= 26 else str(index)
        if not part_id:
            part_id = f"{parent_id}.{label}"
        usable_parts.append(
            {
                "id": part_id,
                "label": label,
                "text": text or f"Part {label}",
                "max_marks": _as_positive_float(raw_part.get("max_marks")),
                "model_answer": model_answer,
                "marking_rules": str(raw_part.get("marking_rules", "")).strip(),
                "keywords": [
                    str(keyword).strip()
                    for keyword in raw_part.get("keywords", [])
                    if str(keyword).strip()
                ],
            }
        )
    if not usable_parts:
        return []
    default_part_marks = parent_max_marks / len(usable_parts) if parent_max_marks > 0 else fallback_marks
    for part in usable_parts:
        parts.append({**part, "max_marks": float(part["max_marks"] or default_part_marks or fallback_marks)})
    return parts


def _missing_answer_text(answer_text: str) -> bool:
    normalized = answer_text.strip().lower()
    if not normalized:
        return True
    missing_markers = [
        "no distinct answer",
        "no separate answer",
        "no answer",
        "not found",
        "not present",
        "not attempted",
        "not visible",
        "did not attempt",
        "left blank",
        "nothing written",
        "no response",
        "no student answer",
        "no visible answer",
        "no visible response",
        "no explicit response",
        "no extracted answer",
        "not answered",
        "unattempted",
        "blank answer",
    ]
    return any(marker in normalized for marker in missing_markers)


def _remove_conflicting_all_question_claims(instructions: str) -> str:
    conflicting_phrases = [
        "answer all questions",
        "all listed questions",
        "all questions are to be answered",
        "all questions to be answered",
    ]
    lines = []
    for line in instructions.splitlines():
        lowered = line.lower()
        if any(phrase in lowered for phrase in conflicting_phrases):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


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
    marks = [float(question["max_marks"]) for question in questions]
    running = 0.0
    for index, mark in enumerate(sorted(marks, reverse=True), start=1):
        running += mark
        if abs(running - total_marks) < 0.01:
            return index if index < len(marks) else None
    dominant = _dominant_mark(marks)
    if not dominant:
        return None
    dominant_mark, dominant_count = dominant
    inferred = total_marks / dominant_mark
    rounded = round(inferred)
    if (
        dominant_mark > 0
        and dominant_count / len(marks) >= 0.7
        and abs(inferred - rounded) < 0.01
        and 0 < rounded < len(marks)
    ):
        return rounded
    return None


def _dominant_mark(marks: list[float]) -> tuple[float, int] | None:
    if not marks:
        return None
    groups: dict[float, int] = {}
    for mark in marks:
        key = round(float(mark), 2)
        groups[key] = groups.get(key, 0) + 1
    mark, count = max(groups.items(), key=lambda item: item[1])
    return mark, count


def _normalize_schema_questions(
    *,
    questions: list[dict[str, Any]],
    total_marks: float | None,
    max_questions_to_grade: int | None,
    default_marks: float,
    infer_choice_from_total: bool = True,
) -> tuple[list[dict[str, Any]], float | None, int | None]:
    if max_questions_to_grade and max_questions_to_grade > len(questions):
        max_questions_to_grade = None
    marks = [float(question["max_marks"]) for question in questions]
    if (
        max_questions_to_grade
        and max_questions_to_grade >= len(questions)
        and (not total_marks or sum(marks) <= total_marks + 0.01)
    ):
        max_questions_to_grade = None
    inferred_choice_limit = _infer_choice_limit_from_total(questions, total_marks) if infer_choice_from_total else None
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
                near_expected = abs(mark - expected_per_question) / expected_per_question <= 0.25
                high_outlier = mark > expected_per_question and near_expected
                fallback_outlier = abs(mark - default_marks) < 0.01 and default_marks > expected_per_question * 1.5
                if high_outlier or fallback_outlier:
                    question["max_marks"] = expected_per_question

    if not total_marks and (infer_choice_from_total or max_questions_to_grade):
        marks = sorted((float(question["max_marks"]) for question in questions), reverse=True)
        total_marks = (
            sum(marks[:max_questions_to_grade])
            if max_questions_to_grade
            else sum(marks)
        )

    for question in questions:
        parts = question.get("parts") or []
        if not parts:
            continue
        part_total = sum(float(part.get("max_marks") or 0) for part in parts)
        parent_marks = float(question["max_marks"])
        if part_total > 0 and parent_marks > 0 and abs(part_total - parent_marks) > 0.01:
            scale = parent_marks / part_total
            for part in parts:
                part["max_marks"] = max(0.5, round(float(part.get("max_marks") or 0) * scale, 2))

    return questions, total_marks, max_questions_to_grade


def _recalculate_submission(conn: Any, submission_id: str) -> None:
    exam = row_to_dict(
        conn.execute(
            """
            SELECT e.total_marks, e.max_questions_to_grade, e.choice_rules_json
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
            SELECT id, question_id, answer_text, attempted, final_score, max_marks, confidence, reason
            FROM evaluations
            WHERE submission_id = ?
            """,
            (submission_id,),
        ).fetchall()
    )
    selected_ids: set[str]
    choice_rules = json_loads((exam or {}).get("choice_rules_json", "[]"), []) if exam else []
    selected_ids = set()
    confidence_rows: list[dict[str, Any]]
    total_score = 0.0
    computed_total_marks = 0.0

    def row_attempted(row: dict[str, Any]) -> bool:
        return (
            bool(row.get("attempted"))
            and (
                not _missing_answer_text(str(row.get("answer_text") or ""))
                or _as_float(row["final_score"]) > 0
            )
        )

    def row_in_checking_scope(row: dict[str, Any]) -> bool:
        return not str(row.get("reason") or "").startswith("Skipped because")

    has_limited_scope = any(not row_in_checking_scope(row) for row in rows)

    if choice_rules:
        rows_by_question = {
            str(row["question_id"]): row
            for row in rows
            if row_in_checking_scope(row)
        }
        all_rule_candidates: list[dict[str, Any]] = []
        total_capacity_ids: set[str] = set()
        for rule in choice_rules:
            if not isinstance(rule, dict):
                continue
            question_ids = [
                str(question_id)
                for question_id in rule.get("question_ids", [])
                if str(question_id) in rows_by_question
            ] or list(rows_by_question.keys())
            rule_rows = [rows_by_question[question_id] for question_id in question_ids]
            rule_type = str(rule.get("type") or "").lower()
            count = _as_positive_int(rule.get("count"))
            if rule_type == "best_n" and count:
                candidates = [
                    row
                    for row in rule_rows
                    if row_attempted(row)
                ]
                all_rule_candidates.extend(candidates)
                selected = sorted(
                    candidates,
                    key=lambda row: (_as_float(row["final_score"]), _as_float(row["confidence"])),
                    reverse=True,
                )[:count]
                selected_ids.update(row["id"] for row in selected)
                capacity_rows = sorted(
                    rule_rows,
                    key=lambda row: _as_float(row["max_marks"]),
                    reverse=True,
                )[:count]
                total_capacity_ids.update(row["id"] for row in capacity_rows)
            elif rule_type == "compulsory":
                selected_ids.update(row["id"] for row in rule_rows)
                total_capacity_ids.update(row["id"] for row in rule_rows)
                all_rule_candidates.extend(rule_rows)
        selected_rows = [row for row in rows if row["id"] in selected_ids]
        total_score = sum(_as_float(row["final_score"]) for row in selected_rows)
        computed_total_marks = sum(_as_float(row["max_marks"]) for row in rows if row["id"] in total_capacity_ids)
        exam_total = _as_float(exam["total_marks"]) if exam else 0
        total_marks = computed_total_marks if has_limited_scope else exam_total if exam_total > 0 else computed_total_marks
        total_score = _clamp(total_score, 0, total_marks) if total_marks else total_score
        confidence_rows = selected_rows or all_rule_candidates or rows
    elif exam and exam.get("max_questions_to_grade"):
        max_questions = exam.get("max_questions_to_grade")
        candidates = [
            row
            for row in rows
            if row_in_checking_scope(row) and row_attempted(row)
        ]
        selected = sorted(
            candidates,
            key=lambda row: (_as_float(row["final_score"]), _as_float(row["confidence"])),
            reverse=True,
        )[: int(max_questions)]
        selected_ids = {row["id"] for row in selected}
        total_score = sum(_as_float(row["final_score"]) for row in selected)
        scoped_capacity = sum(
            _as_float(row["max_marks"])
            for row in sorted(
                [row for row in rows if row_in_checking_scope(row)],
                key=lambda row: _as_float(row["max_marks"]),
                reverse=True,
            )[: int(max_questions)]
        )
        exam_total = _as_float(exam["total_marks"]) if exam else 0
        total_marks = scoped_capacity if has_limited_scope else exam_total or sum(_as_float(row["max_marks"]) for row in selected)
        total_score = _clamp(total_score, 0, total_marks)
        confidence_rows = selected or candidates or rows
    else:
        selected_ids = {row["id"] for row in rows if row_in_checking_scope(row)}
        selected_rows = [row for row in rows if row["id"] in selected_ids]
        total_score = sum(_as_float(row["final_score"]) for row in selected_rows)
        total_marks = sum(_as_float(row["max_marks"]) for row in selected_rows)
        confidence_rows = selected_rows
    avg_confidence = (
        sum(_as_float(row["confidence"]) for row in confidence_rows) / len(confidence_rows)
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


def _evaluation_item_attempted(item: dict[str, Any]) -> bool:
    if "attempted" in item and not bool(item.get("attempted")):
        return False
    answer_text = str(item.get("answer_text", ""))
    return not _missing_answer_text(answer_text)


def _merge_part_level_evaluations(
    *,
    result: dict[str, Any],
    questions: list[dict[str, Any]],
    scope: CheckingScope | None = None,
) -> dict[str, dict[str, Any]]:
    scope = scope or _empty_checking_scope()
    question_lookup = _question_id_lookup(questions)
    part_lookup = _part_parent_lookup(questions)
    top_level_items: dict[str, dict[str, Any]] = {}
    part_groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}

    for raw_item in result.get("questions", []):
        if not isinstance(raw_item, dict):
            continue
        raw_question_id = str(raw_item.get("question_id", "")).strip()
        canonical_id = _canonical_question_key(raw_question_id)
        parent_id = question_lookup.get(raw_question_id) or question_lookup.get(canonical_id)
        if parent_id:
            if not _scope_allows_parent(scope, parent_id) or _scope_requires_part_level(scope, parent_id):
                continue
            top_level_items.setdefault(parent_id, raw_item)
            continue
        part_entry = part_lookup.get(raw_question_id) or part_lookup.get(canonical_id)
        if part_entry:
            group_parent_id, part = part_entry
            part_id = str(part.get("id") or "")
            if not _scope_allows_part(scope, group_parent_id, part_id):
                continue
            part_groups.setdefault(group_parent_id, []).append((part, raw_item))

    for parent_id, items in part_groups.items():
        if parent_id in top_level_items and _evaluation_item_attempted(top_level_items[parent_id]):
            continue
        attempted_parts = [
            (part, item)
            for part, item in items
            if _evaluation_item_attempted(item)
        ]
        answer_chunks: list[str] = []
        reason_chunks: list[str] = []
        missing_points: list[str] = []
        confidence_values: list[float] = []
        score = 0.0
        review_required = False
        for part, item in items:
            part_id = str(part.get("id") or parent_id)
            part_marks = float(part.get("max_marks") or 0)
            attempted = _evaluation_item_attempted(item)
            if attempted:
                answer_text = str(item.get("answer_text", "")).strip()
                if answer_text:
                    answer_chunks.append(f"{part_id}: {answer_text}")
                score += _clamp(_as_float(item.get("score")), 0, part_marks)
            reason = str(item.get("reason", "")).strip()
            if reason:
                reason_chunks.append(f"{part_id}: {reason}")
            for point in item.get("missing_points", []):
                point_text = str(point).strip()
                if point_text:
                    missing_points.append(f"{part_id}: {point_text}")
            confidence_values.append(_clamp(_as_float(item.get("confidence")), 0, 100))
            review_required = review_required or bool(item.get("review_required"))
        top_level_items[parent_id] = {
            "question_id": parent_id,
            "answer_text": "\n".join(answer_chunks),
            "attempted": bool(attempted_parts),
            "score": score,
            "max_marks": sum(float(part.get("max_marks") or 0) for part, _ in items),
            "reason": " ".join(reason_chunks)
            or "Subpart-level answers were merged into the parent question.",
            "missing_points": missing_points,
            "confidence": (
                sum(confidence_values) / len(confidence_values)
                if confidence_values
                else 0
            ),
            "review_required": review_required or not attempted_parts,
        }

    return top_level_items


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
                    "SELECT stored_path FROM submission_files WHERE submission_id = ? ORDER BY stored_path",
                    (submission_id,),
                ).fetchall()
            )

        if not exam:
            raise RuntimeError("Exam not found.")
        exam["questions"] = json_loads(exam["questions_json"], [])
        attempt_hints = json_loads(submission.get("attempt_hints_json", "[]"), [])
        teacher_scope = _question_scope_from_hints(exam["questions"], attempt_hints)
        answer_paths = [Path(row["stored_path"]) for row in files]
        detector_warning = ""
        detected_scope = _empty_checking_scope()
        detector_completed = False
        try:
            detection_result = detect_attempted_questions_with_openai(
                exam=exam,
                student_name=submission["student_name"],
                usn=submission["usn"],
                file_paths=answer_paths,
                question_ids_to_check=list(teacher_scope.ids),
            )
            detector_completed = True
            detected_scope = _question_scope_from_hints(
                exam["questions"],
                _detected_question_ids(detection_result),
            )
        except RuntimeError as exc:
            detector_warning = f" Attempt detector could not complete: {exc}"

        if teacher_scope.active and detected_scope.active:
            checking_scope = _checking_scope_intersection(teacher_scope, detected_scope, exam["questions"])
        elif teacher_scope.active and detector_completed:
            checking_scope = _empty_limited_checking_scope()
        elif teacher_scope.active:
            checking_scope = teacher_scope
        elif detected_scope.active:
            checking_scope = detected_scope
        elif detector_completed:
            checking_scope = _empty_limited_checking_scope()
        else:
            checking_scope = _empty_checking_scope()
        question_ids_to_check = list(checking_scope.ids)
        verifier_warning = ""
        if checking_scope.active and not question_ids_to_check:
            result = {
                "student_name": submission["student_name"],
                "usn": submission["usn"],
                "questions": [],
                "summary": {
                    "overall_feedback": "No attempted answers were detected in the verified checking scope.",
                    "weak_areas": [],
                },
            }
        else:
            draft_result = evaluate_submission_with_openai(
                exam=exam,
                student_name=submission["student_name"],
                usn=submission["usn"],
                file_paths=answer_paths,
                attempt_hints=attempt_hints,
                question_ids_to_check=question_ids_to_check,
            )
            try:
                result = verify_evaluation_with_openai(
                    exam=exam,
                    student_name=submission["student_name"],
                    usn=submission["usn"],
                    file_paths=answer_paths,
                    draft_result=draft_result,
                    attempt_hints=attempt_hints,
                    question_ids_to_check=question_ids_to_check,
                )
            except RuntimeError as exc:
                result = draft_result
                verifier_warning = f" Verification agent could not complete: {exc}"

        question_map = {str(question["id"]): question for question in exam["questions"]}
        merged_items = _merge_part_level_evaluations(
            result=result,
            questions=exam["questions"],
            scope=checking_scope,
        )
        created_at = now_iso()
        with get_db() as conn:
            conn.execute("DELETE FROM evaluations WHERE submission_id = ?", (submission_id,))
            for question_id, question in question_map.items():
                item = merged_items.get(question_id)
                scoped_max_marks = _scope_max_marks_for_question(question, checking_scope)
                if not _scope_allows_parent(checking_scope, question_id):
                    max_marks = float(question["max_marks"])
                    if teacher_scope.active and not _scope_allows_parent(teacher_scope, question_id):
                        skipped_reason = "Skipped because the teacher did not include this question in the questions to check."
                    elif detector_completed and (
                        not detected_scope.active
                        or not _scope_allows_parent(detected_scope, question_id)
                    ):
                        skipped_reason = "Skipped because the attempted-question detector did not find a visible answer for this question."
                    else:
                        skipped_reason = "Skipped because this question was outside the verified checking scope."
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
                            0,
                            skipped_reason,
                            json.dumps([]),
                            created_at,
                            created_at,
                        ),
                    )
                    continue
                if not item:
                    max_marks = scoped_max_marks
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
                    continue
                max_marks = scoped_max_marks
                answer_text = str(item.get("answer_text", ""))
                raw_score = _clamp(_as_float(item.get("score")), 0, max_marks)
                attempted = _evaluation_item_attempted({**item, "score": raw_score})
                if not attempted:
                    answer_text = ""
                score = raw_score if attempted else 0
                confidence = _clamp(_as_float(item.get("confidence")), 0, 100)
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
            summary = result.get("summary", {})
            overall_feedback = str(summary.get("overall_feedback", ""))
            if detector_warning:
                overall_feedback = (overall_feedback + detector_warning).strip()
            if verifier_warning:
                overall_feedback = (overall_feedback + verifier_warning).strip()
            conn.execute(
                """
                UPDATE submissions
                SET status = 'completed', error = '', overall_feedback = ?, weak_areas_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    overall_feedback,
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
            final_score = _clamp(_as_float(payload.final_score), 0, _as_float(current["max_marks"]))
        reason = current["reason"] if payload.reason is None else payload.reason
        review_required = (
            current["review_required"]
            if payload.review_required is None
            else (1 if payload.review_required else 0)
        )
        attempted = 1 if not _missing_answer_text(str(current.get("answer_text") or "")) or _as_float(final_score) > 0 else 0

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
    evaluations = reportable_evaluations([item.model_dump() for item in submission.evaluations])
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
