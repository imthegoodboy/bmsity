"use client";

import { GraduationCap, Loader2, LockKeyhole, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { Notice } from "../../components/portal";
import { api, AuthSession, Role, saveSession } from "../../lib/bmsitai";

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="login-page"><section className="login-panel">Loading...</section></main>}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [role, setRole] = useState<Role>("teacher");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setRole(params.get("role") === "student" ? "student" : "teacher");
  }, [params]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    try {
      const session = await api<AuthSession>(`/auth/${role}/login`, {
        method: "POST",
        body: JSON.stringify({ identifier, password }),
      });
      saveSession(session);
      router.push(session.role === "teacher" ? "/teacher/exams" : "/student");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel">
        <Link className="brand-lockup" href="/">
          <img alt="BMSIT&M logo" src="/brand/bmsit-logo.svg" />
          <div>
            <p className="eyebrow">BmsitAi</p>
            <h1>Sign in</h1>
            <span>Choose the correct portal to continue.</span>
          </div>
        </Link>

        <div className="segmented">
          <button className={role === "teacher" ? "active" : ""} onClick={() => setRole("teacher")} type="button">
            <UserRound size={16} />
            Teacher
          </button>
          <button className={role === "student" ? "active" : ""} onClick={() => setRole("student")} type="button">
            <GraduationCap size={16} />
            Student
          </button>
        </div>

        <form className="flow-panel border-0 shadow-none" onSubmit={login}>
          <label>
            <span className="label">{role === "teacher" ? "Teacher email" : "USN"}</span>
            <input
              autoComplete={role === "teacher" ? "email" : "username"}
              className="field"
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder={role === "teacher" ? "Enter teacher email" : "Enter USN"}
              required
              value={identifier}
            />
          </label>
          <label>
            <span className="label">Password</span>
            <input
              autoComplete="current-password"
              className="field"
              onChange={(event) => setPassword(event.target.value)}
              placeholder={role === "student" ? "First login password is your USN" : "Enter password"}
              required
              type="password"
              value={password}
            />
          </label>
          <button className="btn-primary w-full" disabled={busy} type="submit">
            {busy ? <Loader2 className="animate-spin" size={16} /> : <LockKeyhole size={16} />}
            Continue
          </button>
        </form>

        {notice ? <Notice tone="bad" text={notice} /> : null}
      </section>
    </main>
  );
}
