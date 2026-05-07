from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.database import init_db
from app.settings import settings


def make_client(tmp_path: Path, monkeypatch) -> TestClient:
    settings.database_path = tmp_path / "test.db"
    settings.upload_dir = tmp_path / "uploads"
    settings.report_dir = tmp_path / "reports"
    settings.openai_api_key = "test-key"
    init_db(settings.database_path)
    monkeypatch.setattr(main.settings, "database_path", settings.database_path)
    monkeypatch.setattr(main.settings, "upload_dir", settings.upload_dir)
    monkeypatch.setattr(main.settings, "report_dir", settings.report_dir)
    monkeypatch.setattr(main.settings, "openai_api_key", "test-key")
    return TestClient(main.app)


def exam_payload() -> dict:
    return {
        "title": "Unit Test",
        "subject": "Physics",
        "questions": [
            {
                "id": "Q1",
                "text": "Define velocity.",
                "max_marks": 2,
                "model_answer": "Velocity is speed in a specific direction.",
                "marking_rules": "Definition and direction are required.",
                "keywords": ["speed", "direction"],
            },
            {
                "id": "Q2",
                "text": "Explain acceleration.",
                "max_marks": 3,
                "model_answer": "Acceleration is the rate of change of velocity.",
            },
        ],
    }


def create_exam(client: TestClient) -> dict:
    response = client.post("/exams", json=exam_payload())
    assert response.status_code == 200, response.text
    return response.json()


def upload_submission(client: TestClient, exam_id: str) -> dict:
    response = client.post(
        f"/exams/{exam_id}/submissions",
        data={"student_name": "Asha", "usn": "1BM22CS101"},
        files={"files": ("sheet.png", b"fake-image", "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_exam_rejects_empty_schema(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    response = client.post(
        "/exams",
        json={"title": "Bad", "subject": "Physics", "questions": []},
    )
    assert response.status_code == 422


def test_submission_evaluation_update_and_report(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    exam = create_exam(client)
    submission = upload_submission(client, exam["id"])

    def fake_evaluator(**kwargs):
        return {
            "student_name": "Asha",
            "usn": "1BM22CS101",
            "questions": [
                {
                    "question_id": "Q1",
                    "answer_text": "Velocity is speed with direction.",
                    "score": 2,
                    "max_marks": 2,
                    "reason": "Correct.",
                    "missing_points": [],
                    "confidence": 96,
                    "review_required": False,
                },
                {
                    "question_id": "Q2",
                    "answer_text": "Acceleration is when speed changes.",
                    "score": 2,
                    "max_marks": 3,
                    "reason": "Partly correct.",
                    "missing_points": ["Rate of change wording"],
                    "confidence": 72,
                    "review_required": False,
                },
            ],
            "summary": {
                "overall_feedback": "Good basics.",
                "weak_areas": ["Acceleration definition"],
            },
        }

    monkeypatch.setattr(main, "evaluate_submission_with_openai", fake_evaluator)

    start = client.post(f"/submissions/{submission['id']}/evaluate")
    assert start.status_code == 200, start.text

    fetched = client.get(f"/submissions/{submission['id']}").json()
    assert fetched["status"] == "completed"
    assert fetched["total_score"] == 4
    assert fetched["evaluations"][1]["review_required"] is True

    evaluation_id = fetched["evaluations"][0]["id"]
    updated = client.patch(f"/evaluations/{evaluation_id}", json={"final_score": 9}).json()
    assert updated["final_score"] == 2

    report = client.get(f"/submissions/{submission['id']}/report")
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"


def test_missing_openai_key_returns_setup_error(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    main.settings.openai_api_key = ""
    exam = create_exam(client)
    submission = upload_submission(client, exam["id"])

    response = client.post(f"/submissions/{submission['id']}/evaluate")
    assert response.status_code == 400
    assert "OPENAI_API_KEY" in response.json()["detail"]
