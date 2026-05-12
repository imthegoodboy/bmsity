"use client";

import { Download, Loader2, ShieldCheck } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  EmptyState,
  Fact,
  LoadingScreen,
  Notice,
  PortalHeader,
  StatusPill,
  useRequiredSession,
} from "../../components/portal";
import { api, API_URL, AuthSession, formatNumber, saveSession, scorePercent, StudentPortal } from "../../lib/bmsitai";

export default function StudentPage() {
  const { session, setSession, health, ready, logout } = useRequiredSession("student");
  const [portal, setPortal] = useState<StudentPortal | null>(null);
  const [activeSubmissionId, setActiveSubmissionId] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const activeSubmission = useMemo(
    () => portal?.submissions.find((submission) => submission.id === activeSubmissionId) ?? portal?.submissions[0] ?? null,
    [activeSubmissionId, portal],
  );
  const sessionToken = session?.token;

  useEffect(() => {
    if (!sessionToken) return;
    void loadPortal(sessionToken);
  }, [sessionToken]);

  async function loadPortal(token: string) {
    try {
      const payload = await api<StudentPortal>("/students/me", undefined, token);
      setPortal(payload);
      setActiveSubmissionId((current) =>
        payload.submissions.some((submission) => submission.id === current) ? current : payload.submissions[0]?.id || "",
      );
      setSession((current) => {
        if (!current) return current;
        if (current.force_password_change === payload.force_password_change) return current;
        const next = { ...current, force_password_change: payload.force_password_change };
        saveSession(next);
        return next;
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load student portal");
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setBusy("password");
    setNotice("");
    try {
      const fresh = await api<AuthSession>(
        "/auth/student/change-password",
        {
          method: "POST",
          body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
        },
        session.token,
      );
      saveSession(fresh);
      setSession(fresh);
      setCurrentPassword("");
      setNewPassword("");
      await loadPortal(fresh.token);
      setNotice("Password changed.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Password change failed");
    } finally {
      setBusy("");
    }
  }

  async function downloadReport(submissionId: string) {
    if (!session) return;
    setBusy(`report-${submissionId}`);
    setNotice("");
    try {
      const response = await fetch(`${API_URL}/submissions/${submissionId}/report`, {
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

  const mustChangePassword = session.force_password_change || portal?.force_password_change;
  const attemptedEvaluations = activeSubmission?.evaluations.filter((item) => item.attempted) ?? [];

  return (
    <main className="min-h-screen">
      <PortalHeader
        health={health}
        mode="student"
        onLogout={logout}
        subtitle={`${portal?.student_name ?? session.display_name} - ${portal?.usn ?? session.identifier}`}
      />
      <div className="workspace">
        {notice ? <Notice text={notice} /> : null}

        {mustChangePassword ? (
          <section className="workspace-section max-w-2xl">
            <div className="section-head">
              <div>
                <p className="eyebrow">First login</p>
                <h2>Change your default USN password.</h2>
                <p className="text-sm font-medium text-slate-500">
                  After this, your published reports stay linked to your USN.
                </p>
              </div>
            </div>
            <form className="flow-panel border-0 shadow-none" onSubmit={changePassword}>
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
                  <p className="eyebrow">Published results</p>
                  <h2>{portal?.submissions.length ?? 0} report{portal?.submissions.length === 1 ? "" : "s"}</h2>
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
                      <StatusPill status={submission.status} />
                    </button>
                  ))
                ) : (
                  <EmptyState text="No published reports for this USN yet." />
                )}
              </div>
            </aside>

            <section className="workspace-section">
              {activeSubmission ? (
                <>
                  <div className="review-head">
                    <div>
                      <p className="eyebrow">Report card</p>
                      <h2>{activeSubmission.exam.title}</h2>
                      <p className="text-sm font-medium text-slate-500">{activeSubmission.overall_feedback}</p>
                    </div>
                    <button
                      className="btn-primary"
                      disabled={busy === `report-${activeSubmission.id}`}
                      onClick={() => downloadReport(activeSubmission.id)}
                      type="button"
                    >
                      {busy === `report-${activeSubmission.id}` ? <Loader2 className="animate-spin" size={16} /> : <Download size={16} />}
                      Download PDF
                    </button>
                  </div>
                  <div className="score-band">
                    <Fact
                      label="Marks"
                      value={`${formatNumber(activeSubmission.total_score)} / ${formatNumber(activeSubmission.total_marks)}`}
                    />
                    <Fact label="Score" value={`${scorePercent(activeSubmission)}%`} />
                    <Fact label="Confidence" value={`${formatNumber(activeSubmission.average_confidence)}%`} />
                    <Fact label="Attempted" value={String(attemptedEvaluations.length)} />
                  </div>
                  <div className="evaluation-stack">
                    {attemptedEvaluations.length ? (
                      attemptedEvaluations.map((evaluation) => (
                        <article className="evaluation-card" key={evaluation.id}>
                          <div className="evaluation-top">
                            <div>
                              <p className="eyebrow">{evaluation.question_id}</p>
                              <h3>{evaluation.question_text}</h3>
                            </div>
                            <span className="status-pill status-info">
                              {formatNumber(evaluation.final_score)} / {formatNumber(evaluation.max_marks)}
                            </span>
                          </div>
                          <div className="tagline">
                            <span>{evaluation.counts_toward_total ? "Counts in total" : "Extra attempted"}</span>
                            {evaluation.review_required ? <span>Teacher review advised</span> : null}
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
                      ))
                    ) : (
                      <EmptyState text="No attempted questions were detected in this report." />
                    )}
                  </div>
                </>
              ) : (
                <EmptyState text="Select a report to view feedback." />
              )}
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
