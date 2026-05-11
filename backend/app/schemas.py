from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


class QuestionIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1)
    max_marks: float = Field(gt=0)
    model_answer: str = Field(min_length=1)
    marking_rules: str = ""
    keywords: list[str] = Field(default_factory=list)

    @field_validator("id", "text", "model_answer", "marking_rules")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class ExamCreate(BaseModel):
    title: str = Field(default="Untitled Exam", max_length=120)
    subject: str = Field(min_length=1, max_length=120)
    instructions: str = ""
    total_marks: float | None = Field(default=None, gt=0)
    questions: list[QuestionIn] = Field(min_length=1)

    @field_validator("title", "subject", "instructions")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_questions(self) -> "ExamCreate":
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("Question IDs must be unique.")
        if self.total_marks is None:
            self.total_marks = sum(question.max_marks for question in self.questions)
        return self


class ExamOut(BaseModel):
    id: str
    title: str
    subject: str
    total_marks: float
    instructions: str
    questions: list[QuestionIn]
    created_at: str


class EvaluationOut(BaseModel):
    id: str
    question_id: str
    question_text: str
    answer_text: str
    score: float
    max_marks: float
    final_score: float
    confidence: float
    review_required: bool
    reason: str
    missing_points: list[str]
    updated_at: str


class EvaluationUpdate(BaseModel):
    final_score: Annotated[float | None, Field(ge=0)] = None
    reason: str | None = None
    review_required: bool | None = None

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class SubmissionFileOut(BaseModel):
    id: str
    original_name: str
    mime_type: str
    size_bytes: int


class SubmissionOut(BaseModel):
    id: str
    exam_id: str
    student_name: str
    usn: str
    status: str
    published: bool = False
    total_score: float
    total_marks: float
    average_confidence: float
    error: str
    overall_feedback: str
    weak_areas: list[str]
    files: list[SubmissionFileOut]
    evaluations: list[EvaluationOut]
    created_at: str
    updated_at: str


class SubmissionCreated(BaseModel):
    id: str
    exam_id: str
    student_name: str
    usn: str
    status: str


class StartEvaluationOut(BaseModel):
    submission_id: str
    status: str
    message: str


class LoginIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("identifier", "password")
    @classmethod
    def strip_login_text(cls, value: str) -> str:
        return value.strip()


class AuthOut(BaseModel):
    token: str
    role: str
    display_name: str
    identifier: str
    force_password_change: bool = False


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)

    @field_validator("current_password", "new_password")
    @classmethod
    def strip_password(cls, value: str) -> str:
        return value.strip()


class StudentExamSummary(BaseModel):
    id: str
    title: str
    subject: str
    total_marks: float
    created_at: str


class StudentSubmissionOut(BaseModel):
    id: str
    exam: StudentExamSummary
    student_name: str
    usn: str
    status: str
    published: bool
    total_score: float
    total_marks: float
    average_confidence: float
    error: str
    overall_feedback: str
    weak_areas: list[str]
    evaluations: list[EvaluationOut]
    created_at: str
    updated_at: str


class StudentPortalOut(BaseModel):
    student_name: str
    usn: str
    force_password_change: bool
    submissions: list[StudentSubmissionOut]
