"use client";

import { useEffect, useMemo, useState } from "react";
import {
  EmptyState,
  Fact,
  LoadingScreen,
  Notice,
  PortalHeader,
  StatusPill,
  useRequiredSession,
} from "../../../components/portal";
import { api, computeAnalytics, Exam, formatNumber, Submission } from "../../../lib/bmsitai";

export default function TeacherAnalyticsPage() {
  const { session, health, ready, logout } = useRequiredSession("teacher");
  const [exams, setExams] = useState<Exam[]>([]);
  const [activeExamId, setActiveExamId] = useState("");
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [notice, setNotice] = useState("");
  const analytics = useMemo(() => computeAnalytics(submissions), [submissions]);

  useEffect(() => {
    if (!session) return;
    const token = session.token;
    async function load() {
      try {
        const payload = await api<Exam[]>("/exams", undefined, token);
        setExams(payload);
        setActiveExamId((current) => (payload.some((exam) => exam.id === current) ? current : payload[0]?.id || ""));
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "Could not load exams");
      }
    }
    void load();
  }, [session]);

  useEffect(() => {
    if (!session || !activeExamId) return;
    const token = session.token;
    const examId = activeExamId;
    async function loadSubmissions() {
      try {
        setSubmissions(await api<Submission[]>(`/exams/${examId}/submissions`, undefined, token));
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "Could not load submissions");
      }
    }
    void loadSubmissions();
  }, [activeExamId, session]);

  if (!ready || !session) return <LoadingScreen />;

  return (
    <main className="min-h-screen">
      <PortalHeader health={health} mode="teacher" onLogout={logout} subtitle="Class performance from real results" />
      <div className="workspace">
        {notice ? <Notice text={notice} /> : null}

        <section className="page-hero">
          <div>
            <p className="eyebrow">Analytics</p>
            <h2>Simple class insights after evaluations are complete.</h2>
            <p>Analytics are calculated only from real completed submissions for the selected exam.</p>
          </div>
          <label className="min-w-72">
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
        </section>

        <div className="score-band">
          <Fact label="Completed" value={String(analytics.completed)} />
          <Fact label="Class average" value={`${analytics.classAverage}%`} />
          <Fact label="Pass percentage" value={`${analytics.passPercentage}%`} />
          <Fact label="Review flags" value={String(analytics.reviewFlags)} />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <section className="flow-panel">
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
          </section>
          <section className="flow-panel">
            <h3>Weak areas</h3>
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
          </section>
        </div>

        <section className="workspace-section">
          {submissions.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Student</th>
                    <th>USN</th>
                    <th>Status</th>
                    <th>Marks</th>
                    <th>Confidence</th>
                    <th>Published</th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.map((submission) => (
                    <tr key={submission.id}>
                      <td>{submission.student_name}</td>
                      <td>{submission.usn}</td>
                      <td><StatusPill status={submission.status} /></td>
                      <td>{formatNumber(submission.total_score)} / {formatNumber(submission.total_marks)}</td>
                      <td>{formatNumber(submission.average_confidence)}%</td>
                      <td>{submission.published ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState text="No submissions yet." />
          )}
        </section>
      </div>
    </main>
  );
}
