from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


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

    total = sum(float(item["final_score"]) for item in evaluations)
    max_total = sum(float(item["max_marks"]) for item in evaluations)

    story: list[Any] = [
        Paragraph("BmsitAi Evaluation Report", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Exam: {exam['title']} ({exam['subject']})", styles["Normal"]),
        Paragraph(
            f"Student: {submission['student_name']}  |  USN: {submission.get('usn', '')}",
            styles["Normal"],
        ),
        Paragraph(f"Total: {total:g} / {max_total:g}", styles["Heading2"]),
        Spacer(1, 12),
    ]

    table_data: list[list[Any]] = [["Q", "Marks", "Confidence", "Status", "Feedback"]]
    for item in evaluations:
        status = "Review" if item["review_required"] else "OK"
        table_data.append(
            [
                item["question_id"],
                f"{float(item['final_score']):g}/{float(item['max_marks']):g}",
                f"{float(item['confidence']):g}%",
                status,
                Paragraph(item["reason"], styles["BodyText"]),
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
