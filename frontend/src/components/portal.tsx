"use client";

import {
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  Download,
  FileText,
  Home,
  Loader2,
  LogOut,
  Save,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FormEvent, ReactNode, useEffect, useState } from "react";
import {
  api,
  AuthSession,
  Evaluation,
  formatNumber,
  Health,
  readSession,
  Role,
  saveSession,
  statusClass,
  statusLabel,
} from "../lib/bmsitai";

export function useRequiredSession(role: Role) {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const stored = readSession();
    if (!stored || stored.role !== role) {
      router.replace(`/login?role=${role}`);
      return;
    }
    const currentSession = stored;

    async function verify() {
      try {
        const [fresh, healthPayload] = await Promise.all([
          api<AuthSession>("/auth/me", undefined, currentSession.token),
          api<Health>("/health"),
        ]);
        if (fresh.role !== role) {
          throw new Error("Wrong portal for this account.");
        }
        saveSession(fresh);
        setSession(fresh);
        setHealth(healthPayload);
        setReady(true);
      } catch {
        saveSession(null);
        router.replace(`/login?role=${role}`);
      }
    }

    void verify();
  }, [role, router]);

  function logout() {
    saveSession(null);
    router.replace("/login");
  }

  return { session, setSession, health, ready, logout };
}

export function PortalHeader({
  health,
  mode,
  subtitle,
  onLogout,
}: {
  health: Health | null;
  mode: "teacher" | "student";
  subtitle: string;
  onLogout: () => void;
}) {
  const pathname = usePathname();
  const teacherLinks = [
    { href: "/teacher/exams", label: "Exams" },
    { href: "/teacher/check", label: "Check" },
    { href: "/teacher/review", label: "Review" },
    { href: "/teacher/analytics", label: "Analytics" },
  ];

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
          {health?.openai_configured ? "OpenAI key set" : "OpenAI key needed"}
        </span>
        {mode === "teacher" ? (
          <nav className="header-tabs" aria-label="Teacher sections">
            {teacherLinks.map((item) => (
              <Link className={pathname === item.href ? "active" : ""} href={item.href} key={item.href}>
                {item.label}
              </Link>
            ))}
          </nav>
        ) : (
          <Link className="btn-secondary" href="/">
            <Home size={16} />
            Home
          </Link>
        )}
        <button className="btn-secondary" onClick={onLogout} type="button">
          <LogOut size={16} />
          Logout
        </button>
      </div>
    </header>
  );
}

export function LoadingScreen() {
  return (
    <main className="workspace">
      <div className="empty-state min-h-[50vh]">
        <Loader2 className="animate-spin" size={20} />
        <span>Loading portal...</span>
      </div>
    </main>
  );
}

export function Notice({ text, tone = "info" }: { text: string; tone?: "info" | "bad" }) {
  return (
    <div className={tone === "bad" ? "notice notice-bad" : "notice"}>
      {tone === "bad" ? <AlertTriangle size={16} /> : <BookOpenCheck size={16} />}
      <span>{text}</span>
    </div>
  );
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <FileText size={18} />
      <span>{text}</span>
    </div>
  );
}

export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

export function UploadBox({
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
        accept={accept}
        className="sr-only"
        multiple={multiple}
        onClick={(event) => {
          event.currentTarget.value = "";
        }}
        onChange={(event) => onChange(Array.from(event.target.files ?? []))}
        type="file"
      />
    </label>
  );
}

export function EvaluationEditor({
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

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSave(evaluation, score, reason);
  }

  return (
    <form className="evaluation-card" onSubmit={save}>
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
      <div className="tagline">
        <span>{evaluation.attempted ? "Attempted" : "Not attempted"}</span>
        <span>{evaluation.counts_toward_total ? "Counts in total" : "Not counted in total"}</span>
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
        <button className="btn-primary self-end" disabled={busy} type="submit">
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
    </form>
  );
}

export function ReportButton({
  busy,
  onClick,
}: {
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button className="btn-secondary" disabled={busy} onClick={onClick} type="button">
      {busy ? <Loader2 className="animate-spin" size={16} /> : <Download size={16} />}
      PDF
    </button>
  );
}

export function StatusPill({ status }: { status: Parameters<typeof statusClass>[0] }) {
  return <span className={statusClass(status)}>{statusLabel(status)}</span>;
}
