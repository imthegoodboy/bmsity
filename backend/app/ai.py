from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from openai import OpenAI

from .settings import settings


SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
SUPPORTED_FILE_TYPES = {"application/pdf"}


EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["student_name", "usn", "questions", "summary"],
    "properties": {
        "student_name": {"type": "string"},
        "usn": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "question_id",
                    "answer_text",
                    "score",
                    "max_marks",
                    "reason",
                    "missing_points",
                    "confidence",
                    "review_required",
                ],
                "properties": {
                    "question_id": {"type": "string"},
                    "answer_text": {"type": "string"},
                    "score": {"type": "number"},
                    "max_marks": {"type": "number"},
                    "reason": {"type": "string"},
                    "missing_points": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {"type": "number"},
                    "review_required": {"type": "boolean"},
                },
            },
        },
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "required": ["overall_feedback", "weak_areas"],
            "properties": {
                "overall_feedback": {"type": "string"},
                "weak_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
}


def ensure_openai_ready() -> None:
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it to backend/.env and restart the API server."
        )


def _mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _image_content(path: Path, mime_type: str) -> dict[str, str]:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{mime_type};base64,{encoded}",
    }


def _upload_file_content(client: OpenAI, path: Path) -> dict[str, str]:
    with path.open("rb") as file_handle:
        uploaded = client.files.create(file=file_handle, purpose="user_data")
    return {"type": "input_file", "file_id": uploaded.id}


def _extract_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def evaluate_submission_with_openai(
    *,
    exam: dict[str, Any],
    student_name: str,
    usn: str,
    file_paths: list[Path],
) -> dict[str, Any]:
    ensure_openai_ready()
    client = OpenAI(api_key=settings.openai_api_key)

    rubric = {
        "exam_title": exam["title"],
        "subject": exam["subject"],
        "total_marks": exam["total_marks"],
        "instructions": exam.get("instructions", ""),
        "questions": exam["questions"],
    }

    prompt = (
        "Evaluate this student's answer sheet against the teacher rubric. "
        "Return JSON only in the requested schema. Evaluate every question ID exactly once. "
        "Award partial marks based on conceptual correctness, diagram quality, completeness, "
        "required logic, length expectations, and teacher rules. Do not penalize different wording "
        "when the meaning is correct. Use confidence 0-100. Set review_required true when confidence "
        "is below 80, handwriting/pages are unclear, or the answer is ambiguous.\n\n"
        f"Student name: {student_name}\nUSN: {usn}\nRubric JSON:\n{json.dumps(rubric, ensure_ascii=False)}"
    )

    content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
    for path in file_paths:
        mime_type = _mime_type(path)
        if mime_type in SUPPORTED_IMAGE_TYPES:
            content.append(_image_content(path, mime_type))
        elif mime_type in SUPPORTED_FILE_TYPES:
            content.append(_upload_file_content(client, path))
        else:
            raise RuntimeError(f"Unsupported file type for AI evaluation: {path.name}")

    response = client.responses.create(
        model=settings.openai_model,
        input=[
            {
                "role": "system",
                "content": (
                    "You are a strict but fair exam evaluator. Follow the teacher rubric exactly. "
                    "Prefer evidence from the answer sheet over assumptions."
                ),
            },
            {"role": "user", "content": content},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "bmsitai_evaluation",
                "strict": True,
                "schema": EVALUATION_SCHEMA,
            }
        },
    )

    text = _extract_text(response)
    if not text:
        raise RuntimeError("OpenAI returned an empty evaluation response.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI returned invalid JSON for the evaluation.") from exc
