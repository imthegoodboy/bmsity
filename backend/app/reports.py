from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _rule_text(exam: dict[str, Any]) -> str:
    choice_rules = exam.get("choice_rules") or []
    if choice_rules:
        parts: list[str] = []
        for rule in choice_rules:
            if not isinstance(rule, dict):
                continue
            description = str(rule.get("description") or "").strip()
            if description:
                parts.append(description)
            elif rule.get("type") == "best_n" and rule.get("count"):
                parts.append(f"best {rule['count']} of {len(rule.get('question_ids', []))}")
            elif rule.get("type") == "compulsory":
                parts.append(f"{len(rule.get('question_ids', []))} compulsory question(s)")
        if parts:
            return "Rule: " + "; ".join(parts)
    if exam.get("max_questions_to_grade"):
        return f"Rule: grade best {exam['max_questions_to_grade']} attempted question(s)"
    return "Rule: grade all questions"


def _as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return number if math.isfinite(number) else 0


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


def _is_attempted(item: dict[str, Any]) -> bool:
    return (
        bool(item.get("attempted"))
        and (
            not _missing_answer_text(str(item.get("answer_text") or ""))
            or _as_float(item.get("final_score")) > 0
        )
    )


def reportable_evaluations(evaluations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in evaluations if _is_attempted(item)]


def _feedback_text(item: dict[str, Any]) -> str:
    reason = str(item.get("reason") or "").strip()
    missing_points = [
        str(point).strip()
        for point in item.get("missing_points", [])
        if str(point).strip()
    ]
    if missing_points:
        missing = "Missing: " + "; ".join(missing_points)
        return "<br/>".join(escape(part) for part in [reason, missing] if part)
    return escape(reason or "No written feedback was returned for this attempted answer.")


def generate_report(
    *,
    destination: Path,
    exam: dict[str, Any],
    submission: dict[str, Any],
    evaluations: list[dict[str, Any]],
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(destination), pagesize=A4, rightMargin=32, leftMargin=32)

    total = _as_float(submission.get("total_score", 0))
    max_total = _as_float(submission.get("total_marks", 0))
    visible_evaluations = reportable_evaluations(evaluations)

    story: list[Any] = [
        Paragraph("BmsitAi Evaluation Report", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Exam: {exam['title']} ({exam['subject']})", styles["Normal"]),
        Paragraph(_rule_text(exam), styles["Normal"]),
        Paragraph(
            f"Student: {submission['student_name']}  |  USN: {submission.get('usn', '')}",
            styles["Normal"],
        ),
        Paragraph(f"Total: {total:g} / {max_total:g}", styles["Heading2"]),
        Paragraph(f"Attempted answers shown: {len(visible_evaluations)}", styles["Normal"]),
        Spacer(1, 12),
    ]

    if visible_evaluations:
        table_data: list[list[Any]] = [["Q", "Marks", "Confidence", "Status", "Feedback"]]
        for item in visible_evaluations:
            if not item.get("counts_toward_total", True):
                status = "Not counted"
            else:
                status = "Review" if item["review_required"] else "Counted"
            table_data.append(
                [
                    item["question_id"],
                    f"{_as_float(item.get('final_score')):g}/{_as_float(item.get('max_marks')):g}",
                    f"{_as_float(item.get('confidence')):g}%",
                    status,
                    Paragraph(
                        "<br/>".join(
                            part
                            for part in [
                                _feedback_text(item),
                                escape(f"Answer evidence: {str(item.get('answer_text') or '').strip()}")
                                if str(item.get("answer_text") or "").strip()
                                else "",
                            ]
                            if part
                        ),
                        styles["BodyText"],
                    ),
                ]
            )

        table = Table(table_data, colWidths=[42, 58, 76, 62, 300])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bfdbfe")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fbff")]),
                ]
            )
        )
        story.append(table)
    else:
        story.append(
            Paragraph(
                "No attempted answers were detected for this submission.",
                styles["BodyText"],
            )
        )

    if submission.get("overall_feedback"):
        story.extend(
            [
                Spacer(1, 16),
                Paragraph("Overall Feedback", styles["Heading2"]),
                Paragraph(submission["overall_feedback"], styles["BodyText"]),
            ]
        )

    doc.build(story)
    return destination
