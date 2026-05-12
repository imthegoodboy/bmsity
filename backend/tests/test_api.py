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
    settings.teacher_email = "teacher@bmsit.ac.in"
    settings.teacher_password = "test-teacher-password"
    settings.auth_secret = "test-secret"
    init_db(settings.database_path)
    monkeypatch.setattr(main.settings, "database_path", settings.database_path)
    monkeypatch.setattr(main.settings, "upload_dir", settings.upload_dir)
    monkeypatch.setattr(main.settings, "report_dir", settings.report_dir)
    monkeypatch.setattr(main.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(main.settings, "teacher_email", "teacher@bmsit.ac.in")
    monkeypatch.setattr(main.settings, "teacher_password", "test-teacher-password")
    monkeypatch.setattr(main.settings, "auth_secret", "test-secret")
    monkeypatch.setattr(main, "verify_schema_with_openai", lambda **kwargs: kwargs["draft_schema"])
    monkeypatch.setattr(main, "verify_evaluation_with_openai", lambda **kwargs: kwargs["draft_result"])
    return TestClient(main.app)


def teacher_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/teacher/login",
        json={"identifier": "teacher@bmsit.ac.in", "password": "test-teacher-password"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


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


def choice_exam_payload() -> dict:
    return {
        "title": "Choice Test",
        "subject": "Computer Vision",
        "max_questions_to_grade": 4,
        "questions": [
            {
                "id": f"Q{index}",
                "text": f"Question {index}",
                "max_marks": 10,
                "model_answer": f"Model answer {index}",
            }
            for index in range(1, 9)
        ],
    }


def section_choice_exam_payload() -> dict:
    return {
        "title": "Section Choice Test",
        "subject": "Computer Vision",
        "total_marks": 30,
        "choice_rules": [
            {
                "type": "compulsory",
                "count": None,
                "question_ids": ["Q1"],
                "description": "Q1 is compulsory.",
            },
            {
                "type": "best_n",
                "count": 2,
                "question_ids": ["Q2", "Q3", "Q4"],
                "description": "Answer any two from Q2 to Q4.",
            },
        ],
        "questions": [
            {
                "id": f"Q{index}",
                "text": f"Question {index}",
                "max_marks": 10,
                "model_answer": f"Model answer {index}",
            }
            for index in range(1, 5)
        ],
    }


def create_exam(client: TestClient) -> dict:
    response = client.post("/exams", json=exam_payload(), headers=teacher_headers(client))
    assert response.status_code == 200, response.text
    return response.json()


def upload_submission(client: TestClient, exam_id: str) -> dict:
    response = client.post(
        f"/exams/{exam_id}/submissions",
        data={"student_name": "Asha", "usn": "1BM22CS101"},
        files={"files": ("sheet.png", b"fake-image", "image/png")},
        headers=teacher_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_exam_rejects_empty_schema(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    response = client.post(
        "/exams",
        json={"title": "Bad", "subject": "Physics", "questions": []},
        headers=teacher_headers(client),
    )
    assert response.status_code == 422


def test_schema_extract_rejects_unsupported_upload_type(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    response = client.post(
        "/schema/extract",
        data={"subject": "Computer Science", "title": "Bad Upload"},
        files={"file": ("schema.txt", b"plain text", "text/plain")},
        headers=teacher_headers(client),
    )

    assert response.status_code == 400
    assert "Unsupported answer scheme file" in response.json()["detail"]


def test_submission_rejects_unsupported_answer_sheet_type(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    exam = create_exam(client)
    response = client.post(
        f"/exams/{exam['id']}/submissions",
        data={"student_name": "Asha", "usn": "1BM22CS101"},
        files={"files": ("sheet.txt", b"plain text", "text/plain")},
        headers=teacher_headers(client),
    )

    assert response.status_code == 400
    assert "Unsupported answer sheet file" in response.json()["detail"]


def test_attempt_hints_normalize_common_question_formats():
    assert main._parse_attempt_hints("Q.1(a), question 2(ii); 3b") == ["Q1.a", "Q2.ii", "Q3.b"]


def test_attempt_hints_accept_free_text_and_filter_to_exam_questions():
    questions = [
        {"id": "Q1", "parts": [{"id": "Q1.a"}]},
        {"id": "Q2", "parts": [{"id": "Q2.ii"}]},
        {"id": "Q3", "parts": [{"id": "Q3.b"}]},
    ]

    assert main._parse_attempt_hints(
        "student solved question 2(ii) Q.1(a) 3b and 40 marks",
        valid_question_ids=main._question_hint_ids(questions),
    ) == ["Q2.ii", "Q1.a", "Q3.b"]


def test_nonfinite_ai_numbers_fall_back_safely():
    assert main._as_float("NaN", fallback=7) == 7
    assert main._as_positive_float("Infinity") is None
    assert main._as_positive_int("4.0") == 4
    assert main._clamp(float("nan"), 0, 10) == 0
    assert main.reportable_evaluations(
        [
            {
                "question_id": "Q1",
                "attempted": True,
                "answer_text": "No extracted answer text returned.",
                "final_score": 0,
            },
            {
                "question_id": "Q2",
                "attempted": True,
                "answer_text": "Real answer text.",
                "final_score": "NaN",
            },
        ]
    ) == [
        {
            "question_id": "Q2",
            "attempted": True,
            "answer_text": "Real answer text.",
            "final_score": "NaN",
        }
    ]


def test_schema_image_creates_exam(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    def fake_schema_extractor(**kwargs):
        return {
            "title": "Computer Components",
            "subject": "Computer Science",
            "instructions": "Use teacher answer points.",
            "questions": [
                {
                    "id": "Q2",
                    "text": "What is a computer? Explain the components of a computer.",
                    "max_marks": 10,
                    "model_answer": "A computer processes data and includes input, output, storage, CPU, ALU, and control unit.",
                    "marking_rules": "Award partial marks for definition and components.",
                    "keywords": ["computer", "input", "output", "storage", "CPU", "ALU", "control"],
                }
            ],
        }

    monkeypatch.setattr(main, "extract_schema_with_openai", fake_schema_extractor)
    response = client.post(
        "/schema/extract",
        data={"subject": "Computer Science", "title": "Answer Schema", "default_marks": "10"},
        files={"file": ("schema.webp", b"fake-schema-image", "image/webp")},
        headers=teacher_headers(client),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["subject"] == "Computer Science"
    assert payload["total_marks"] == 10
    assert payload["questions"][0]["id"] == "Q2"
    assert "components" in payload["questions"][0]["text"]


def test_schema_extract_accepts_question_paper_and_nested_parts(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    captured: dict[str, int] = {}

    def fake_schema_extractor(**kwargs):
        captured["schema_count"] = len(kwargs["schema_paths"])
        captured["question_count"] = len(kwargs["question_paper_paths"])
        return {
            "title": "Nested Paper",
            "subject": "Computer Vision",
            "instructions": "Answer all questions.",
            "total_marks": 10,
            "max_questions_to_grade": None,
            "choice_rule": "Answer all questions.",
            "questions": [
                {
                    "id": "Q1",
                    "text": "Answer both subparts.",
                    "max_marks": 10,
                    "model_answer": "",
                    "marking_rules": "",
                    "keywords": [],
                    "parts": [
                        {
                            "id": "Q1.a",
                            "label": "a",
                            "text": "Explain inverse problem.",
                            "max_marks": 5,
                            "model_answer": "Recover scene properties from image data.",
                            "marking_rules": "",
                            "keywords": ["inverse"],
                        },
                        {
                            "id": "Q1.b",
                            "label": "b",
                            "text": "Explain lighting ambiguity.",
                            "max_marks": 5,
                            "model_answer": "Lighting changes appearance while object properties remain.",
                            "marking_rules": "",
                            "keywords": ["lighting"],
                        },
                    ],
                }
            ],
        }

    monkeypatch.setattr(main, "extract_schema_with_openai", fake_schema_extractor)
    response = client.post(
        "/schema/extract",
        data={"subject": "Computer Vision", "title": "Nested Paper"},
        files=[
            ("question_files", ("paper-1.png", b"fake-paper", "image/png")),
            ("schema_files", ("scheme-1.png", b"fake-scheme-1", "image/png")),
            ("schema_files", ("scheme-2.png", b"fake-scheme-2", "image/png")),
        ],
        headers=teacher_headers(client),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert captured == {"schema_count": 2, "question_count": 1}
    assert payload["questions"][0]["max_marks"] == 10
    assert [part["id"] for part in payload["questions"][0]["parts"]] == ["Q1.a", "Q1.b"]


def test_schema_extraction_uses_verifier_repair_pass(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    captured: dict[str, str] = {}

    def fake_schema_extractor(**kwargs):
        return {
            "title": "Draft Paper",
            "subject": "Computer Vision",
            "instructions": "Answer all questions.",
            "total_marks": 40,
            "max_questions_to_grade": None,
            "choice_rule": "Answer all questions.",
            "questions": [
                {
                    "id": "Q1",
                    "text": "Question 1",
                    "max_marks": 40,
                    "model_answer": "Model answer 1",
                    "marking_rules": "",
                    "keywords": [],
                    "parts": [],
                }
            ],
        }

    def fake_schema_verifier(**kwargs):
        captured["draft_title"] = kwargs["draft_schema"]["title"]
        return {
            **kwargs["draft_schema"],
            "title": "Verified Paper",
            "max_questions_to_grade": 1,
            "choice_rule": "Answer any one question.",
            "choice_rules": [
                {
                    "type": "best_n",
                    "count": 1,
                    "question_ids": ["Q1"],
                    "description": "Answer any one question.",
                }
            ],
        }

    monkeypatch.setattr(main, "extract_schema_with_openai", fake_schema_extractor)
    monkeypatch.setattr(main, "verify_schema_with_openai", fake_schema_verifier)
    response = client.post(
        "/schema/extract",
        data={"subject": "Computer Vision", "title": "Verifier Test"},
        files={"file": ("schema.pdf", b"fake-schema-pdf", "application/pdf")},
        headers=teacher_headers(client),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert captured["draft_title"] == "Draft Paper"
    assert payload["title"] == "Verified Paper"
    assert payload["choice_rules"][0]["description"] == "Answer any one question."


def test_schema_verifier_failure_does_not_discard_valid_extraction(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    def fake_schema_extractor(**kwargs):
        return {
            "title": "Draft Paper",
            "subject": "Computer Vision",
            "instructions": "Answer any one question.",
            "total_marks": 10,
            "max_questions_to_grade": 1,
            "choice_rule": "Answer any one question.",
            "choice_rules": [
                {
                    "type": "best_n",
                    "count": 1,
                    "question_ids": ["Q1", "Q2"],
                    "description": "Answer any one question.",
                }
            ],
            "questions": [
                {
                    "id": "Q1",
                    "text": "Question 1",
                    "max_marks": 10,
                    "model_answer": "Model answer 1",
                    "marking_rules": "",
                    "keywords": [],
                    "parts": [],
                },
                {
                    "id": "Q2",
                    "text": "Question 2",
                    "max_marks": 10,
                    "model_answer": "Model answer 2",
                    "marking_rules": "",
                    "keywords": [],
                    "parts": [],
                },
            ],
        }

    def failing_schema_verifier(**kwargs):
        raise RuntimeError("temporary verifier outage")

    monkeypatch.setattr(main, "extract_schema_with_openai", fake_schema_extractor)
    monkeypatch.setattr(main, "verify_schema_with_openai", failing_schema_verifier)
    response = client.post(
        "/schema/extract",
        data={"subject": "Computer Vision", "title": "Verifier Fallback"},
        files={"file": ("schema.pdf", b"fake-schema-pdf", "application/pdf")},
        headers=teacher_headers(client),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "Draft Paper"
    assert payload["total_marks"] == 10
    assert payload["max_questions_to_grade"] == 1
    assert "schema verifier could not complete" in payload["instructions"].lower()


def test_schema_section_choice_rules_are_not_flattened_to_global_best_n(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    def fake_schema_extractor(**kwargs):
        return {
            "title": "Section Paper",
            "subject": "Computer Vision",
            "instructions": "Q1 is compulsory. Answer any two from Q2 to Q4.",
            "total_marks": None,
            "max_questions_to_grade": None,
            "choice_rule": "Q1 compulsory; answer any 2 from Q2-Q4.",
            "choice_rules": [
                {
                    "type": "compulsory",
                    "count": None,
                    "question_ids": ["Q1"],
                    "description": "Q1 is compulsory.",
                },
                {
                    "type": "best_n",
                    "count": 2,
                    "question_ids": ["Q2", "Q3", "Q4"],
                    "description": "Answer any two from Q2 to Q4.",
                },
            ],
            "questions": [
                {
                    "id": f"Q{index}",
                    "text": f"Question {index}",
                    "max_marks": 10,
                    "model_answer": f"Model answer {index}",
                    "marking_rules": "",
                    "keywords": [],
                    "parts": [],
                }
                for index in range(1, 5)
            ],
        }

    monkeypatch.setattr(main, "extract_schema_with_openai", fake_schema_extractor)
    response = client.post(
        "/schema/extract",
        data={"subject": "Computer Vision", "title": "Section Paper"},
        files={"file": ("schema.pdf", b"fake-schema-pdf", "application/pdf")},
        headers=teacher_headers(client),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_marks"] == 30
    assert payload["max_questions_to_grade"] is None
    assert [rule["type"] for rule in payload["choice_rules"]] == ["compulsory", "best_n"]
    assert "best 3 of 4" not in payload["instructions"].lower()


def test_schema_choice_rule_normalizes_total_and_per_question_marks(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    def fake_schema_extractor(**kwargs):
        return {
            "title": "BAI505B CV IA 1",
            "subject": "Computer Vision",
            "instructions": "Answer any four questions.",
            "total_marks": 40,
            "max_questions_to_grade": 4,
            "choice_rule": "Answer any 4 out of 8 questions.",
            "questions": [
                {
                    "id": str(index),
                    "text": f"Question {index}",
                    "max_marks": 40,
                    "model_answer": f"Model answer {index}",
                    "marking_rules": "",
                    "keywords": [],
                }
                for index in range(1, 9)
            ],
        }

    monkeypatch.setattr(main, "extract_schema_with_openai", fake_schema_extractor)
    response = client.post(
        "/schema/extract",
        data={"subject": "Computer Vision", "title": "Choice Paper", "default_marks": "40"},
        files={"file": ("schema.pdf", b"fake-schema-pdf", "application/pdf")},
        headers=teacher_headers(client),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_marks"] == 40
    assert payload["max_questions_to_grade"] == 4
    assert len(payload["questions"]) == 8
    assert all(question["max_marks"] == 10 for question in payload["questions"])


def test_schema_total_marks_overrides_wrong_all_questions_extraction(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    def fake_schema_extractor(**kwargs):
        return {
            "title": "BAI505B CV IA 1",
            "subject": "Computer Vision",
            "instructions": "Answer all questions. Max. Marks: 40",
            "total_marks": 40,
            "max_questions_to_grade": 8,
            "choice_rule": "Answer all questions",
            "choice_rules": [
                {
                    "type": "compulsory",
                    "count": None,
                    "question_ids": [str(index) for index in range(1, 9)],
                    "description": "Answer all questions",
                }
            ],
            "questions": [
                {
                    "id": str(index),
                    "text": f"Question {index}",
                    "max_marks": 12 if index == 3 else 5 if index == 5 else 10,
                    "model_answer": f"Model answer {index}",
                    "marking_rules": "",
                    "keywords": [],
                }
                for index in range(1, 9)
            ],
        }

    monkeypatch.setattr(main, "extract_schema_with_openai", fake_schema_extractor)
    response = client.post(
        "/schema/extract",
        data={"subject": "Computer Vision", "title": "Choice Paper"},
        files={"file": ("schema.pdf", b"fake-schema-pdf", "application/pdf")},
        headers=teacher_headers(client),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_marks"] == 40
    assert payload["max_questions_to_grade"] == 4
    assert payload["choice_rules"][0]["type"] == "best_n"
    marks_by_id = {question["id"]: question["max_marks"] for question in payload["questions"]}
    assert marks_by_id["3"] == 10
    assert marks_by_id["5"] == 5
    assert marks_by_id["1"] == 10
    assert "answer all questions" not in payload["instructions"].lower()
    assert "best 4 of 8" in payload["instructions"].lower()


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

    headers = teacher_headers(client)
    start = client.post(f"/submissions/{submission['id']}/evaluate", headers=headers)
    assert start.status_code == 200, start.text

    fetched = client.get(f"/submissions/{submission['id']}", headers=headers).json()
    assert fetched["status"] == "completed"
    assert fetched["published"] is False
    assert fetched["total_score"] == 4
    assert fetched["evaluations"][1]["review_required"] is True

    evaluation_id = fetched["evaluations"][0]["id"]
    updated = client.patch(
        f"/evaluations/{evaluation_id}",
        json={"final_score": 9},
        headers=headers,
    ).json()
    assert updated["final_score"] == 2

    report = client.get(f"/submissions/{submission['id']}/report", headers=headers)
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"


def test_evaluation_backfills_missing_questions_for_review(tmp_path, monkeypatch):
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
                }
            ],
            "summary": {
                "overall_feedback": "Question Q2 needs review.",
                "weak_areas": ["Missing evaluation"],
            },
        }

    monkeypatch.setattr(main, "evaluate_submission_with_openai", fake_evaluator)

    headers = teacher_headers(client)
    start = client.post(f"/submissions/{submission['id']}/evaluate", headers=headers)
    assert start.status_code == 200, start.text

    fetched = client.get(f"/submissions/{submission['id']}", headers=headers).json()
    assert fetched["status"] == "completed"
    assert fetched["total_score"] == 2
    assert len(fetched["evaluations"]) == 2

    q2 = next(item for item in fetched["evaluations"] if item["question_id"] == "Q2")
    assert q2["score"] == 0
    assert q2["final_score"] == 0
    assert q2["confidence"] == 0
    assert q2["review_required"] is True

    captured: dict[str, list[str]] = {}

    def fake_generate_report(**kwargs):
        captured["question_ids"] = [item["question_id"] for item in kwargs["evaluations"]]
        destination = kwargs["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"%PDF-1.4\n%%EOF")
        return destination

    monkeypatch.setattr(main, "generate_report", fake_generate_report)
    report = client.get(f"/submissions/{submission['id']}/report", headers=headers)
    assert report.status_code == 200
    assert captured["question_ids"] == ["Q1"]


def test_agent_placeholder_attempt_is_not_counted_or_reported(tmp_path, monkeypatch):
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
                    "answer_text": "No distinct answer visible.",
                    "attempted": True,
                    "score": 1,
                    "max_marks": 2,
                    "reason": "Agent incorrectly awarded this placeholder.",
                    "missing_points": ["No visible answer"],
                    "confidence": 91,
                    "review_required": False,
                },
                {
                    "question_id": "Q2",
                    "answer_text": "Acceleration is the rate of change of velocity.",
                    "attempted": True,
                    "score": 3,
                    "max_marks": 3,
                    "reason": "Correct.",
                    "missing_points": [],
                    "confidence": 94,
                    "review_required": False,
                },
            ],
            "summary": {
                "overall_feedback": "One real answer detected.",
                "weak_areas": [],
            },
        }

    monkeypatch.setattr(main, "evaluate_submission_with_openai", fake_evaluator)
    headers = teacher_headers(client)
    start = client.post(f"/submissions/{submission['id']}/evaluate", headers=headers)
    assert start.status_code == 200, start.text

    fetched = client.get(f"/submissions/{submission['id']}", headers=headers).json()
    q1 = next(item for item in fetched["evaluations"] if item["question_id"] == "Q1")
    q2 = next(item for item in fetched["evaluations"] if item["question_id"] == "Q2")
    assert q1["attempted"] is False
    assert q1["answer_text"] == ""
    assert q1["final_score"] == 0
    assert q2["attempted"] is True
    assert fetched["total_score"] == 3

    captured: dict[str, list[str]] = {}

    def fake_generate_report(**kwargs):
        captured["question_ids"] = [item["question_id"] for item in kwargs["evaluations"]]
        destination = kwargs["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"%PDF-1.4\n%%EOF")
        return destination

    monkeypatch.setattr(main, "generate_report", fake_generate_report)
    report = client.get(f"/submissions/{submission['id']}/report", headers=headers)
    assert report.status_code == 200
    assert captured["question_ids"] == ["Q2"]


def test_choice_exam_scores_best_attempted_questions_only(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = teacher_headers(client)
    exam_response = client.post("/exams", json=choice_exam_payload(), headers=headers)
    assert exam_response.status_code == 200, exam_response.text
    exam = exam_response.json()
    assert exam["total_marks"] == 40

    submission = upload_submission(client, exam["id"])

    def fake_evaluator(**kwargs):
        return {
            "student_name": "Asha",
            "usn": "1BM22CS101",
            "questions": [
                {
                    "question_id": f"Q{index}",
                    "answer_text": f"Student answer {index}" if index <= 5 else "",
                    "attempted": index <= 5 and index != 4,
                    "score": score,
                    "max_marks": 10,
                    "reason": "Checked.",
                    "missing_points": [],
                    "confidence": 90,
                    "review_required": False,
                }
                for index, score in enumerate([8, 7, 6, 5, 9, 0, 0, 0], start=1)
            ],
            "summary": {
                "overall_feedback": "Best four attempted questions counted.",
                "weak_areas": [],
            },
        }

    monkeypatch.setattr(main, "evaluate_submission_with_openai", fake_evaluator)
    start = client.post(f"/submissions/{submission['id']}/evaluate", headers=headers)
    assert start.status_code == 200, start.text

    fetched = client.get(f"/submissions/{submission['id']}", headers=headers).json()
    assert fetched["status"] == "completed"
    assert fetched["total_score"] == 30
    assert fetched["total_marks"] == 40

    counted = {item["question_id"] for item in fetched["evaluations"] if item["counts_toward_total"]}
    assert counted == {"Q1", "Q2", "Q3", "Q5"}
    assert next(item for item in fetched["evaluations"] if item["question_id"] == "Q4")["attempted"] is True
    assert next(item for item in fetched["evaluations"] if item["question_id"] == "Q4")["counts_toward_total"] is False
    assert next(item for item in fetched["evaluations"] if item["question_id"] == "Q8")["attempted"] is False


def test_section_choice_rules_count_compulsory_and_best_group(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = teacher_headers(client)
    exam_response = client.post("/exams", json=section_choice_exam_payload(), headers=headers)
    assert exam_response.status_code == 200, exam_response.text
    exam = exam_response.json()
    submission = upload_submission(client, exam["id"])

    def fake_evaluator(**kwargs):
        return {
            "student_name": "Asha",
            "usn": "1BM22CS101",
            "questions": [
                {
                    "question_id": f"Q{index}",
                    "answer_text": f"Student answer {index}",
                    "attempted": True,
                    "score": score,
                    "max_marks": 10,
                    "reason": "Checked.",
                    "missing_points": [],
                    "confidence": 90,
                    "review_required": False,
                }
                for index, score in enumerate([6, 7, 9, 4], start=1)
            ],
            "summary": {"overall_feedback": "Section rules applied.", "weak_areas": []},
        }

    monkeypatch.setattr(main, "evaluate_submission_with_openai", fake_evaluator)
    start = client.post(f"/submissions/{submission['id']}/evaluate", headers=headers)
    assert start.status_code == 200, start.text

    fetched = client.get(f"/submissions/{submission['id']}", headers=headers).json()
    assert fetched["total_score"] == 22
    assert fetched["total_marks"] == 30
    counted = {item["question_id"] for item in fetched["evaluations"] if item["counts_toward_total"]}
    assert counted == {"Q1", "Q2", "Q3"}


def test_part_level_evaluator_output_rolls_up_to_parent_question(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = teacher_headers(client)
    exam_response = client.post(
        "/exams",
        json={
            "title": "Part Test",
            "subject": "Computer Vision",
            "questions": [
                {
                    "id": "Q1",
                    "text": "Answer both subparts.",
                    "max_marks": 10,
                    "model_answer": "Use part rubrics.",
                    "parts": [
                        {
                            "id": "Q1.a",
                            "label": "a",
                            "text": "Part a",
                            "max_marks": 5,
                            "model_answer": "Answer a",
                        },
                        {
                            "id": "Q1.b",
                            "label": "b",
                            "text": "Part b",
                            "max_marks": 5,
                            "model_answer": "Answer b",
                        },
                    ],
                }
            ],
        },
        headers=headers,
    )
    assert exam_response.status_code == 200, exam_response.text
    submission = upload_submission(client, exam_response.json()["id"])

    def fake_evaluator(**kwargs):
        return {
            "student_name": "Asha",
            "usn": "1BM22CS101",
            "questions": [
                {
                    "question_id": "Q1",
                    "answer_text": "No distinct answer visible.",
                    "attempted": False,
                    "score": 0,
                    "max_marks": 10,
                    "reason": "Parent row missed the subpart answers.",
                    "missing_points": [],
                    "confidence": 45,
                    "review_required": True,
                },
                {
                    "question_id": "Q1.a",
                    "answer_text": "Student answer for part a.",
                    "attempted": True,
                    "score": 4,
                    "max_marks": 5,
                    "reason": "Part a mostly correct.",
                    "missing_points": [],
                    "confidence": 92,
                    "review_required": False,
                },
                {
                    "question_id": "Q1.b",
                    "answer_text": "Student answer for part b.",
                    "attempted": True,
                    "score": 3,
                    "max_marks": 5,
                    "reason": "Part b partially correct.",
                    "missing_points": ["Missing example"],
                    "confidence": 88,
                    "review_required": False,
                },
            ],
            "summary": {"overall_feedback": "Parts merged.", "weak_areas": []},
        }

    monkeypatch.setattr(main, "evaluate_submission_with_openai", fake_evaluator)
    start = client.post(f"/submissions/{submission['id']}/evaluate", headers=headers)
    assert start.status_code == 200, start.text
    fetched = client.get(f"/submissions/{submission['id']}", headers=headers).json()
    q1 = fetched["evaluations"][0]
    assert q1["question_id"] == "Q1"
    assert q1["final_score"] == 7
    assert "Q1.a" in q1["answer_text"]
    assert "Q1.b: Missing example" in q1["missing_points"]


def test_missing_openai_key_returns_setup_error(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    main.settings.openai_api_key = ""
    exam = create_exam(client)
    submission = upload_submission(client, exam["id"])

    response = client.post(f"/submissions/{submission['id']}/evaluate", headers=teacher_headers(client))
    assert response.status_code == 400
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_student_login_password_change_and_portal(tmp_path, monkeypatch):
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
                    "answer_text": "Acceleration is the rate of velocity change.",
                    "score": 3,
                    "max_marks": 3,
                    "reason": "Correct.",
                    "missing_points": [],
                    "confidence": 94,
                    "review_required": False,
                },
            ],
            "summary": {
                "overall_feedback": "Strong basics.",
                "weak_areas": [],
            },
        }

    monkeypatch.setattr(main, "evaluate_submission_with_openai", fake_evaluator)
    headers = teacher_headers(client)

    blocked_login = client.post(
        "/auth/student/login",
        json={"identifier": "1bm22cs101", "password": "1BM22CS101"},
    )
    assert blocked_login.status_code == 401

    start = client.post(f"/submissions/{submission['id']}/evaluate", headers=headers)
    assert start.status_code == 200, start.text

    blocked_after_eval = client.post(
        "/auth/student/login",
        json={"identifier": "1bm22cs101", "password": "1BM22CS101"},
    )
    assert blocked_after_eval.status_code == 401

    publish = client.post(f"/submissions/{submission['id']}/publish", headers=headers)
    assert publish.status_code == 200, publish.text
    assert publish.json()["published"] is True

    login = client.post(
        "/auth/student/login",
        json={"identifier": "1bm22cs101", "password": "1BM22CS101"},
    )
    assert login.status_code == 200, login.text
    student_token = login.json()["token"]
    assert login.json()["force_password_change"] is True

    portal = client.get("/students/me", headers={"Authorization": f"Bearer {student_token}"})
    assert portal.status_code == 200, portal.text
    assert portal.json()["submissions"][0]["exam"]["title"] == "Unit Test"

    changed = client.post(
        "/auth/student/change-password",
        json={"current_password": "1BM22CS101", "new_password": "new-secure-pass"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["force_password_change"] is False

    old_login = client.post(
        "/auth/student/login",
        json={"identifier": "1BM22CS101", "password": "1BM22CS101"},
    )
    assert old_login.status_code == 401
