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
import { api, DraftQuestion, emptyDraftQuestion, Exam, formatNumber, gradingRule } from "../../../lib/bmsitai";

export default function TeacherExamsPage() {
  const { session, health, ready, logout } = useRequiredSession("teacher");
  const [exams, setExams] = useState<Exam[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const [schemaSubject, setSchemaSubject] = useState("");
  const [schemaTitle, setSchemaTitle] = useState("");
  const [schemaFiles, setSchemaFiles] = useState<File[]>([]);
  const [questionFiles, setQuestionFiles] = useState<File[]>([]);

  const [manualTitle, setManualTitle] = useState("");
  const [manualSubject, setManualSubject] = useState("");
  const [manualInstructions, setManualInstructions] = useState("");
  const [manualMaxQuestions, setManualMaxQuestions] = useState("");
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
    if (!session || !schemaFiles.length) return;
    setBusy("schema");
    setNotice("");
    try {
      const form = new FormData();
      form.append("subject", schemaSubject);
      form.append("title", schemaTitle);
      schemaFiles.forEach((file) => form.append("schema_files", file));
      questionFiles.forEach((file) => form.append("question_files", file));
      const exam = await api<Exam>("/schema/extract", { method: "POST", body: form }, session.token);
      setExams((current) => [exam, ...current.filter((item) => item.id !== exam.id)]);
      setSchemaFiles([]);
      setQuestionFiles([]);
      setSchemaSubject("");
      setSchemaTitle("");
      setNotice("Exam blueprint extracted. Confirm the rule, then check students from the Check page.");
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
            max_questions_to_grade: manualMaxQuestions ? Number(manualMaxQuestions) : null,
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
      setManualMaxQuestions("");
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
              <h3>Extract exam blueprint</h3>
              <button
                className="btn-primary"
                disabled={!schemaFiles.length || !schemaSubject || !schemaTitle || busy === "schema"}
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
            <label>
              <span className="label">Subject</span>
              <input className="field" onChange={(event) => setSchemaSubject(event.target.value)} required value={schemaSubject} />
            </label>
            <UploadBox
              accept=".pdf,.png,.jpg,.jpeg,.webp"
              icon={<FileText size={22} />}
              label={
                questionFiles.length
                  ? `${questionFiles.length} question paper file${questionFiles.length === 1 ? "" : "s"} selected`
                  : "Upload question paper, optional"
              }
              multiple
              onChange={setQuestionFiles}
            />
            <UploadBox
              accept=".pdf,.png,.jpg,.jpeg,.webp"
              icon={<Upload size={22} />}
              label={
                schemaFiles.length
                  ? `${schemaFiles.length} solution scheme file${schemaFiles.length === 1 ? "" : "s"} selected`
                  : "Upload solution scheme"
              }
              multiple
              onChange={setSchemaFiles}
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
            <label>
              <span className="label">Questions to grade, optional</span>
              <input
                className="field"
                max={manualQuestions.length || undefined}
                min={1}
                onChange={(event) => setManualMaxQuestions(event.target.value)}
                placeholder="Example: 4 for best 4 of 8"
                type="number"
                value={manualMaxQuestions}
              />
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
                    <th>Rule</th>
                    <th>Total marks</th>
                  </tr>
                </thead>
                <tbody>
                  {exams.map((exam) => (
                    <tr key={exam.id}>
                      <td>{exam.title}</td>
                      <td>{exam.subject}</td>
                      <td>{exam.questions.length}</td>
                      <td>{gradingRule(exam)}</td>
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
