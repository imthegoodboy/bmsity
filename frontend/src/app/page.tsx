import { ArrowRight, BrainCircuit, CheckCircle2, FileText, GraduationCap, ShieldCheck } from "lucide-react";
import Link from "next/link";

export default function Home() {
  return (
    <main className="home-shell">
      <nav className="home-nav">
        <div className="brand-lockup">
          <img alt="BMSIT&M logo" src="/brand/bmsit-logo.svg" />
          <div>
            <p className="eyebrow">BMS Institute of Technology and Management</p>
            <h1>BmsitAi</h1>
            <span>AI answer sheet evaluation portal</span>
          </div>
        </div>
        <Link className="btn-secondary" href="/login">
          Start
          <ArrowRight size={16} />
        </Link>
      </nav>

      <section className="hero-clean">
        <div className="hero-copy">
          <p className="eyebrow">Teacher review first. Student results after publish.</p>
          <h2>Evaluate handwritten exam papers with AI agents and publish verified reports.</h2>
          <p>
            Teachers create exams, upload schemes, assign one checking agent per student, review the marks,
            and publish the final PDF to the student portal through the student's USN.
          </p>
          <div className="hero-actions">
            <Link className="btn-primary" href="/login">
              Start checking
              <ArrowRight size={16} />
            </Link>
            <Link className="btn-secondary" href="/login?role=student">
              Student portal
              <GraduationCap size={16} />
            </Link>
          </div>
        </div>
        <div className="hero-visual" aria-hidden="true">
          <img alt="" src="/brand/bmsit-hero.jpg" />
        </div>
      </section>

      <section className="process-line" aria-label="Evaluation workflow">
        <div>
          <FileText size={20} />
          <strong>Create exam</strong>
          <span>Question paper, answer scheme, and marking rules.</span>
        </div>
        <div>
          <BrainCircuit size={20} />
          <strong>Run agents</strong>
          <span>One student queue item maps to one evaluation agent run.</span>
        </div>
        <div>
          <ShieldCheck size={20} />
          <strong>Teacher review</strong>
          <span>Edit marks, see confidence, and approve the result.</span>
        </div>
        <div>
          <CheckCircle2 size={20} />
          <strong>Publish PDF</strong>
          <span>Students sign in by USN after the teacher publishes.</span>
        </div>
      </section>
    </main>
  );
}
