"use client";

import { FileText, Loader2, Plus, SearchCheck, Upload } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  EmptyState,
  LoadingScreen,
  Notice,
  PortalHeader,
  UploadBox,
  useRequiredSession,
} from "../../../components/portal";
import { api, DraftQuestion, emptyDraftQuestion, Exam, formatNumber } from "../../../lib/bmsitai";

export default function TeacherExamsPage() {
  const { session, health, ready, logout } = useRequiredSession("teacher");
  const [exams, setExams] = useState<Exam[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const [schemaSubject, setSchemaSubject] = useState("");
  const [schemaTitle, setSchemaTitle] = useState("");
  const [schemaMarks, setSchemaMarks] = useState("");
  const [schemaFile, setSchemaFile] = useState<File | null>(null);

  const [manualTitle, setManualTitle] = useState("");
  const [manualSubject, setManualSubject] = useState("");
  const [manualInstructions, setManualInstructions] = useState("");
  const [manualQuestions, setManualQuestions] = useState<DraftQuestion[]>([]);
  const [draftQuestion, setDraftQuestion] = useState<DraftQuestion>(emptyDraftQuestion);

  useEffect(() => {
    if (!session) return;
    void loadExams(session.token);
  }, [session]);

  async function loadExams(token: string) {
    try {
      setExams(await api<Exam[]>("/exams", undefined, token));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load exams");
    }
  }

  async function extractSchema(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !schemaFile) return;
    setBusy("schema");
    setNotice("");
    try {
      const form = new FormData();
      form.append("subject", schemaSubject);
      form.append("title", schemaTitle);
      form.append("default_marks", schemaMarks);
      form.append("file", schemaFile);
      const exam = await api<Exam>("/schema/extract", { method: "POST", body: form }, session.token);
      setExams((current) => [exam, ...current.filter((item) => item.id !== exam.id)]);
      setSchemaFile(null);
      setSchemaSubject("");
      setSchemaTitle("");
      setSchemaMarks("");
      setNotice("Answer scheme extracted. You can now check students from the Check page.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Schema extraction failed");
    } finally {
      setBusy("");
    }
  }

  function addQuestion() {
    const marks = Number(draftQuestion.max_marks);
    if (!draftQuestion.text.trim() || !draftQuestion.model_answer.trim() || !marks) {
      setNotice("Add question text, max marks, and model answer before adding it.");
      return;
    }
    setManualQuestions((current) => [
      ...current,
      {
        ...draftQuestion,
        id: draftQuestion.id.trim() || `Q${current.length + 1}`,
        max_marks: Math.max(0.5, marks),
      },
    ]);
    setDraftQuestion(emptyDraftQuestion());
    setNotice("");
  }

  async function createManualExam(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !manualQuestions.length) return;
    setBusy("manual");
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
      setManualTitle("");
      setManualSubject("");
      setManualInstructions("");
      setNotice("Exam created. Open Check to assign student answer sheets.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create exam");
    } finally {
      setBusy("");
    }
  }

  if (!ready || !session) return <LoadingScreen />;

  return (
    <main className="min-h-screen">
      <PortalHeader health={health} mode="teacher" onLogout={logout} subtitle="Create exams and rubrics" />
      <div className="workspace">
        {notice ? <Notice text={notice} /> : null}

        <section className="page-hero">
          <div>
            <p className="eyebrow">Step 1</p>
            <h2>Create the exam and answer scheme.</h2>
            <p>Use an uploaded answer scheme or enter the rubric by hand. No student can see anything from here.</p>
          </div>
          <Link className="btn-primary" href="/teacher/check">
            Go to Check
          </Link>
        </section>

        <div className="teacher-grid">
          <form className="flow-panel" onSubmit={extractSchema}>
            <div className="split-head">
              <h3>Extract from answer scheme</h3>
              <button
                className="btn-primary"
                disabled={!schemaFile || !schemaSubject || !schemaTitle || !schemaMarks || busy === "schema"}
                type="submit"
              >
                {busy === "schema" ? <Loader2 className="animate-spin" size={16} /> : <SearchCheck size={16} />}
                Extract
              </button>
            </div>
            <label>
              <span className="label">Exam name</span>
              <input className="field" onChange={(event) => setSchemaTitle(event.target.value)} required value={schemaTitle} />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="label">Subject</span>
                <input className="field" onChange={(event) => setSchemaSubject(event.target.value)} required value={schemaSubject} />
              </label>
              <label>
                <span className="label">Default marks</span>
                <input
                  className="field"
                  min={0.5}
                  onChange={(event) => setSchemaMarks(event.target.value)}
                  required
                  step={0.5}
                  type="number"
                  value={schemaMarks}
                />
              </label>
            </div>
            <UploadBox
              accept=".pdf,.png,.jpg,.jpeg,.webp"
              icon={<Upload size={22} />}
              label={schemaFile ? schemaFile.name : "Upload answer scheme"}
              onChange={(files) => setSchemaFile(files[0] ?? null)}
            />
          </form>

          <form className="flow-panel" onSubmit={createManualExam}>
            <div className="split-head">
              <h3>Manual rubric</h3>
              <button className="btn-primary" disabled={!manualQuestions.length || busy === "manual"} type="submit">
                {busy === "manual" ? <Loader2 className="animate-spin" size={16} /> : <Plus size={16} />}
                Create
              </button>
            </div>
            <label>
              <span className="label">Exam name</span>
              <input className="field" onChange={(event) => setManualTitle(event.target.value)} required value={manualTitle} />
            </label>
            <label>
              <span className="label">Subject</span>
              <input className="field" onChange={(event) => setManualSubject(event.target.value)} required value={manualSubject} />
            </label>
            <label>
              <span className="label">Instructions</span>
              <input className="field" onChange={(event) => setManualInstructions(event.target.value)} value={manualInstructions} />
            </label>
            <div className="rubric-builder">
              <div className="grid gap-3 sm:grid-cols-2">
                <input
                  className="field"
                  onChange={(event) => setDraftQuestion((current) => ({ ...current, id: event.target.value }))}
                  placeholder="Question ID, optional"
                  value={draftQuestion.id}
                />
                <input
                  className="field"
                  min={0.5}
                  onChange={(event) =>
                    setDraftQuestion((current) => ({ ...current, max_marks: Number(event.target.value) }))
                  }
                  placeholder="Max marks"
                  step={0.5}
                  type="number"
                  value={draftQuestion.max_marks || ""}
                />
              </div>
              <input
                className="field"
                onChange={(event) => setDraftQuestion((current) => ({ ...current, text: event.target.value }))}
                placeholder="Question text"
                value={draftQuestion.text}
              />
              <textarea
                className="field min-h-24"
                onChange={(event) => setDraftQuestion((current) => ({ ...current, model_answer: event.target.value }))}
                placeholder="Model answer or marking rubric"
                value={draftQuestion.model_answer}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <input
                  className="field"
                  onChange={(event) => setDraftQuestion((current) => ({ ...current, marking_rules: event.target.value }))}
                  placeholder="Marking rules"
                  value={draftQuestion.marking_rules}
                />
                <input
                  className="field"
                  onChange={(event) => setDraftQuestion((current) => ({ ...current, keywordsText: event.target.value }))}
                  placeholder="Keywords, comma separated"
                  value={draftQuestion.keywordsText}
                />
              </div>
              <button className="btn-secondary w-full" onClick={addQuestion} type="button">
                <Plus size={16} />
                Add question
              </button>
            </div>
            {manualQuestions.length ? (
              <div className="mini-list">
                {manualQuestions.map((question, index) => (
                  <button
                    className="mini-row"
                    key={`${question.id}-${index}`}
                    onClick={() => setManualQuestions((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    type="button"
                  >
                    <span>{question.id}</span>
                    <strong>{formatNumber(question.max_marks)} marks</strong>
                    <small>Remove</small>
                  </button>
                ))}
              </div>
            ) : null}
          </form>
        </div>

        <section className="workspace-section">
          <div className="section-head">
            <div>
              <p className="eyebrow">Existing exams</p>
              <h2>Select one on the Check page when you are ready.</h2>
            </div>
          </div>
          {exams.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Exam</th>
                    <th>Subject</th>
                    <th>Questions</th>
                    <th>Total marks</th>
                  </tr>
                </thead>
                <tbody>
                  {exams.map((exam) => (
                    <tr key={exam.id}>
                      <td>{exam.title}</td>
                      <td>{exam.subject}</td>
                      <td>{exam.questions.length}</td>
                      <td>{formatNumber(exam.total_marks)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState text="No exams created yet." />
          )}
        </section>
      </div>
    </main>
  );
}
