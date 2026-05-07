"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileText,
  Plus,
  RefreshCcw,
  Save,
  Trash2,
  Upload,
  Wand2,
} from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

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
  updated_at: string;
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
};

type Health = {
  status: string;
  openai_configured: boolean;
  model: string;
};

const blankQuestion = (index: number): Question => ({
  id: `Q${index}`,
  text: "",
  max_marks: 2,
  model_answer: "",
  marking_rules: "",
  keywords: [],
});

const initialExam = {
  title: "Internal Assessment",
  subject: "",
  instructions: "",
  total_marks: 0,
  questions: [blankQuestion(1)],
};

function statusTone(status?: Submission["status"]) {
  if (status === "completed") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "failed") return "border-rose-200 bg-rose-50 text-rose-700";
  if (status === "running") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-sky-200 bg-sky-50 text-sky-700";
}

function formatNumber(value: number) {
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init.headers
        : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Request failed");
  }
  return response.json();
}

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [exams, setExams] = useState<Exam[]>([]);
  const [activeExamId, setActiveExamId] = useState("");
  const [examForm, setExamForm] = useState(initialExam);
  const [studentName, setStudentName] = useState("");
  const [usn, setUsn] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [activeSubmission, setActiveSubmission] = useState<Submission | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");

  const activeExam = useMemo(
    () => exams.find((exam) => exam.id === activeExamId) ?? null,
    [activeExamId, exams],
  );

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    if (activeExamId) {
      void loadSubmissions(activeExamId);
    }
  }, [activeExamId]);

  async function refreshAll() {
    try {
      const [healthPayload, examPayload] = await Promise.all([
        api<Health>("/health"),
        api<Exam[]>("/exams"),
      ]);
      setHealth(healthPayload);
      setExams(examPayload);
      setActiveExamId((current) => current || examPayload[0]?.id || "");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "API unavailable");
    }
  }

  async function loadSubmissions(examId: string) {
    try {
      const payload = await api<Submission[]>(`/exams/${examId}/submissions`);
      setSubmissions(payload);
      setActiveSubmission((current) => {
        if (current && payload.some((item) => item.id === current.id)) return current;
        return payload[0] ?? null;
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load submissions");
    }
  }

  function updateQuestion(index: number, patch: Partial<Question>) {
    setExamForm((current) => ({
      ...current,
      questions: current.questions.map((question, itemIndex) =>
        itemIndex === index ? { ...question, ...patch } : question,
      ),
    }));
  }

  function addQuestion() {
    setExamForm((current) => ({
      ...current,
      questions: [...current.questions, blankQuestion(current.questions.length + 1)],
    }));
  }

  function removeQuestion(index: number) {
    setExamForm((current) => ({
      ...current,
      questions: current.questions.filter((_, itemIndex) => itemIndex !== index),
    }));
  }

  async function createExam(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("exam");
    setNotice("");
    try {
      const total = examForm.questions.reduce((sum, question) => sum + Number(question.max_marks || 0), 0);
      const payload = await api<Exam>("/exams", {
        method: "POST",
        body: JSON.stringify({ ...examForm, total_marks: total }),
      });
      setExams((current) => [payload, ...current]);
      setActiveExamId(payload.id);
      setNotice("Exam saved");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not save exam");
    } finally {
      setBusy("");
    }
  }

  function onFilesChange(event: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(event.target.files ?? []));
  }

  async function uploadSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeExam) return;
    setBusy("upload");
    setNotice("");
    try {
      const form = new FormData();
      form.append("student_name", studentName);
      form.append("usn", usn);
      files.forEach((file) => form.append("files", file));
      const created = await api<{ id: string }>(`/exams/${activeExam.id}/submissions`, {
        method: "POST",
        body: form,
      });
      const fresh = await api<Submission>(`/submissions/${created.id}`);
      setActiveSubmission(fresh);
      await loadSubmissions(activeExam.id);
      setNotice("Sheets uploaded");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setBusy("");
    }
  }

  async function startEvaluation() {
    if (!activeSubmission) return;
    setBusy("evaluate");
    setNotice("");
    try {
      await api(`/submissions/${activeSubmission.id}/evaluate`, { method: "POST" });
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const fresh = await api<Submission>(`/submissions/${activeSubmission.id}`);
        setActiveSubmission(fresh);
        if (fresh.status !== "running") {
          if (activeExamId) await loadSubmissions(activeExamId);
          break;
        }
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Evaluation failed");
    } finally {
      setBusy("");
    }
  }

  async function saveEvaluation(evaluation: Evaluation, finalScore: number) {
    setBusy(evaluation.id);
    setNotice("");
    try {
      await api<Evaluation>(`/evaluations/${evaluation.id}`, {
        method: "PATCH",
        body: JSON.stringify({ final_score: finalScore, review_required: finalScore !== evaluation.score }),
      });
      const fresh = await api<Submission>(`/submissions/${activeSubmission?.id}`);
      setActiveSubmission(fresh);
      setNotice("Saved");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Save failed");
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-3 border-b border-sky-100 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-normal text-ink">BmsitAi</h1>
          <p className="text-sm text-slate-500">Answer sheet evaluation</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-md border border-sky-100 bg-white px-3 py-2 text-xs font-semibold text-slate-600">
            {health?.model ?? "API"}
          </span>
          <span
            className={`rounded-md border px-3 py-2 text-xs font-semibold ${
              health?.openai_configured
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-amber-200 bg-amber-50 text-amber-700"
            }`}
          >
            {health?.openai_configured ? "GPT ready" : "Add API key"}
          </span>
          <button className="btn-secondary" onClick={refreshAll} type="button">
            <RefreshCcw size={16} />
            Refresh
          </button>
        </div>
      </header>

      {notice ? (
        <div className="rounded-md border border-sky-100 bg-white px-4 py-3 text-sm font-medium text-slate-700">
          {notice}
        </div>
      ) : null}

      <section className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        <form className="panel space-y-4" onSubmit={createExam}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-bold text-ink">Exam Setup</h2>
            <button className="btn-primary" disabled={busy === "exam"} type="submit">
              <Save size={16} />
              Save
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className="label">Title</span>
              <input
                className="field"
                value={examForm.title}
                onChange={(event) => setExamForm({ ...examForm, title: event.target.value })}
              />
            </label>
            <label>
              <span className="label">Subject</span>
              <input
                className="field"
                required
                value={examForm.subject}
                onChange={(event) => setExamForm({ ...examForm, subject: event.target.value })}
              />
            </label>
          </div>

          <label>
            <span className="label">Rules</span>
            <textarea
              className="field min-h-20"
              value={examForm.instructions}
              onChange={(event) => setExamForm({ ...examForm, instructions: event.target.value })}
            />
          </label>

          <div className="space-y-3">
            {examForm.questions.map((question, index) => (
              <div className="rounded-lg border border-sky-100 bg-skyglass p-3" key={`${question.id}-${index}`}>
                <div className="mb-3 flex items-center justify-between gap-2">
                  <input
                    className="field h-9 max-w-24 bg-white"
                    value={question.id}
                    onChange={(event) => updateQuestion(index, { id: event.target.value })}
                    aria-label="Question ID"
                  />
                  <input
                    className="field h-9 max-w-28 bg-white"
                    min={0.5}
                    step={0.5}
                    type="number"
                    value={question.max_marks}
                    onChange={(event) => updateQuestion(index, { max_marks: Number(event.target.value) })}
                    aria-label="Marks"
                  />
                  <button
                    className="btn-ghost h-9 px-2"
                    disabled={examForm.questions.length === 1}
                    onClick={() => removeQuestion(index)}
                    type="button"
                    title="Remove"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
                <div className="grid gap-3">
                  <textarea
                    className="field min-h-16 bg-white"
                    required
                    placeholder="Question"
                    value={question.text}
                    onChange={(event) => updateQuestion(index, { text: event.target.value })}
                  />
                  <textarea
                    className="field min-h-20 bg-white"
                    required
                    placeholder="Model answer"
                    value={question.model_answer}
                    onChange={(event) => updateQuestion(index, { model_answer: event.target.value })}
                  />
                  <input
                    className="field bg-white"
                    placeholder="Keywords"
                    value={question.keywords.join(", ")}
                    onChange={(event) =>
                      updateQuestion(index, {
                        keywords: event.target.value
                          .split(",")
                          .map((item) => item.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                  <input
                    className="field bg-white"
                    placeholder="Marking rule"
                    value={question.marking_rules}
                    onChange={(event) => updateQuestion(index, { marking_rules: event.target.value })}
                  />
                </div>
              </div>
            ))}
            <button className="btn-secondary w-full" onClick={addQuestion} type="button">
              <Plus size={16} />
              Add Question
            </button>
          </div>
        </form>

        <div className="space-y-5">
          <section className="panel space-y-4">
            <h2 className="text-lg font-bold text-ink">Upload</h2>
            <label>
              <span className="label">Exam</span>
              <select
                className="field"
                value={activeExamId}
                onChange={(event) => setActiveExamId(event.target.value)}
              >
                <option value="">Select exam</option>
                {exams.map((exam) => (
                  <option key={exam.id} value={exam.id}>
                    {exam.title} - {exam.subject}
                  </option>
                ))}
              </select>
            </label>

            <form className="space-y-3" onSubmit={uploadSubmission}>
              <div className="grid gap-3 sm:grid-cols-2">
                <label>
                  <span className="label">Student</span>
                  <input className="field" required value={studentName} onChange={(event) => setStudentName(event.target.value)} />
                </label>
                <label>
                  <span className="label">USN</span>
                  <input className="field" value={usn} onChange={(event) => setUsn(event.target.value)} />
                </label>
              </div>
              <label className="flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-sky-200 bg-skyglass px-4 py-5 text-center text-sm font-semibold text-sky-700">
                <Upload size={22} />
                {files.length ? `${files.length} file${files.length > 1 ? "s" : ""}` : "Choose PDF/images"}
                <input className="sr-only" multiple onChange={onFilesChange} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" />
              </label>
              <button className="btn-primary w-full" disabled={!activeExam || busy === "upload"} type="submit">
                <Upload size={16} />
                Upload Sheets
              </button>
            </form>
          </section>

          <section className="panel space-y-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-ink">Evaluate</h2>
              {activeSubmission ? (
                <span className={`rounded-md border px-3 py-1 text-xs font-semibold ${statusTone(activeSubmission.status)}`}>
                  {activeSubmission.status}
                </span>
              ) : null}
            </div>
            <select
              className="field"
              value={activeSubmission?.id ?? ""}
              onChange={async (event) => {
                const id = event.target.value;
                setActiveSubmission(id ? await api<Submission>(`/submissions/${id}`) : null);
              }}
            >
              <option value="">Select student</option>
              {submissions.map((submission) => (
                <option key={submission.id} value={submission.id}>
                  {submission.student_name} {submission.usn ? `- ${submission.usn}` : ""}
                </option>
              ))}
            </select>
            <div className="grid gap-3 sm:grid-cols-2">
              <button
                className="btn-primary"
                disabled={!activeSubmission || activeSubmission.status === "running" || busy === "evaluate"}
                onClick={startEvaluation}
                type="button"
              >
                <Wand2 size={16} />
                Run GPT
              </button>
              <button
                className="btn-secondary"
                disabled={!activeSubmission || activeSubmission.status !== "completed"}
                onClick={() => window.open(`${API_URL}/submissions/${activeSubmission?.id}/report`, "_blank")}
                type="button"
              >
                <Download size={16} />
                PDF
              </button>
            </div>
            {activeSubmission?.error ? (
              <div className="rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                {activeSubmission.error}
              </div>
            ) : null}
          </section>
        </div>
      </section>

      <section className="panel space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-lg font-bold text-ink">Results</h2>
          {activeSubmission?.status === "completed" ? (
            <div className="flex flex-wrap gap-2 text-sm font-semibold">
              <span className="rounded-md bg-sky-50 px-3 py-2 text-sky-700">
                {formatNumber(activeSubmission.total_score)} / {formatNumber(activeSubmission.total_marks)}
              </span>
              <span className="rounded-md bg-white px-3 py-2 text-slate-600">
                {formatNumber(activeSubmission.average_confidence)}%
              </span>
            </div>
          ) : null}
        </div>

        {!activeSubmission ? (
          <div className="flex min-h-40 items-center justify-center rounded-lg border border-sky-100 bg-skyglass text-sm font-semibold text-sky-700">
            <FileText className="mr-2" size={18} />
            No submission selected
          </div>
        ) : activeSubmission.status !== "completed" ? (
          <div className="flex min-h-40 items-center justify-center rounded-lg border border-sky-100 bg-skyglass text-sm font-semibold text-sky-700">
            {activeSubmission.status === "running" ? "Evaluating..." : "Run GPT to see marks"}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-separate border-spacing-0 text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-normal text-slate-500">
                  <th className="border-b border-sky-100 px-3 py-2">Q</th>
                  <th className="border-b border-sky-100 px-3 py-2">Marks</th>
                  <th className="border-b border-sky-100 px-3 py-2">Confidence</th>
                  <th className="border-b border-sky-100 px-3 py-2">Status</th>
                  <th className="border-b border-sky-100 px-3 py-2">Reason</th>
                  <th className="border-b border-sky-100 px-3 py-2">Save</th>
                </tr>
              </thead>
              <tbody>
                {activeSubmission.evaluations.map((evaluation) => (
                  <ResultRow
                    busy={busy === evaluation.id}
                    evaluation={evaluation}
                    key={evaluation.id}
                    onSave={saveEvaluation}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

function ResultRow({
  evaluation,
  busy,
  onSave,
}: {
  evaluation: Evaluation;
  busy: boolean;
  onSave: (evaluation: Evaluation, finalScore: number) => Promise<void>;
}) {
  const [score, setScore] = useState(evaluation.final_score);

  useEffect(() => {
    setScore(evaluation.final_score);
  }, [evaluation.final_score]);

  return (
    <tr className="align-top">
      <td className="border-b border-sky-50 px-3 py-3 font-bold text-sky-700">{evaluation.question_id}</td>
      <td className="border-b border-sky-50 px-3 py-3">
        <div className="flex items-center gap-2">
          <input
            className="field h-9 w-24"
            min={0}
            max={evaluation.max_marks}
            step={0.5}
            type="number"
            value={score}
            onChange={(event) => setScore(Number(event.target.value))}
          />
          <span className="text-xs font-semibold text-slate-500">/{formatNumber(evaluation.max_marks)}</span>
        </div>
      </td>
      <td className="border-b border-sky-50 px-3 py-3 font-semibold text-slate-700">
        {formatNumber(evaluation.confidence)}%
      </td>
      <td className="border-b border-sky-50 px-3 py-3">
        <span
          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold ${
            evaluation.review_required
              ? "border-amber-200 bg-amber-50 text-amber-700"
              : "border-emerald-200 bg-emerald-50 text-emerald-700"
          }`}
        >
          {evaluation.review_required ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
          {evaluation.review_required ? "Review" : "OK"}
        </span>
      </td>
      <td className="max-w-md border-b border-sky-50 px-3 py-3 text-slate-600">
        <p className="font-medium text-slate-700">{evaluation.reason}</p>
        {evaluation.missing_points.length ? (
          <p className="mt-1 text-xs text-slate-500">{evaluation.missing_points.join(", ")}</p>
        ) : null}
      </td>
      <td className="border-b border-sky-50 px-3 py-3">
        <button className="btn-secondary h-9 px-3" disabled={busy} onClick={() => onSave(evaluation, score)} type="button">
          <Save size={15} />
        </button>
      </td>
    </tr>
  );
}
