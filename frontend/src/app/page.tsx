"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileText,
  RefreshCcw,
  Save,
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
  openai_configured: boolean;
  model: string;
};

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

function formatNumber(value: number) {
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

function statusTone(status?: Submission["status"]) {
  if (status === "completed") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "failed") return "border-rose-200 bg-rose-50 text-rose-700";
  if (status === "running") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-sky-200 bg-sky-50 text-sky-700";
}

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [exams, setExams] = useState<Exam[]>([]);
  const [activeExamId, setActiveExamId] = useState("");
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [activeSubmission, setActiveSubmission] = useState<Submission | null>(null);

  const [schemaSubject, setSchemaSubject] = useState("Computer Science");
  const [schemaTitle, setSchemaTitle] = useState("Answer Schema");
  const [schemaMarks, setSchemaMarks] = useState(10);
  const [schemaFile, setSchemaFile] = useState<File | null>(null);

  const [usn, setUsn] = useState("");
  const [studentName, setStudentName] = useState("");
  const [answerFiles, setAnswerFiles] = useState<File[]>([]);

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
        if (current && payload.some((submission) => submission.id === current.id)) return current;
        return payload[0] ?? null;
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load students");
    }
  }

  function onAnswerFiles(event: ChangeEvent<HTMLInputElement>) {
    setAnswerFiles(Array.from(event.target.files ?? []));
  }

  async function extractSchema(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!schemaFile) return;
    setBusy("schema");
    setNotice("");
    try {
      const form = new FormData();
      form.append("subject", schemaSubject);
      form.append("title", schemaTitle);
      form.append("default_marks", String(schemaMarks));
      form.append("file", schemaFile);
      const exam = await api<Exam>("/schema/extract", { method: "POST", body: form });
      setExams((current) => [exam, ...current.filter((item) => item.id !== exam.id)]);
      setActiveExamId(exam.id);
      setActiveSubmission(null);
      setNotice("Schema ready");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Schema failed");
    } finally {
      setBusy("");
    }
  }

  async function uploadAndEvaluate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeExam || !answerFiles.length) return;
    setBusy("evaluate");
    setNotice("");
    try {
      const form = new FormData();
      form.append("student_name", studentName.trim() || usn.trim() || "Student");
      form.append("usn", usn.trim());
      answerFiles.forEach((file) => form.append("files", file));
      const created = await api<{ id: string }>(`/exams/${activeExam.id}/submissions`, {
        method: "POST",
        body: form,
      });
      await api<unknown>(`/submissions/${created.id}/evaluate`, { method: "POST" });
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const fresh = await api<Submission>(`/submissions/${created.id}`);
        setActiveSubmission(fresh);
        if (fresh.status !== "running") {
          await loadSubmissions(activeExam.id);
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
    if (!activeSubmission) return;
    setBusy(evaluation.id);
    setNotice("");
    try {
      await api<Evaluation>(`/evaluations/${evaluation.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          final_score: finalScore,
          review_required: finalScore !== evaluation.score || evaluation.review_required,
        }),
      });
      const fresh = await api<Submission>(`/submissions/${activeSubmission.id}`);
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
          <h1 className="text-3xl font-bold text-ink">BmsitAi</h1>
          <p className="text-sm text-slate-500">Schema image to marks</p>
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
            {health?.openai_configured ? "GPT ready" : "Add key"}
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

      <section className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="min-w-0 space-y-5">
          <form className="panel space-y-4" onSubmit={extractSchema}>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-lg font-bold text-ink">1. Schema Image</h2>
              <button className="btn-primary w-full sm:w-auto" disabled={!schemaFile || busy === "schema"} type="submit">
                <Wand2 size={16} />
                Extract
              </button>
            </div>

            <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_120px]">
              <label>
                <span className="label">Subject</span>
                <input
                  className="field"
                  value={schemaSubject}
                  onChange={(event) => setSchemaSubject(event.target.value)}
                />
              </label>
              <label>
                <span className="label">Marks</span>
                <input
                  className="field"
                  min={0.5}
                  step={0.5}
                  type="number"
                  value={schemaMarks}
                  onChange={(event) => setSchemaMarks(Number(event.target.value))}
                />
              </label>
            </div>

            <label>
              <span className="label">Name</span>
              <input
                className="field"
                value={schemaTitle}
                onChange={(event) => setSchemaTitle(event.target.value)}
              />
            </label>

            <label className="flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-sky-200 bg-skyglass px-4 py-5 text-center text-sm font-semibold text-sky-700">
              <Upload size={22} />
              {schemaFile ? schemaFile.name : "Upload answer schema"}
              <input
                className="sr-only"
                onChange={(event) => setSchemaFile(event.target.files?.[0] ?? null)}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp"
              />
            </label>
          </form>

          <form className="panel space-y-4" onSubmit={uploadAndEvaluate}>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-lg font-bold text-ink">2. Student Sheet</h2>
              <button
                className="btn-primary w-full sm:w-auto"
                disabled={!activeExam || !answerFiles.length || !usn.trim() || busy === "evaluate"}
                type="submit"
              >
                <Wand2 size={16} />
                Evaluate
              </button>
            </div>

            <label>
              <span className="label">Schema</span>
              <select
                className="field"
                value={activeExamId}
                onChange={(event) => setActiveExamId(event.target.value)}
              >
                <option value="">Select schema</option>
                {exams.map((exam) => (
                  <option key={exam.id} value={exam.id}>
                    {exam.title} - {formatNumber(exam.total_marks)}
                  </option>
                ))}
              </select>
            </label>

            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="label">USN</span>
                <input className="field" required value={usn} onChange={(event) => setUsn(event.target.value)} />
              </label>
              <label>
                <span className="label">Name</span>
                <input
                  className="field"
                  value={studentName}
                  onChange={(event) => setStudentName(event.target.value)}
                />
              </label>
            </div>

            <label className="flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-sky-200 bg-skyglass px-4 py-5 text-center text-sm font-semibold text-sky-700">
              <FileText size={22} />
              {answerFiles.length ? `${answerFiles.length} file${answerFiles.length > 1 ? "s" : ""}` : "Upload answer sheet"}
              <input className="sr-only" multiple onChange={onAnswerFiles} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" />
            </label>

            {activeSubmission ? (
              <div className={`rounded-md border px-3 py-2 text-sm font-semibold ${statusTone(activeSubmission.status)}`}>
                {activeSubmission.status}
              </div>
            ) : null}
          </form>
        </div>

        <div className="min-w-0 space-y-5">
          <section className="panel space-y-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-ink">Extracted Schema</h2>
              {activeExam ? (
                <span className="rounded-md bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-700">
                  {formatNumber(activeExam.total_marks)}
                </span>
              ) : null}
            </div>
            {activeExam ? (
              <div className="space-y-3">
                {activeExam.questions.map((question) => (
                  <div className="rounded-lg border border-sky-100 bg-skyglass p-3" key={question.id}>
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <h3 className="font-bold text-ink">{question.id}</h3>
                      <span className="text-sm font-semibold text-sky-700">
                        {formatNumber(question.max_marks)}
                      </span>
                    </div>
                    <p className="text-sm font-semibold text-slate-800">{question.text}</p>
                    <p className="mt-2 text-sm text-slate-600">{question.model_answer}</p>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState text="Upload schema first" />
            )}
          </section>

          <section className="panel space-y-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-lg font-bold text-ink">3. Result</h2>
              {activeSubmission?.status === "completed" ? (
                <div className="flex flex-wrap gap-2 text-sm font-semibold">
                  <span className="rounded-md bg-sky-50 px-3 py-2 text-sky-700">
                    {formatNumber(activeSubmission.total_score)} / {formatNumber(activeSubmission.total_marks)}
                  </span>
                  <span className="rounded-md bg-white px-3 py-2 text-slate-600">
                    {formatNumber(activeSubmission.average_confidence)}%
                  </span>
                  <button
                    className="btn-secondary h-9"
                    onClick={() => window.open(`${API_URL}/submissions/${activeSubmission.id}/report`, "_blank")}
                    type="button"
                  >
                    <Download size={15} />
                    PDF
                  </button>
                </div>
              ) : null}
            </div>

            {activeSubmission?.error ? (
              <div className="rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                {activeSubmission.error}
              </div>
            ) : null}

            {!activeSubmission ? (
              <EmptyState text="No result yet" />
            ) : activeSubmission.status !== "completed" ? (
              <EmptyState text={activeSubmission.status === "running" ? "Checking..." : "Ready"} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] border-separate border-spacing-0 text-left text-sm">
                  <thead>
                    <tr className="text-xs uppercase text-slate-500">
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
        </div>
      </section>
    </main>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex min-h-36 items-center justify-center rounded-lg border border-sky-100 bg-skyglass text-sm font-semibold text-sky-700">
      {text}
    </div>
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
            max={evaluation.max_marks}
            min={0}
            onChange={(event) => setScore(Number(event.target.value))}
            step={0.5}
            type="number"
            value={score}
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
      <td className="max-w-sm border-b border-sky-50 px-3 py-3 text-slate-600">
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
