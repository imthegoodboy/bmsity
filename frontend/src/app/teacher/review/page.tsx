"use client";

import { Loader2, RefreshCcw, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  EmptyState,
  EvaluationEditor,
  Fact,
  LoadingScreen,
  Notice,
  PortalHeader,
  ReportButton,
  StatusPill,
  useRequiredSession,
} from "../../../components/portal";
import { api, API_URL, Evaluation, Exam, formatNumber, scorePercent, Submission } from "../../../lib/bmsitai";

export default function TeacherReviewPage() {
  const { session, health, ready, logout } = useRequiredSession("teacher");
  const [exams, setExams] = useState<Exam[]>([]);
  const [activeExamId, setActiveExamId] = useState("");
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [activeSubmissionId, setActiveSubmissionId] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const activeSubmission = useMemo(
    () => submissions.find((submission) => submission.id === activeSubmissionId) ?? submissions[0] ?? null,
    [activeSubmissionId, submissions],
  );

  useEffect(() => {
    if (!session) return;
    const token = session.token;
    async function load() {
      try {
        const payload = await api<Exam[]>("/exams", undefined, token);
        setExams(payload);
        setActiveExamId((current) => current || payload[0]?.id || "");
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "Could not load exams");
      }
    }
    void load();
  }, [session]);

  useEffect(() => {
    if (!session || !activeExamId) return;
    void loadSubmissions(activeExamId, session.token);
  }, [activeExamId, session]);

  async function loadSubmissions(examId: string, token: string) {
    try {
      const payload = await api<Submission[]>(`/exams/${examId}/submissions`, undefined, token);
      setSubmissions(payload);
      setActiveSubmissionId((current) => current || payload[0]?.id || "");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load submissions");
    }
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
      await loadSubmissions(activeSubmission.exam_id, session.token);
      setNotice("Saved. Publish when the final result is ready for the student.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Save failed");
    } finally {
      setBusy("");
    }
  }

  async function publishSubmission() {
    if (!session || !activeSubmission) return;
    setBusy("publish");
    setNotice("");
    try {
      const published = await api<Submission>(
        `/submissions/${activeSubmission.id}/publish`,
        { method: "POST" },
        session.token,
      );
      setSubmissions((current) => current.map((item) => (item.id === published.id ? published : item)));
      setNotice("Published. The student can now sign in by USN and download the PDF.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Publish failed");
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
        setSubmissions((current) => current.map((item) => (item.id === fresh.id ? fresh : item)));
        if (fresh.status !== "running") break;
      }
      setNotice("Re-check complete. Review again before publishing.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not rerun evaluation");
    } finally {
      setBusy("");
    }
  }

  async function downloadReport(submission: Submission) {
    if (!session) return;
    setBusy(`report-${submission.id}`);
    setNotice("");
    try {
      const response = await fetch(`${API_URL}/submissions/${submission.id}/report`, {
        headers: { Authorization: `Bearer ${session.token}` },
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Report export failed");
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => window.URL.revokeObjectURL(url), 30000);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Report export failed");
    } finally {
      setBusy("");
    }
  }

  if (!ready || !session) return <LoadingScreen />;

  return (
    <main className="min-h-screen">
      <PortalHeader health={health} mode="teacher" onLogout={logout} subtitle="Review, edit, and publish results" />
      <div className="workspace">
        {notice ? <Notice text={notice} /> : null}

        <section className="page-hero">
          <div>
            <p className="eyebrow">Step 3</p>
            <h2>Approve only the results you want students to see.</h2>
            <p>Students cannot log in or download PDFs until the teacher publishes the completed submission.</p>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="workspace-section">
            <label>
              <span className="label">Exam</span>
              <select className="field" onChange={(event) => setActiveExamId(event.target.value)} value={activeExamId}>
                <option value="">Select exam</option>
                {exams.map((exam) => (
                  <option key={exam.id} value={exam.id}>
                    {exam.title}
                  </option>
                ))}
              </select>
            </label>
            <div className="submission-list">
              {submissions.length ? (
                submissions.map((submission) => (
                  <button
                    className={activeSubmission?.id === submission.id ? "submission-row active" : "submission-row"}
                    key={submission.id}
                    onClick={() => setActiveSubmissionId(submission.id)}
                    type="button"
                  >
                    <span>
                      <strong>{submission.student_name}</strong>
                      <small>{submission.usn || "No USN"} {submission.published ? "- published" : "- not published"}</small>
                    </span>
                    <StatusPill status={submission.status} />
                  </button>
                ))
              ) : (
                <EmptyState text="No submissions for this exam." />
              )}
            </div>
          </aside>

          <section className="workspace-section">
            {activeSubmission ? (
              <>
                <div className="review-head">
                  <div>
                    <p className="eyebrow">Teacher review</p>
                    <h2>
                      {activeSubmission.student_name} - {activeSubmission.usn}
                    </h2>
                    <p className="text-sm font-medium text-slate-500">
                      {activeSubmission.overall_feedback || "Evaluation feedback appears after completion."}
                    </p>
                  </div>
                  <div className="review-actions">
                    <StatusPill status={activeSubmission.status} />
                    <span className={activeSubmission.published ? "status-pill status-good" : "status-pill status-info"}>
                      {activeSubmission.published ? "Published" : "Private"}
                    </span>
                    <button className="btn-secondary" disabled={busy === "rerun"} onClick={rerunEvaluation} type="button">
                      {busy === "rerun" ? <Loader2 className="animate-spin" size={16} /> : <RefreshCcw size={16} />}
                      Re-check
                    </button>
                    <button
                      className="btn-primary"
                      disabled={busy === "publish" || activeSubmission.status !== "completed"}
                      onClick={publishSubmission}
                      type="button"
                    >
                      {busy === "publish" ? <Loader2 className="animate-spin" size={16} /> : <ShieldCheck size={16} />}
                      Publish
                    </button>
                    {activeSubmission.status === "completed" ? (
                      <ReportButton
                        busy={busy === `report-${activeSubmission.id}`}
                        onClick={() => downloadReport(activeSubmission)}
                      />
                    ) : null}
                  </div>
                </div>

                {activeSubmission.error ? <Notice tone="bad" text={activeSubmission.error} /> : null}

                <div className="score-band">
                  <Fact
                    label="Marks"
                    value={`${formatNumber(activeSubmission.total_score)} / ${formatNumber(activeSubmission.total_marks)}`}
                  />
                  <Fact label="Score" value={`${scorePercent(activeSubmission)}%`} />
                  <Fact label="Confidence" value={`${formatNumber(activeSubmission.average_confidence)}%`} />
                  <Fact
                    label="Review flags"
                    value={String(activeSubmission.evaluations.filter((item) => item.review_required).length)}
                  />
                </div>

                {activeSubmission.status === "completed" ? (
                  <div className="evaluation-stack">
                    {activeSubmission.evaluations.map((evaluation) => (
                      <EvaluationEditor
                        busy={busy === evaluation.id}
                        evaluation={evaluation}
                        key={evaluation.id}
                        onSave={saveEvaluation}
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyState text="Run checking before review." />
                )}
              </>
            ) : (
              <EmptyState text="Select a submission to review." />
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
