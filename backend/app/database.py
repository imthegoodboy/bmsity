from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .settings import settings


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS exams (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                subject TEXT NOT NULL,
                total_marks REAL NOT NULL,
                max_questions_to_grade INTEGER,
                instructions TEXT NOT NULL DEFAULT '',
                questions_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                exam_id TEXT NOT NULL,
                student_name TEXT NOT NULL,
                usn TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                total_score REAL NOT NULL DEFAULT 0,
                total_marks REAL NOT NULL DEFAULT 0,
                average_confidence REAL NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                overall_feedback TEXT NOT NULL DEFAULT '',
                weak_areas_json TEXT NOT NULL DEFAULT '[]',
                attempt_hints_json TEXT NOT NULL DEFAULT '[]',
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS submission_files (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                question_text TEXT NOT NULL,
                answer_text TEXT NOT NULL,
                attempted INTEGER NOT NULL DEFAULT 0,
                counts_toward_total INTEGER NOT NULL DEFAULT 1,
                score REAL NOT NULL,
                max_marks REAL NOT NULL,
                final_score REAL NOT NULL,
                confidence REAL NOT NULL,
                review_required INTEGER NOT NULL,
                reason TEXT NOT NULL,
                missing_points_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(submission_id, question_id),
                FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS student_accounts (
                usn TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL DEFAULT '',
                force_password_change INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_submissions_usn ON submissions(usn);
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(submissions)").fetchall()
        }
        if "published" not in columns:
            conn.execute("ALTER TABLE submissions ADD COLUMN published INTEGER NOT NULL DEFAULT 0")
        if "attempt_hints_json" not in columns:
            conn.execute(
                "ALTER TABLE submissions ADD COLUMN attempt_hints_json TEXT NOT NULL DEFAULT '[]'"
            )
        exam_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(exams)").fetchall()
        }
        if "max_questions_to_grade" not in exam_columns:
            conn.execute("ALTER TABLE exams ADD COLUMN max_questions_to_grade INTEGER")
        evaluation_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(evaluations)").fetchall()
        }
        if "attempted" not in evaluation_columns:
            conn.execute("ALTER TABLE evaluations ADD COLUMN attempted INTEGER NOT NULL DEFAULT 0")
        if "counts_toward_total" not in evaluation_columns:
            conn.execute(
                "ALTER TABLE evaluations ADD COLUMN counts_toward_total INTEGER NOT NULL DEFAULT 1"
            )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def json_loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
