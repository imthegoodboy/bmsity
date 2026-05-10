"use client";

import {
  AlertTriangle,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileText,
  GraduationCap,
  Layers3,
  Loader2,
  LockKeyhole,
  LogOut,
  Plus,
  RefreshCcw,
  Save,
  SearchCheck,
  ShieldCheck,
  Upload,
  UserRound,
  Wand2,
} from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type Role = "teacher" | "student";
type TeacherView = "evaluate" | "review" | "analytics";

type Question = {
  id: string;
  text: string;
  max_marks: number;
  model_answer: string;
  marking_rules: string;
  keywords: string[];
};

type Exam = {
  id: string;
  title: string;
  subject: string;
  total_marks: number;
  instructions: string;
  questions: Question[];
  created_at: string;
};

type Evaluation = {
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

type Submission = {
  id: string;
  exam_id: string;
  student_name: string;
  usn: string;
  status: "uploaded" | "running" | "completed" | "failed";
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

type Health = {
  status: string;
  openai_configured: boolean;
  model: string;
};

type AuthSession = {
  token: string;
  role: Role;
  display_name: string;
  identifier: string;
  force_password_change: boolean;
};

type StudentPortal = {
  student_name: string;
  usn: string;
  force_password_change: boolean;
  submissions: Array<
    Omit<Submission, "exam_id"> & {
      exam: Pick<Exam, "id" | "title" | "subject" | "total_marks" | "created_at">;
    }
  >;
};

type QueueEntry = {
  id: string;
  studentName: string;
  usn: string;
  files: File[];
  status: "queued" | "uploading" | "running" | "completed" | "failed";
  message: string;
  submissionId?: string;
};

type DraftQuestion = {
  id: string;
  text: string;
  max_marks: number;
  model_answer: string;
  marking_rules: string;
  keywordsText: string;
};

async function api<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
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

function formatNumber(value: number) {
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

function scorePercent(submission?: Pick<Submission, "total_score" | "total_marks"> | null) {
  if (!submission?.total_marks) return 0;
  return Math.round((submission.total_score / submission.total_marks) * 100);
}

function statusLabel(status?: Submission["status"] | QueueEntry["status"]) {
  if (status === "completed") return "Completed";
  if (status === "failed") return "Needs attention";
  if (status === "running") return "Evaluating";
  if (status === "uploading") return "Uploading";
  return "Queued";
}

function statusClass(status?: Submission["status"] | QueueEntry["status"]) {
  if (status === "completed") return "status-pill status-good";
  if (status === "failed") return "status-pill status-bad";
  if (status === "running" || status === "uploading") return "status-pill status-warn";
  return "status-pill status-info";
}

const emptyDraftQuestion = (): DraftQuestion => ({
  id: "Q1",
  text: "",
  max_marks: 5,
  model_answer: "",
  marking_rules: "",
  keywordsText: "",
});

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loginRole, setLoginRole] = useState<Role>("teacher");
  const [loginIdentifier, setLoginIdentifier] = useState("teacher@bmsit.ac.in");
  const [loginPassword, setLoginPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const [teacherView, setTeacherView] = useState<TeacherView>("evaluate");
  const [exams, setExams] = useState<Exam[]>([]);
  const [activeExamId, setActiveExamId] = useState("");
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [activeSubmission, setActiveSubmission] = useState<Submission | null>(null);

  const [manualTitle, setManualTitle] = useState("Internal Assessment");
  const [manualSubject, setManualSubject] = useState("Computer Science");
  const [manualInstructions, setManualInstructions] = useState("");
  const [manualQuestions, setManualQuestions] = useState<DraftQuestion[]>([]);
  const [draftQuestion, setDraftQuestion] = useState<DraftQuestion>(emptyDraftQuestion);

  const [schemaSubject, setSchemaSubject] = useState("Computer Science");
  const [schemaTitle, setSchemaTitle] = useState("Answer Scheme");
  const [schemaMarks, setSchemaMarks] = useState(10);
  const [schemaFile, setSchemaFile] = useState<File | null>(null);

  const [studentName, setStudentName] = useState("");
  const [usn, setUsn] = useState("");
  const [answerFiles, setAnswerFiles] = useState<File[]>([]);
  const [queue, setQueue] = useState<QueueEntry[]>([]);

  const [studentPortal, setStudentPortal] = useState<StudentPortal | null>(null);
  const [activeStudentSubmissionId, setActiveStudentSubmissionId] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const activeExam = useMemo(
    () => exams.find((exam) => exam.id === activeExamId) ?? null,
    [activeExamId, exams],
  );

  const activeStudentSubmission = useMemo(() => {
    return (
      studentPortal?.submissions.find((submission) => submission.id === activeStudentSubmissionId) ??
      studentPortal?.submissions[0] ??
      null
    );
  }, [activeStudentSubmissionId, studentPortal]);

  const analytics = useMemo(() => computeAnalytics(submissions), [submissions]);

  useEffect(() => {
    const stored = window.localStorage.getItem("bmsitai-session");
    if (!stored) {
      void loadHealth();
      return;
    }
    try {
      const parsed = JSON.parse(stored) as AuthSession;
      setSession(parsed);
      setLoginRole(parsed.role);
      void refreshSession(parsed);
    } catch {
      window.localStorage.removeItem("bmsitai-session");
      void loadHealth();
    }
  }, []);

  useEffect(() => {
    if (loginRole === "teacher") {
      setLoginIdentifier("teacher@bmsit.ac.in");
    } else {
      setLoginIdentifier("");
    }
    setLoginPassword("");
  }, [loginRole]);

  useEffect(() => {
    if (session?.role === "teacher" && activeExamId) {
      void loadSubmissions(activeExamId, session.token);
    }
  }, [activeExamId, session?.role, session?.token]);

  async function loadHealth() {
    try {
      setHealth(await api<Health>("/health"));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "API unavailable");
    }
  }

  function persistSession(payload: AuthSession | null) {
    setSession(payload);
    if (payload) {
      window.localStorage.setItem("bmsitai-session", JSON.stringify(payload));
    } else {
      window.localStorage.removeItem("bmsitai-session");
    }
  }

  async function refreshSession(current = session) {
    if (!current) return;
    try {
      const fresh = await api<AuthSession>("/auth/me", undefined, current.token);
      persistSession(fresh);
      setNotice("");
      await loadHealth();
      if (fresh.role === "teacher") {
        await refreshTeacherData(fresh.token);
      } else {
        await refreshStudentData(fresh.token);
      }
    } catch (error) {
      persistSession(null);
      setNotice(error instanceof Error ? error.message : "Please login again");
    }
  }

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("login");
    setNotice("");
    try {
      const payload = await api<AuthSession>(`/auth/${loginRole}/login`, {
        method: "POST",
        body: JSON.stringify({ identifier: loginIdentifier, password: loginPassword }),
      });
      persistSession(payload);
      if (payload.role === "teacher") {
        await refreshTeacherData(payload.token);
      } else {
        await refreshStudentData(payload.token);
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Login failed");
    } finally {
      setBusy("");
    }
  }

  function logout() {
    persistSession(null);
    setExams([]);
    setSubmissions([]);
    setActiveSubmission(null);
    setStudentPortal(null);
    setActiveStudentSubmissionId("");
    setNotice("");
  }

  async function refreshTeacherData(token = session?.token) {
    if (!token) return;
    try {
      const [healthPayload, examPayload] = await Promise.all([
        api<Health>("/health"),
        api<Exam[]>("/exams", undefined, token),
      ]);
      setHealth(healthPayload);
      setExams(examPayload);
      const nextExamId = activeExamId || examPayload[0]?.id || "";
      setActiveExamId(nextExamId);
      if (nextExamId) {
        await loadSubmissions(nextExamId, token);
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load teacher workspace");
    }
  }

  async function loadSubmissions(examId: string, token = session?.token) {
    if (!token) return;
    try {
      const payload = await api<Submission[]>(`/exams/${examId}/submissions`, undefined, token);
      setSubmissions(payload);
      setActiveSubmission((current) => {
        if (current && payload.some((submission) => submission.id === current.id)) {
          return payload.find((submission) => submission.id === current.id) ?? current;
        }
        return payload[0] ?? null;
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load submissions");
    }
  }

  async function refreshStudentData(token = session?.token) {
    if (!token) return;
    try {
      const [healthPayload, portalPayload] = await Promise.all([
        api<Health>("/health"),
        api<StudentPortal>("/students/me", undefined, token),
      ]);
      setHealth(healthPayload);
      setStudentPortal(portalPayload);
      setActiveStudentSubmissionId((current) => current || portalPayload.submissions[0]?.id || "");
      setSession((current) => {
        if (!current) return current;
        const next = { ...current, force_password_change: portalPayload.force_password_change };
        window.localStorage.setItem("bmsitai-session", JSON.stringify(next));
        return next;
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load student portal");
    }
  }

  function onAnswerFiles(event: ChangeEvent<HTMLInputElement>) {
    setAnswerFiles(Array.from(event.target.files ?? []));
  }

  function addManualQuestion() {
    if (!draftQuestion.text.trim() || !draftQuestion.model_answer.trim()) {
      setNotice("Add question text and model answer before saving it.");
      return;
    }
    setManualQuestions((current) => [
      ...current,
      {
        ...draftQuestion,
        id: draftQuestion.id.trim() || `Q${current.length + 1}`,
        max_marks: Math.max(0.5, Number(draftQuestion.max_marks) || 1),
      },
    ]);
    setDraftQuestion({
      ...emptyDraftQuestion(),
      id: `Q${manualQuestions.length + 2}`,
      max_marks: draftQuestion.max_marks,
    });
    setNotice("");
  }

  async function createManualExam(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !manualQuestions.length) return;
    setBusy("manual-exam");
    setNotice("");
    try {
      const exam = await api<Exam>(
        "/exams",
        {
          method: "POST",
          body: JSON.stringify({
            title: manualTitle,
            subject: manualSubject,
            instructions: manualInstructions,
            questions: manualQuestions.map((question) => ({
              id: question.id,
              text: question.text,
              max_marks: question.max_marks,
              model_answer: question.model_answer,
              marking_rules: question.marking_rules,
              keywords: question.keywordsText
                .split(",")
                .map((keyword) => keyword.trim())
                .filter(Boolean),
            })),
          }),
        },
        session.token,
      );
      setExams((current) => [exam, ...current.filter((item) => item.id !== exam.id)]);
      setManualQuestions([]);
      setActiveExamId(exam.id);
      setNotice("Exam created and ready for student uploads.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create exam");
    } finally {
      setBusy("");
    }
  }

  async function extractSchema(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!schemaFile || !session) return;
    setBusy("schema");
    setNotice("");
    try {
      const form = new FormData();
      form.append("subject", schemaSubject);
      form.append("title", schemaTitle);
      form.append("default_marks", String(schemaMarks));
      form.append("file", schemaFile);
      const exam = await api<Exam>("/schema/extract", { method: "POST", body: form }, session.token);
      setExams((current) => [exam, ...current.filter((item) => item.id !== exam.id)]);
      setActiveExamId(exam.id);
      setSchemaFile(null);
      setNotice("Answer scheme extracted into a real exam rubric.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Schema extraction failed");
    } finally {
      setBusy("");
    }
  }

  function addQueueEntry() {
    if (!studentName.trim() || !usn.trim() || !answerFiles.length) {
      setNotice("Add student name, USN, and answer sheet files first.");
      return;
    }
    setQueue((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        studentName: studentName.trim(),
        usn: usn.trim().toUpperCase(),
        files: answerFiles,
        status: "queued",
        message: `${answerFiles.length} file${answerFiles.length === 1 ? "" : "s"} ready`,
      },
    ]);
    setStudentName("");
    setUsn("");
    setAnswerFiles([]);
    setNotice("");
  }

  function updateQueueEntry(id: string, patch: Partial<QueueEntry>) {
    setQueue((current) => current.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry)));
  }

  async function evaluateQueue() {
    if (!activeExam || !session) return;
    const targets = queue.filter((entry) => entry.status === "queued" || entry.status === "failed");
    if (!targets.length) return;
    setBusy("queue");
    setNotice("");
    for (const entry of targets) {
      try {
        updateQueueEntry(entry.id, { status: "uploading", message: "Uploading sheets" });
        const form = new FormData();
        form.append("student_name", entry.studentName);
        form.append("usn", entry.usn);
        entry.files.forEach((file) => form.append("files", file));
        const created = await api<{ id: string }>(
          `/exams/${activeExam.id}/submissions`,
          { method: "POST", body: form },
          session.token,
        );

        updateQueueEntry(entry.id, {
          status: "running",
          submissionId: created.id,
          message: "AI evaluation running",
        });
        await api<unknown>(`/submissions/${created.id}/evaluate`, { method: "POST" }, session.token);

        for (let attempt = 0; attempt < 120; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, 1500));
          const fresh = await api<Submission>(`/submissions/${created.id}`, undefined, session.token);
          if (fresh.status !== "running") {
            updateQueueEntry(entry.id, {
              status: fresh.status === "completed" ? "completed" : "failed",
              message:
                fresh.status === "completed"
                  ? `${formatNumber(fresh.total_score)} / ${formatNumber(fresh.total_marks)}`
                  : fresh.error || "Evaluation failed",
            });
            setActiveSubmission(fresh);
            break;
          }
        }
        await loadSubmissions(activeExam.id, session.token);
      } catch (error) {
        updateQueueEntry(entry.id, {
          status: "failed",
          message: error instanceof Error ? error.message : "Evaluation failed",
        });
      }
    }
    setBusy("");
  }

  async function saveEvaluation(evaluation: Evaluation, finalScore: number, reason: string) {
    if (!session || !activeSubmission) return;
    setBusy(evaluation.id);
    setNotice("");
    try {
      await api<Evaluation>(
        `/evaluations/${evaluation.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            final_score: finalScore,
            reason,
            review_required: finalScore !== evaluation.score || evaluation.review_required,
          }),
        },
        session.token,
      );
      const fresh = await api<Submission>(`/submissions/${activeSubmission.id}`, undefined, session.token);
      setActiveSubmission(fresh);
      if (activeExam) await loadSubmissions(activeExam.id, session.token);
      setNotice("Teacher review saved.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Save failed");
    } finally {
      setBusy("");
    }
  }

  async function approveSubmission() {
    if (!session || !activeSubmission) return;
    setBusy("approve");
    setNotice("");
    try {
      await Promise.all(
        activeSubmission.evaluations.map((evaluation) =>
          api<Evaluation>(
            `/evaluations/${evaluation.id}`,
            {
              method: "PATCH",
              body: JSON.stringify({
                final_score: evaluation.final_score,
                reason: evaluation.reason,
                review_required: false,
              }),
            },
            session.token,
          ),
        ),
      );
      const fresh = await api<Submission>(`/submissions/${activeSubmission.id}`, undefined, session.token);
      setActiveSubmission(fresh);
      if (activeExam) await loadSubmissions(activeExam.id, session.token);
      setNotice("Result approved for student portal and report export.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Approval failed");
    } finally {
      setBusy("");
    }
  }

  async function rerunEvaluation() {
    if (!session || !activeSubmission) return;
    setBusy("rerun");
    setNotice("");
    try {
      await api<unknown>(`/submissions/${activeSubmission.id}/evaluate`, { method: "POST" }, session.token);
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const fresh = await api<Submission>(`/submissions/${activeSubmission.id}`, undefined, session.token);
        setActiveSubmission(fresh);
        if (fresh.status !== "running") break;
      }
      if (activeExam) await loadSubmissions(activeExam.id, session.token);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not rerun evaluation");
    } finally {
      setBusy("");
    }
  }

  async function downloadReport(submissionId: string, token = session?.token) {
    if (!token) return;
    setBusy(`report-${submissionId}`);
    setNotice("");
    try {
      const response = await fetch(`${API_URL}/submissions/${submissionId}/report`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Report export failed");
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => window.URL.revokeObjectURL(url), 30_000);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Report export failed");
    } finally {
      setBusy("");
    }
  }

  async function changeStudentPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setBusy("password");
    setNotice("");
    try {
      const payload = await api<AuthSession>(
        "/auth/student/change-password",
        {
          method: "POST",
          body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
        },
        session.token,
      );
      persistSession(payload);
      setCurrentPassword("");
      setNewPassword("");
      await refreshStudentData(payload.token);
      setNotice("Password changed.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Password change failed");
    } finally {
      setBusy("");
    }
  }

  if (!session) {
    return (
      <Landing
        busy={busy === "login"}
        health={health}
        loginIdentifier={loginIdentifier}
        loginPassword={loginPassword}
        loginRole={loginRole}
        notice={notice}
        onLogin={login}
        setLoginIdentifier={setLoginIdentifier}
        setLoginPassword={setLoginPassword}
        setLoginRole={setLoginRole}
      />
    );
  }

  if (session.role === "student") {
    return (
      <StudentWorkspace
        activeSubmission={activeStudentSubmission}
        busy={busy}
        currentPassword={currentPassword}
        health={health}
        newPassword={newPassword}
        notice={notice}
        onChangePassword={changeStudentPassword}
        onDownloadReport={(submissionId) => downloadReport(submissionId, session.token)}
        onLogout={logout}
        onRefresh={() => refreshStudentData(session.token)}
        portal={studentPortal}
        session={session}
        setActiveSubmissionId={setActiveStudentSubmissionId}
        setCurrentPassword={setCurrentPassword}
        setNewPassword={setNewPassword}
      />
    );
  }

  return (
    <TeacherWorkspace
      activeExam={activeExam}
      activeExamId={activeExamId}
      activeSubmission={activeSubmission}
      analytics={analytics}
      answerFiles={answerFiles}
      busy={busy}
      draftQuestion={draftQuestion}
      exams={exams}
      health={health}
      manualInstructions={manualInstructions}
      manualQuestions={manualQuestions}
      manualSubject={manualSubject}
      manualTitle={manualTitle}
      notice={notice}
      onAddManualQuestion={addManualQuestion}
      onAddQueueEntry={addQueueEntry}
      onApproveSubmission={approveSubmission}
      onCreateManualExam={createManualExam}
      onDownloadReport={(submissionId) => downloadReport(submissionId, session.token)}
      onEvaluateQueue={evaluateQueue}
      onExtractSchema={extractSchema}
      onLogout={logout}
      onRefresh={() => refreshTeacherData(session.token)}
      onRerunEvaluation={rerunEvaluation}
      onSaveEvaluation={saveEvaluation}
      queue={queue}
      schemaFile={schemaFile}
      schemaMarks={schemaMarks}
      schemaSubject={schemaSubject}
      schemaTitle={schemaTitle}
      setActiveExamId={setActiveExamId}
      setActiveSubmission={setActiveSubmission}
      setAnswerFiles={setAnswerFiles}
      setDraftQuestion={setDraftQuestion}
      setManualInstructions={setManualInstructions}
      setManualQuestions={setManualQuestions}
      setManualSubject={setManualSubject}
      setManualTitle={setManualTitle}
      setSchemaFile={setSchemaFile}
      setSchemaMarks={setSchemaMarks}
      setSchemaSubject={setSchemaSubject}
      setSchemaTitle={setSchemaTitle}
      setStudentName={setStudentName}
      setTeacherView={setTeacherView}
      setUsn={setUsn}
      studentName={studentName}
      submissions={submissions}
      teacherView={teacherView}
      usn={usn}
    />
  );
}

function Landing({
  busy,
  health,
  loginIdentifier,
  loginPassword,
  loginRole,
  notice,
  onLogin,
  setLoginIdentifier,
  setLoginPassword,
  setLoginRole,
}: {
  busy: boolean;
  health: Health | null;
  loginIdentifier: string;
  loginPassword: string;
  loginRole: Role;
  notice: string;
  onLogin: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  setLoginIdentifier: (value: string) => void;
  setLoginPassword: (value: string) => void;
  setLoginRole: (value: Role) => void;
}) {
  return (
    <main className="min-h-screen bg-page text-ink">
      <section className="hero-shell">
        <div className="hero-media" />
        <div className="hero-shade" />
        <header className="hero-nav">
          <img alt="BMSIT&M logo" className="h-14 w-auto bg-white/95 p-2" src="/brand/bmsit-logo.svg" />
          <div className="hidden items-center gap-6 text-sm font-semibold text-white/80 md:flex">
            <span>AI evaluation</span>
            <span>Teacher review</span>
            <span>Student reports</span>
          </div>
        </header>

        <div className="hero-content">
          <p className="eyebrow text-white/80">BMS Institute of Technology & Management</p>
          <h1>AI-powered answer sheet evaluation for campus exams.</h1>
          <p className="max-w-2xl text-base font-medium leading-7 text-white/80 sm:text-lg">
            A role-based portal for teachers to build rubrics, evaluate handwritten answer sheets with GPT vision, review marks, export PDF reports, and publish results to students by USN.
          </p>
        </div>

        <div className="access-dock">
          <div className="dock-copy">
            <p className="eyebrow">Secure access</p>
            <h2>Teacher and student portals share one real evaluation workflow.</h2>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className={health?.openai_configured ? "status-pill status-good" : "status-pill status-warn"}>
                {health?.openai_configured ? "OpenAI ready" : "OpenAI key needed"}
              </span>
              <span className="status-pill status-info">{health?.model ?? "API"}</span>
            </div>
          </div>
          <form className="login-flow" onSubmit={onLogin}>
            <div className="segmented">
              <button
                className={loginRole === "teacher" ? "active" : ""}
                onClick={() => setLoginRole("teacher")}
                type="button"
              >
                <UserRound size={16} />
                Teacher
              </button>
              <button
                className={loginRole === "student" ? "active" : ""}
                onClick={() => setLoginRole("student")}
                type="button"
              >
                <GraduationCap size={16} />
                Student
              </button>
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
              <label>
                <span className="label">{loginRole === "teacher" ? "Email" : "USN"}</span>
                <input
                  className="field"
                  onChange={(event) => setLoginIdentifier(event.target.value)}
                  placeholder={loginRole === "teacher" ? "teacher@bmsit.ac.in" : "1BM22CS101"}
                  required
                  value={loginIdentifier}
                />
              </label>
              <label>
                <span className="label">Password</span>
                <input
                  className="field"
                  onChange={(event) => setLoginPassword(event.target.value)}
                  required
                  type="password"
                  value={loginPassword}
                />
              </label>
              <button className="btn-primary self-end" disabled={busy} type="submit">
                {busy ? <Loader2 className="animate-spin" size={16} /> : <LockKeyhole size={16} />}
                Login
              </button>
            </div>
            {loginRole === "student" ? (
              <p className="text-xs font-semibold text-slate-500">First student login uses USN as the password.</p>
            ) : null}
            {notice ? <Notice text={notice} /> : null}
          </form>
        </div>
      </section>

      <section className="campus-strip">
        <div>
          <p className="eyebrow">Official BMSIT&M context</p>
          <h2>A college-branded workflow built around actual exam operations.</h2>
        </div>
        <div className="campus-facts">
          <Fact label="Accreditations" value="NAAC A, AICTE, NBA" />
          <Fact label="Campus" value="21+ acres, Yelahanka" />
          <Fact label="Focus" value="Engineering, research, placements" />
        </div>
      </section>
    </main>
  );
}

function TeacherWorkspace(props: {
  activeExam: Exam | null;
  activeExamId: string;
  activeSubmission: Submission | null;
  analytics: ReturnType<typeof computeAnalytics>;
  answerFiles: File[];
  busy: string;
  draftQuestion: DraftQuestion;
  exams: Exam[];
  health: Health | null;
  manualInstructions: string;
  manualQuestions: DraftQuestion[];
  manualSubject: string;
  manualTitle: string;
  notice: string;
  onAddManualQuestion: () => void;
  onAddQueueEntry: () => void;
  onApproveSubmission: () => Promise<void>;
  onCreateManualExam: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  onDownloadReport: (submissionId: string) => void;
  onEvaluateQueue: () => Promise<void>;
  onExtractSchema: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  onLogout: () => void;
  onRefresh: () => void;
  onRerunEvaluation: () => Promise<void>;
  onSaveEvaluation: (evaluation: Evaluation, finalScore: number, reason: string) => Promise<void>;
  queue: QueueEntry[];
  schemaFile: File | null;
  schemaMarks: number;
  schemaSubject: string;
  schemaTitle: string;
  setActiveExamId: (value: string) => void;
  setActiveSubmission: (submission: Submission | null) => void;
  setAnswerFiles: (files: File[]) => void;
  setDraftQuestion: (value: DraftQuestion | ((current: DraftQuestion) => DraftQuestion)) => void;
  setManualInstructions: (value: string) => void;
  setManualQuestions: (value: DraftQuestion[] | ((current: DraftQuestion[]) => DraftQuestion[])) => void;
  setManualSubject: (value: string) => void;
  setManualTitle: (value: string) => void;
  setSchemaFile: (file: File | null) => void;
  setSchemaMarks: (value: number) => void;
  setSchemaSubject: (value: string) => void;
  setSchemaTitle: (value: string) => void;
  setStudentName: (value: string) => void;
  setTeacherView: (value: TeacherView) => void;
  setUsn: (value: string) => void;
  studentName: string;
  submissions: Submission[];
  teacherView: TeacherView;
  usn: string;
}) {
  return (
    <main className="min-h-screen bg-page text-ink">
      <AppHeader
        health={props.health}
        mode="Teacher"
        onLogout={props.onLogout}
        onRefresh={props.onRefresh}
        subtitle="Rubrics, GPT vision evaluation, teacher review, analytics"
      />

      <div className="workspace">
        {props.notice ? <Notice text={props.notice} /> : null}

        <nav className="tabline">
          <button
            className={props.teacherView === "evaluate" ? "active" : ""}
            onClick={() => props.setTeacherView("evaluate")}
            type="button"
          >
            <Wand2 size={16} />
            Evaluate
          </button>
          <button
            className={props.teacherView === "review" ? "active" : ""}
            onClick={() => props.setTeacherView("review")}
            type="button"
          >
            <ClipboardCheck size={16} />
            Review
          </button>
          <button
            className={props.teacherView === "analytics" ? "active" : ""}
            onClick={() => props.setTeacherView("analytics")}
            type="button"
          >
            <BarChart3 size={16} />
            Analytics
          </button>
        </nav>

        {props.teacherView === "evaluate" ? (
          <TeacherEvaluate {...props} />
        ) : props.teacherView === "review" ? (
          <TeacherReview {...props} />
        ) : (
          <TeacherAnalytics analytics={props.analytics} submissions={props.submissions} />
        )}
      </div>
    </main>
  );
}

function TeacherEvaluate(props: Parameters<typeof TeacherWorkspace>[0]) {
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.72fr)]">
      <section className="workspace-section">
        <div className="section-head">
          <div>
            <p className="eyebrow">Exam setup</p>
            <h2>Create a rubric from an answer scheme or enter it manually.</h2>
          </div>
        </div>

        <div className="grid gap-5 lg:grid-cols-2">
          <form className="flow-panel" onSubmit={props.onExtractSchema}>
            <div className="split-head">
              <h3>Extract answer scheme</h3>
              <button className="btn-primary" disabled={!props.schemaFile || props.busy === "schema"} type="submit">
                {props.busy === "schema" ? <Loader2 className="animate-spin" size={16} /> : <SearchCheck size={16} />}
                Extract
              </button>
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
              <label>
                <span className="label">Subject</span>
                <input
                  className="field"
                  onChange={(event) => props.setSchemaSubject(event.target.value)}
                  value={props.schemaSubject}
                />
              </label>
              <label>
                <span className="label">Marks</span>
                <input
                  className="field"
                  min={0.5}
                  onChange={(event) => props.setSchemaMarks(Number(event.target.value))}
                  step={0.5}
                  type="number"
                  value={props.schemaMarks}
                />
              </label>
            </div>
            <label>
              <span className="label">Exam name</span>
              <input
                className="field"
                onChange={(event) => props.setSchemaTitle(event.target.value)}
                value={props.schemaTitle}
              />
            </label>
            <UploadBox
              accept=".pdf,.png,.jpg,.jpeg,.webp"
              icon={<Upload size={22} />}
              label={props.schemaFile ? props.schemaFile.name : "Upload teacher answer scheme"}
              onChange={(files) => props.setSchemaFile(files[0] ?? null)}
            />
          </form>

          <form className="flow-panel" onSubmit={props.onCreateManualExam}>
            <div className="split-head">
              <h3>Manual rubric</h3>
              <button
                className="btn-primary"
                disabled={!props.manualQuestions.length || props.busy === "manual-exam"}
                type="submit"
              >
                {props.busy === "manual-exam" ? <Loader2 className="animate-spin" size={16} /> : <Plus size={16} />}
                Create
              </button>
            </div>
            <div className="grid gap-3">
              <label>
                <span className="label">Exam</span>
                <input
                  className="field"
                  onChange={(event) => props.setManualTitle(event.target.value)}
                  value={props.manualTitle}
                />
              </label>
              <label>
                <span className="label">Subject</span>
                <input
                  className="field"
                  onChange={(event) => props.setManualSubject(event.target.value)}
                  value={props.manualSubject}
                />
              </label>
            </div>
            <label>
              <span className="label">Instructions</span>
              <input
                className="field"
                onChange={(event) => props.setManualInstructions(event.target.value)}
                value={props.manualInstructions}
              />
            </label>
            <div className="rubric-builder">
              <div className="grid gap-3 sm:grid-cols-2">
                <input
                  className="field"
                  onChange={(event) => props.setDraftQuestion((current) => ({ ...current, id: event.target.value }))}
                  value={props.draftQuestion.id}
                />
                <input
                  className="field"
                  min={0.5}
                  onChange={(event) =>
                    props.setDraftQuestion((current) => ({ ...current, max_marks: Number(event.target.value) }))
                  }
                  step={0.5}
                  type="number"
                  value={props.draftQuestion.max_marks}
                />
              </div>
              <input
                className="field"
                onChange={(event) => props.setDraftQuestion((current) => ({ ...current, text: event.target.value }))}
                placeholder="Question text"
                value={props.draftQuestion.text}
              />
              <textarea
                className="field min-h-20"
                onChange={(event) => props.setDraftQuestion((current) => ({ ...current, model_answer: event.target.value }))}
                placeholder="Model answer or rubric"
                value={props.draftQuestion.model_answer}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <input
                  className="field"
                  onChange={(event) =>
                    props.setDraftQuestion((current) => ({ ...current, marking_rules: event.target.value }))
                  }
                  placeholder="Marking rules"
                  value={props.draftQuestion.marking_rules}
                />
                <input
                  className="field"
                  onChange={(event) =>
                    props.setDraftQuestion((current) => ({ ...current, keywordsText: event.target.value }))
                  }
                  placeholder="Keywords, comma separated"
                  value={props.draftQuestion.keywordsText}
                />
              </div>
              <button className="btn-secondary w-full" onClick={props.onAddManualQuestion} type="button">
                <Plus size={16} />
                Add question
              </button>
            </div>
            {props.manualQuestions.length ? (
              <div className="mini-list">
                {props.manualQuestions.map((question, index) => (
                  <button
                    className="mini-row"
                    key={`${question.id}-${index}`}
                    onClick={() =>
                      props.setManualQuestions((current) => current.filter((_, itemIndex) => itemIndex !== index))
                    }
                    type="button"
                  >
                    <span>{question.id}</span>
                    <strong>{formatNumber(question.max_marks)}</strong>
                    <small>Remove</small>
                  </button>
                ))}
              </div>
            ) : null}
          </form>
        </div>
      </section>

      <section className="workspace-section">
        <div className="section-head">
          <div>
            <p className="eyebrow">Student batch</p>
            <h2>Queue one or many answer sheets for the selected exam.</h2>
          </div>
          <button
            className="btn-primary"
            disabled={!props.activeExam || !props.queue.some((entry) => entry.status === "queued" || entry.status === "failed") || props.busy === "queue"}
            onClick={props.onEvaluateQueue}
            type="button"
          >
            {props.busy === "queue" ? <Loader2 className="animate-spin" size={16} /> : <Wand2 size={16} />}
            Run queue
          </button>
        </div>

        <label>
          <span className="label">Selected exam</span>
          <select
            className="field"
            onChange={(event) => props.setActiveExamId(event.target.value)}
            value={props.activeExamId}
          >
            <option value="">Select exam</option>
            {props.exams.map((exam) => (
              <option key={exam.id} value={exam.id}>
                {exam.title} - {exam.subject} - {formatNumber(exam.total_marks)} marks
              </option>
            ))}
          </select>
        </label>

        <div className="grid gap-3 sm:grid-cols-2">
          <label>
            <span className="label">Student name</span>
            <input className="field" onChange={(event) => props.setStudentName(event.target.value)} value={props.studentName} />
          </label>
          <label>
            <span className="label">USN</span>
            <input className="field uppercase" onChange={(event) => props.setUsn(event.target.value)} value={props.usn} />
          </label>
        </div>
        <UploadBox
          accept=".pdf,.png,.jpg,.jpeg,.webp"
          icon={<FileText size={22} />}
          label={
            props.answerFiles.length
              ? `${props.answerFiles.length} answer file${props.answerFiles.length === 1 ? "" : "s"} selected`
              : "Upload answer sheet pages"
          }
          multiple
          onChange={props.setAnswerFiles}
        />
        <button className="btn-secondary w-full" onClick={props.onAddQueueEntry} type="button">
          <Layers3 size={16} />
          Add to batch queue
        </button>

        <div className="queue-list">
          {props.queue.length ? (
            props.queue.map((entry) => (
              <div className="queue-row" key={entry.id}>
                <div>
                  <strong>{entry.studentName}</strong>
                  <span>
                    {entry.usn} · {entry.files.length} file{entry.files.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="text-right">
                  <span className={statusClass(entry.status)}>{statusLabel(entry.status)}</span>
                  <p>{entry.message}</p>
                </div>
              </div>
            ))
          ) : (
            <EmptyState text="No students queued yet." />
          )}
        </div>
      </section>
    </div>
  );
}

function TeacherReview(props: Parameters<typeof TeacherWorkspace>[0]) {
  return (
    <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
      <aside className="workspace-section">
        <div className="section-head">
          <div>
            <p className="eyebrow">Submissions</p>
            <h2>{props.activeExam ? props.activeExam.title : "Select an exam"}</h2>
          </div>
        </div>
        <div className="submission-list">
          {props.submissions.length ? (
            props.submissions.map((submission) => (
              <button
                className={props.activeSubmission?.id === submission.id ? "submission-row active" : "submission-row"}
                key={submission.id}
                onClick={() => props.setActiveSubmission(submission)}
                type="button"
              >
                <span>
                  <strong>{submission.student_name}</strong>
                  <small>{submission.usn || "No USN"}</small>
                </span>
                <span className={statusClass(submission.status)}>{statusLabel(submission.status)}</span>
              </button>
            ))
          ) : (
            <EmptyState text="No submissions for this exam." />
          )}
        </div>
      </aside>

      <section className="workspace-section">
        {props.activeSubmission ? (
          <>
            <div className="review-head">
              <div>
                <p className="eyebrow">Teacher review</p>
                <h2>
                  {props.activeSubmission.student_name} · {props.activeSubmission.usn}
                </h2>
                <p className="text-sm font-medium text-slate-500">
                  {props.activeSubmission.overall_feedback || "Evaluation feedback appears after completion."}
                </p>
              </div>
              <div className="review-actions">
                <span className={statusClass(props.activeSubmission.status)}>{statusLabel(props.activeSubmission.status)}</span>
                {props.activeSubmission.status === "completed" ? (
                  <>
                    <button className="btn-secondary" onClick={props.onApproveSubmission} type="button">
                      <ShieldCheck size={16} />
                      Approve
                    </button>
                    <button
                      className="btn-secondary"
                      onClick={() => props.onDownloadReport(props.activeSubmission!.id)}
                      type="button"
                    >
                      <Download size={16} />
                      PDF
                    </button>
                  </>
                ) : null}
                <button className="btn-secondary" onClick={props.onRerunEvaluation} type="button">
                  <RefreshCcw size={16} />
                  Re-check
                </button>
              </div>
            </div>

            {props.activeSubmission.error ? <Notice tone="bad" text={props.activeSubmission.error} /> : null}

            <div className="score-band">
              <Fact label="Marks" value={`${formatNumber(props.activeSubmission.total_score)} / ${formatNumber(props.activeSubmission.total_marks)}`} />
              <Fact label="Score" value={`${scorePercent(props.activeSubmission)}%`} />
              <Fact label="Confidence" value={`${formatNumber(props.activeSubmission.average_confidence)}%`} />
              <Fact
                label="Review flags"
                value={String(props.activeSubmission.evaluations.filter((item) => item.review_required).length)}
              />
            </div>

            {props.activeSubmission.status === "completed" ? (
              <div className="evaluation-stack">
                {props.activeSubmission.evaluations.map((evaluation) => (
                  <EvaluationEditor
                    busy={props.busy === evaluation.id}
                    evaluation={evaluation}
                    key={evaluation.id}
                    onSave={props.onSaveEvaluation}
                  />
                ))}
              </div>
            ) : (
              <EmptyState text={props.activeSubmission.status === "running" ? "Evaluation is still running." : "Run evaluation to see review rows."} />
            )}
          </>
        ) : (
          <EmptyState text="Select a completed submission to review marks." />
        )}
      </section>
    </div>
  );
}

function TeacherAnalytics({
  analytics,
  submissions,
}: {
  analytics: ReturnType<typeof computeAnalytics>;
  submissions: Submission[];
}) {
  return (
    <section className="workspace-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Class analytics</p>
          <h2>Insights calculated from completed evaluations only.</h2>
        </div>
      </div>
      <div className="score-band">
        <Fact label="Completed" value={String(analytics.completed)} />
        <Fact label="Class average" value={`${analytics.classAverage}%`} />
        <Fact label="Pass percentage" value={`${analytics.passPercentage}%`} />
        <Fact label="Review flags" value={String(analytics.reviewFlags)} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="flow-panel">
          <h3>Difficult questions</h3>
          {analytics.difficultQuestions.length ? (
            <div className="mini-list">
              {analytics.difficultQuestions.map((item) => (
                <div className="mini-row" key={item.questionId}>
                  <span>{item.questionId}</span>
                  <strong>{item.average}% avg</strong>
                  <small>{item.attempts} attempts</small>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState text="No completed question data yet." />
          )}
        </div>
        <div className="flow-panel">
          <h3>Weak topics</h3>
          {analytics.weakAreas.length ? (
            <div className="mini-list">
              {analytics.weakAreas.map((item) => (
                <div className="mini-row" key={item.label}>
                  <span>{item.label}</span>
                  <strong>{item.count}</strong>
                  <small>mentions</small>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState text="Weak areas appear after AI evaluation." />
          )}
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>USN</th>
              <th>Status</th>
              <th>Marks</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {submissions.map((submission) => (
              <tr key={submission.id}>
                <td>{submission.student_name}</td>
                <td>{submission.usn}</td>
                <td>
                  <span className={statusClass(submission.status)}>{statusLabel(submission.status)}</span>
                </td>
                <td>
                  {formatNumber(submission.total_score)} / {formatNumber(submission.total_marks)}
                </td>
                <td>{formatNumber(submission.average_confidence)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StudentWorkspace({
  activeSubmission,
  busy,
  currentPassword,
  health,
  newPassword,
  notice,
  onChangePassword,
  onDownloadReport,
  onLogout,
  onRefresh,
  portal,
  session,
  setActiveSubmissionId,
  setCurrentPassword,
  setNewPassword,
}: {
  activeSubmission: StudentPortal["submissions"][number] | null;
  busy: string;
  currentPassword: string;
  health: Health | null;
  newPassword: string;
  notice: string;
  onChangePassword: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  onDownloadReport: (submissionId: string) => void;
  onLogout: () => void;
  onRefresh: () => void;
  portal: StudentPortal | null;
  session: AuthSession;
  setActiveSubmissionId: (value: string) => void;
  setCurrentPassword: (value: string) => void;
  setNewPassword: (value: string) => void;
}) {
  const mustChangePassword = session.force_password_change || portal?.force_password_change;

  return (
    <main className="min-h-screen bg-page text-ink">
      <AppHeader
        health={health}
        mode="Student"
        onLogout={onLogout}
        onRefresh={onRefresh}
        subtitle={`${portal?.student_name ?? session.display_name} · ${portal?.usn ?? session.identifier}`}
      />
      <div className="workspace">
        {notice ? <Notice text={notice} /> : null}
        {mustChangePassword ? (
          <section className="workspace-section max-w-2xl">
            <div className="section-head">
              <div>
                <p className="eyebrow">First login</p>
                <h2>Change the default USN password before opening results.</h2>
              </div>
            </div>
            <form className="flow-panel" onSubmit={onChangePassword}>
              <label>
                <span className="label">Current password</span>
                <input
                  className="field"
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  required
                  type="password"
                  value={currentPassword}
                />
              </label>
              <label>
                <span className="label">New password</span>
                <input
                  className="field"
                  minLength={8}
                  onChange={(event) => setNewPassword(event.target.value)}
                  required
                  type="password"
                  value={newPassword}
                />
              </label>
              <button className="btn-primary" disabled={busy === "password"} type="submit">
                {busy === "password" ? <Loader2 className="animate-spin" size={16} /> : <ShieldCheck size={16} />}
                Save password
              </button>
            </form>
          </section>
        ) : (
          <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
            <aside className="workspace-section">
              <div className="section-head">
                <div>
                  <p className="eyebrow">My exams</p>
                  <h2>{portal?.submissions.length ?? 0} result{portal?.submissions.length === 1 ? "" : "s"}</h2>
                </div>
              </div>
              <div className="submission-list">
                {portal?.submissions.length ? (
                  portal.submissions.map((submission) => (
                    <button
                      className={activeSubmission?.id === submission.id ? "submission-row active" : "submission-row"}
                      key={submission.id}
                      onClick={() => setActiveSubmissionId(submission.id)}
                      type="button"
                    >
                      <span>
                        <strong>{submission.exam.title}</strong>
                        <small>{submission.exam.subject}</small>
                      </span>
                      <ChevronRight size={16} />
                    </button>
                  ))
                ) : (
                  <EmptyState text="No published results for this USN yet." />
                )}
              </div>
            </aside>

            <section className="workspace-section">
              {activeSubmission ? (
                <>
                  <div className="review-head">
                    <div>
                      <p className="eyebrow">Result card</p>
                      <h2>{activeSubmission.exam.title}</h2>
                      <p className="text-sm font-medium text-slate-500">{activeSubmission.overall_feedback}</p>
                    </div>
                    {activeSubmission.status === "completed" ? (
                      <button className="btn-primary" onClick={() => onDownloadReport(activeSubmission.id)} type="button">
                        <Download size={16} />
                        Download PDF
                      </button>
                    ) : (
                      <span className={statusClass(activeSubmission.status)}>{statusLabel(activeSubmission.status)}</span>
                    )}
                  </div>

                  <div className="score-band">
                    <Fact label="Marks" value={`${formatNumber(activeSubmission.total_score)} / ${formatNumber(activeSubmission.total_marks)}`} />
                    <Fact label="Score" value={`${scorePercent(activeSubmission)}%`} />
                    <Fact label="Confidence" value={`${formatNumber(activeSubmission.average_confidence)}%`} />
                    <Fact label="Weak areas" value={String(activeSubmission.weak_areas.length)} />
                  </div>

                  <div className="evaluation-stack">
                    {activeSubmission.evaluations.map((evaluation) => (
                      <article className="evaluation-card" key={evaluation.id}>
                        <div className="evaluation-top">
                          <div>
                            <p className="eyebrow">{evaluation.question_id}</p>
                            <h3>{evaluation.question_text}</h3>
                          </div>
                          <span className={evaluation.review_required ? "status-pill status-warn" : "status-pill status-good"}>
                            {formatNumber(evaluation.final_score)} / {formatNumber(evaluation.max_marks)}
                          </span>
                        </div>
                        <p>{evaluation.reason}</p>
                        {evaluation.missing_points.length ? (
                          <div className="tagline">
                            {evaluation.missing_points.map((point) => (
                              <span key={point}>{point}</span>
                            ))}
                          </div>
                        ) : null}
                      </article>
                    ))}
                  </div>
                </>
              ) : (
                <EmptyState text="Select a result to view marks and feedback." />
              )}
            </section>
          </div>
        )}
      </div>
    </main>
  );
}

function AppHeader({
  health,
  mode,
  onLogout,
  onRefresh,
  subtitle,
}: {
  health: Health | null;
  mode: string;
  onLogout: () => void;
  onRefresh: () => void;
  subtitle: string;
}) {
  return (
    <header className="app-header">
      <div className="brand-lockup">
        <img alt="BMSIT&M logo" src="/brand/bmsit-logo.svg" />
        <div>
          <p className="eyebrow">{mode} portal</p>
          <h1>BmsitAi</h1>
          <span>{subtitle}</span>
        </div>
      </div>
      <div className="header-actions">
        <span className={health?.openai_configured ? "status-pill status-good" : "status-pill status-warn"}>
          {health?.openai_configured ? "OpenAI ready" : "OpenAI key needed"}
        </span>
        <button className="btn-secondary" onClick={onRefresh} type="button">
          <RefreshCcw size={16} />
          Refresh
        </button>
        <button className="btn-secondary" onClick={onLogout} type="button">
          <LogOut size={16} />
          Logout
        </button>
      </div>
    </header>
  );
}

function UploadBox({
  accept,
  icon,
  label,
  multiple = false,
  onChange,
}: {
  accept: string;
  icon: ReactNode;
  label: string;
  multiple?: boolean;
  onChange: (files: File[]) => void;
}) {
  return (
    <label className="upload-box">
      {icon}
      <span>{label}</span>
      <input
        className="sr-only"
        multiple={multiple}
        onChange={(event) => onChange(Array.from(event.target.files ?? []))}
        type="file"
        accept={accept}
      />
    </label>
  );
}

function EvaluationEditor({
  busy,
  evaluation,
  onSave,
}: {
  busy: boolean;
  evaluation: Evaluation;
  onSave: (evaluation: Evaluation, finalScore: number, reason: string) => Promise<void>;
}) {
  const [score, setScore] = useState(evaluation.final_score);
  const [reason, setReason] = useState(evaluation.reason);

  useEffect(() => {
    setScore(evaluation.final_score);
    setReason(evaluation.reason);
  }, [evaluation.final_score, evaluation.reason]);

  return (
    <article className="evaluation-card">
      <div className="evaluation-top">
        <div>
          <p className="eyebrow">{evaluation.question_id}</p>
          <h3>{evaluation.question_text}</h3>
        </div>
        <span className={evaluation.review_required ? "status-pill status-warn" : "status-pill status-good"}>
          {evaluation.review_required ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
          {formatNumber(evaluation.confidence)}%
        </span>
      </div>
      <div className="grid gap-3 lg:grid-cols-[160px_minmax(0,1fr)_auto]">
        <label>
          <span className="label">Final marks</span>
          <input
            className="field"
            max={evaluation.max_marks}
            min={0}
            onChange={(event) => setScore(Number(event.target.value))}
            step={0.5}
            type="number"
            value={score}
          />
        </label>
        <label>
          <span className="label">Teacher comment</span>
          <input className="field" onChange={(event) => setReason(event.target.value)} value={reason} />
        </label>
        <button className="btn-primary self-end" disabled={busy} onClick={() => onSave(evaluation, score, reason)} type="button">
          {busy ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
          Save
        </button>
      </div>
      <p>{evaluation.answer_text || "No extracted answer text returned."}</p>
      {evaluation.missing_points.length ? (
        <div className="tagline">
          {evaluation.missing_points.map((point) => (
            <span key={point}>{point}</span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function Notice({ text, tone = "info" }: { text: string; tone?: "info" | "bad" }) {
  return (
    <div className={tone === "bad" ? "notice notice-bad" : "notice"}>
      {tone === "bad" ? <AlertTriangle size={16} /> : <BookOpenCheck size={16} />}
      <span>{text}</span>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <FileText size={18} />
      <span>{text}</span>
    </div>
  );
}

function computeAnalytics(submissions: Submission[]) {
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
