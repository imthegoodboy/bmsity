"use client";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
export const SESSION_KEY = "bmsitai-session";

export type Role = "teacher" | "student";
export type TeacherView = "exams" | "check" | "review" | "analytics";

export type Question = {
  id: string;
  text: string;
  max_marks: number;
  model_answer: string;
  marking_rules: string;
  keywords: string[];
};

export type Exam = {
  id: string;
  title: string;
  subject: string;
  total_marks: number;
  instructions: string;
  questions: Question[];
  created_at: string;
};

export type Evaluation = {
  id: string;
  question_id: string;
  question_text: string;
  answer_text: string;
  score: number;
  max_marks: number;
  final_score: number;
  confidence: number;
  review_required: boolean;
  reason: string;
  missing_points: string[];
  updated_at?: string;
};

export type Submission = {
  id: string;
  exam_id: string;
  student_name: string;
  usn: string;
  status: "uploaded" | "running" | "completed" | "failed";
  published: boolean;
  total_score: number;
  total_marks: number;
  average_confidence: number;
  error: string;
  overall_feedback: string;
  weak_areas: string[];
  evaluations: Evaluation[];
  created_at: string;
  updated_at: string;
};

export type Health = {
  status: string;
  openai_configured: boolean;
  model: string;
};

export type AuthSession = {
  token: string;
  role: Role;
  display_name: string;
  identifier: string;
  force_password_change: boolean;
};

export type StudentPortal = {
  student_name: string;
  usn: string;
  force_password_change: boolean;
  submissions: Array<
    Omit<Submission, "exam_id"> & {
      exam: Pick<Exam, "id" | "title" | "subject" | "total_marks" | "created_at">;
    }
  >;
};

export type QueueEntry = {
  id: string;
  studentName: string;
  usn: string;
  files: File[];
  status: "queued" | "uploading" | "running" | "completed" | "failed";
  message: string;
  submissionId?: string;
};

export type DraftQuestion = {
  id: string;
  text: string;
  max_marks: number;
  model_answer: string;
  marking_rules: string;
  keywordsText: string;
};

export async function api<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Request failed");
  }
  return response.json();
}

export function readSession(): AuthSession | null {
  try {
    const stored = window.localStorage.getItem(SESSION_KEY);
    return stored ? (JSON.parse(stored) as AuthSession) : null;
  } catch {
    window.localStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function saveSession(session: AuthSession | null) {
  if (session) {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } else {
    window.localStorage.removeItem(SESSION_KEY);
  }
}

export function formatNumber(value: number) {
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

export function scorePercent(submission?: Pick<Submission, "total_score" | "total_marks"> | null) {
  if (!submission?.total_marks) return 0;
  return Math.round((submission.total_score / submission.total_marks) * 100);
}

export function statusLabel(status?: Submission["status"] | QueueEntry["status"]) {
  if (status === "completed") return "Completed";
  if (status === "failed") return "Needs attention";
  if (status === "running") return "Agent running";
  if (status === "uploading") return "Uploading";
  return "Queued";
}

export function statusClass(status?: Submission["status"] | QueueEntry["status"]) {
  if (status === "completed") return "status-pill status-good";
  if (status === "failed") return "status-pill status-bad";
  if (status === "running" || status === "uploading") return "status-pill status-warn";
  return "status-pill status-info";
}

export function emptyDraftQuestion(index = 1): DraftQuestion {
  return {
    id: "",
    text: "",
    max_marks: 0,
    model_answer: "",
    marking_rules: "",
    keywordsText: "",
  };
}

export function computeAnalytics(submissions: Submission[]) {
  const completed = submissions.filter((submission) => submission.status === "completed");
  const percentages = completed.map(scorePercent).filter((value) => Number.isFinite(value));
  const classAverage = percentages.length
    ? Math.round(percentages.reduce((total, value) => total + value, 0) / percentages.length)
    : 0;
  const passPercentage = completed.length
    ? Math.round((completed.filter((submission) => scorePercent(submission) >= 40).length / completed.length) * 100)
    : 0;
  const reviewFlags = completed.reduce(
    (total, submission) => total + submission.evaluations.filter((evaluation) => evaluation.review_required).length,
    0,
  );

  const questionMap = new Map<string, { earned: number; possible: number; attempts: number }>();
  for (const submission of completed) {
    for (const evaluation of submission.evaluations) {
      const current = questionMap.get(evaluation.question_id) ?? { earned: 0, possible: 0, attempts: 0 };
      current.earned += evaluation.final_score;
      current.possible += evaluation.max_marks;
      current.attempts += 1;
      questionMap.set(evaluation.question_id, current);
    }
  }

  const difficultQuestions = Array.from(questionMap.entries())
    .map(([questionId, item]) => ({
      questionId,
      average: item.possible ? Math.round((item.earned / item.possible) * 100) : 0,
      attempts: item.attempts,
    }))
    .sort((a, b) => a.average - b.average)
    .slice(0, 5);

  const weakAreaMap = new Map<string, number>();
  for (const submission of completed) {
    for (const weakArea of submission.weak_areas) {
      weakAreaMap.set(weakArea, (weakAreaMap.get(weakArea) ?? 0) + 1);
    }
  }
  const weakAreas = Array.from(weakAreaMap.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);

  return {
    completed: completed.length,
    classAverage,
    passPercentage,
    reviewFlags,
    difficultQuestions,
    weakAreas,
  };
}
