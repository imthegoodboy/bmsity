"use client";

import { BrainCircuit, FileText, Loader2, Play, UserPlus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  EmptyState,
  LoadingScreen,
  Notice,
  PortalHeader,
  StatusPill,
  UploadBox,
  useRequiredSession,
} from "../../../components/portal";
import { api, Exam, formatNumber, QueueEntry, Submission } from "../../../lib/bmsitai";

export default function TeacherCheckPage() {
  const { session, health, ready, logout } = useRequiredSession("teacher");
  const [exams, setExams] = useState<Exam[]>([]);
  const [activeExamId, setActiveExamId] = useState("");
  const [studentName, setStudentName] = useState("");
  const [usn, setUsn] = useState("");
  const [answerFiles, setAnswerFiles] = useState<File[]>([]);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const activeExam = useMemo(
    () => exams.find((exam) => exam.id === activeExamId) ?? null,
    [activeExamId, exams],
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

  function addStudent() {
    if (!activeExam || !studentName.trim() || !usn.trim() || !answerFiles.length) {
      setNotice("Select an exam, enter student details, and upload answer sheet pages.");
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
        message: "Agent waiting",
      },
    ]);
    setStudentName("");
    setUsn("");
    setAnswerFiles([]);
    setNotice("");
  }

  function updateQueue(id: string, patch: Partial<QueueEntry>) {
    setQueue((current) => current.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry)));
  }

  async function runAgents() {
    if (!session || !activeExam) return;
    const targets = queue.filter((entry) => entry.status === "queued" || entry.status === "failed");
    if (!targets.length) return;
    setBusy(true);
    setNotice("");

    for (const [index, entry] of targets.entries()) {
      try {
        updateQueue(entry.id, { status: "uploading", message: `Agent ${index + 1} uploading pages` });
        const form = new FormData();
        form.append("student_name", entry.studentName);
        form.append("usn", entry.usn);
        entry.files.forEach((file) => form.append("files", file));
        const created = await api<{ id: string }>(
          `/exams/${activeExam.id}/submissions`,
          { method: "POST", body: form },
          session.token,
        );

        updateQueue(entry.id, {
          status: "running",
          submissionId: created.id,
          message: `Agent ${index + 1} reading ${entry.files.length} page${entry.files.length === 1 ? "" : "s"}`,
        });
        await api<unknown>(`/submissions/${created.id}/evaluate`, { method: "POST" }, session.token);

        for (let attempt = 0; attempt < 120; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, 1500));
          const fresh = await api<Submission>(`/submissions/${created.id}`, undefined, session.token);
          if (fresh.status !== "running") {
            updateQueue(entry.id, {
              status: fresh.status === "completed" ? "completed" : "failed",
              message:
                fresh.status === "completed"
                  ? `${formatNumber(fresh.total_score)} / ${formatNumber(fresh.total_marks)} ready for review`
                  : fresh.error || "Evaluation failed",
            });
            break;
          }
        }
      } catch (error) {
        updateQueue(entry.id, {
          status: "failed",
          message: error instanceof Error ? error.message : "Evaluation failed",
        });
      }
    }

    setBusy(false);
  }

  if (!ready || !session) return <LoadingScreen />;

  return (
    <main className="min-h-screen">
      <PortalHeader health={health} mode="teacher" onLogout={logout} subtitle="Assign one AI agent per student" />
      <div className="workspace">
        {notice ? <Notice text={notice} /> : null}

        <section className="page-hero">
          <div>
            <p className="eyebrow">Step 2</p>
            <h2>Check answer sheets with a clear student queue.</h2>
            <p>Upload every page for a student, add them to the queue, and run checking. Seven or eight pages are fine.</p>
          </div>
          <Link className="btn-secondary" href="/teacher/review">
            Open Review
          </Link>
        </section>

        <div className="teacher-grid">
          <section className="flow-panel">
            <div className="split-head">
              <h3>Student answer sheet</h3>
              <button className="btn-secondary" onClick={addStudent} type="button">
                <UserPlus size={16} />
                Add student
              </button>
            </div>
            <label>
              <span className="label">Exam</span>
              <select className="field" onChange={(event) => setActiveExamId(event.target.value)} value={activeExamId}>
                <option value="">Select exam</option>
                {exams.map((exam) => (
                  <option key={exam.id} value={exam.id}>
                    {exam.title} - {exam.subject}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="label">Student name</span>
                <input className="field" onChange={(event) => setStudentName(event.target.value)} value={studentName} />
              </label>
              <label>
                <span className="label">USN</span>
                <input className="field uppercase" onChange={(event) => setUsn(event.target.value)} value={usn} />
              </label>
            </div>
            <UploadBox
              accept=".pdf,.png,.jpg,.jpeg,.webp"
              icon={<FileText size={22} />}
              label={
                answerFiles.length
                  ? `${answerFiles.length} answer sheet page${answerFiles.length === 1 ? "" : "s"} selected`
                  : "Upload answer sheet pages"
              }
              multiple
              onChange={setAnswerFiles}
            />
          </section>

          <section className="flow-panel">
            <div className="split-head">
              <h3>Agent queue</h3>
              <button
                className="btn-primary"
                disabled={busy || !queue.some((entry) => entry.status === "queued" || entry.status === "failed")}
                onClick={runAgents}
                type="button"
              >
                {busy ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />}
                Run agents
              </button>
            </div>
            {activeExam ? (
              <div className="agent-banner">
                <BrainCircuit size={18} />
                <span>
                  Selected: <strong>{activeExam.title}</strong> ({formatNumber(activeExam.total_marks)} marks)
                </span>
              </div>
            ) : null}
            <div className="queue-list">
              {queue.length ? (
                queue.map((entry, index) => (
                  <div className="queue-row" key={entry.id}>
                    <div>
                      <strong>Agent {index + 1}: {entry.studentName}</strong>
                      <span>
                        {entry.usn} - {entry.files.length} page{entry.files.length === 1 ? "" : "s"}
                      </span>
                    </div>
                    <div className="text-right">
                      <StatusPill status={entry.status} />
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
      </div>
    </main>
  );
}
