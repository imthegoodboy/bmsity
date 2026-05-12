# BmsitAi

BMSIT&M-branded AI answer sheet evaluation portal for teachers and students.

## What It Does

- Teachers create exams from uploaded question paper pages plus solution-scheme pages, or from a manual rubric.
- The blueprint agent reads question numbers, subparts, per-question marks, total marks, and structured choice rules such as "best 4 of 8" or "Q1 compulsory, answer any 2 from Q2-Q4" without hardcoding one paper pattern.
- Teachers upload student answer sheets as PDFs or images.
- The evaluation agent detects which questions and subparts the student attempted, extracts the written answer, grades against the matching rubric, and a verifier agent re-checks the marks before the backend applies the allowed-question rule.
- Teachers review marks, edit final scores, re-check, publish, and export PDFs.
- Students log in by USN after publish and can view/download only their published reports.

## Prerequisites

- Windows PowerShell
- Python 3.11 or newer
- Node.js 20 or newer
- An OpenAI API key with access to the configured model

## First-Time Setup

Run these commands from the repo root.

```powershell
cd backend
Copy-Item .env.example .env
notepad .env
```

Set these values in `backend/.env`:

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-5.4-mini
OPENAI_SCHEMA_MODEL=gpt-5.4-mini
OPENAI_EVALUATION_MODEL=gpt-5.4-mini
OPENAI_VERIFIER_MODEL=gpt-5.4-mini
TEACHER_EMAIL=teacher@bmsit.ac.in
TEACHER_PASSWORD=choose-a-real-password
AUTH_SECRET=choose-a-long-random-secret
FRONTEND_ORIGIN=http://localhost:3000
```

Install backend dependencies:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
cd ..\frontend
Copy-Item .env.example .env.local
npm install
```

## Run Locally

Use two PowerShell windows.

Backend:

```powershell
cd C:\Users\parth\Desktop\bmsityi\backend
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd C:\Users\parth\Desktop\bmsityi\frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open:

```text
http://127.0.0.1:3000
```

Backend health check:

```text
http://127.0.0.1:8000/health
```

Expected health response:

```json
{"status":"ok","openai_configured":true,"model":"gpt-5.4-mini","schema_model":"gpt-5.4-mini","evaluation_model":"gpt-5.4-mini","verifier_model":"gpt-5.4-mini"}
```

## Login Flow

Teacher:

- Go to `/login`.
- Select `Teacher`.
- Use `TEACHER_EMAIL` and `TEACHER_PASSWORD` from `backend/.env`.

Student:

- A student can log in only after the teacher uploads, evaluates, and publishes a submission for that student's USN.
- First login password is the student's USN.
- The student portal forces a password change on first login.

## Teacher Demo Flow

1. Open `/teacher/exams`.
2. Upload the question paper files if available.
3. Upload every solution-scheme PDF/image page.
4. Confirm the extracted exam shows the correct question count, subparts, total marks, and rule.
5. Open `/teacher/check`.
6. Select the exam.
7. Enter student name and USN.
8. Optionally enter attempted-question hints such as `Q1, Q2, Q5, Q8`.
9. Upload the answer sheet PDF or page images.
10. Add the student to the queue.
11. Run agents.
12. Open `/teacher/review`.
13. Confirm attempted/not attempted and counted/not counted questions.
14. Edit marks if needed.
15. Publish.
16. Download the teacher PDF or let the student log in and download it.

## Important Grading Behavior

The system is not hardcoded for one paper. It stores the exam rule extracted from the schema:

- all questions compulsory
- best N of M questions
- mixed compulsory plus optional groups
- nested parts such as Q1(a), Q1(b), Q2(i), and Q2(ii)
- mixed per-question marks
- subpart marks summed into a question total
- unattempted questions separated from attempted but low-scoring answers
- optional teacher hints for attempted questions
- second-pass verification before totals are finalized

If the schema extraction says "all questions" but the marks do not make sense, the backend cross-checks the math. Example: 8 questions listed, each 10 marks, paper total 40 means the system stores a best 4 of 8 rule.

The AI agents extract and verify evidence. The backend still clamps marks, applies the final choice rule, and selects the counted questions deterministically.

Old exams keep old extracted data. If you improve extraction logic, upload the scheme again as a new exam or repair/re-check existing submissions.

## Verification

Backend tests:

```powershell
cd C:\Users\parth\Desktop\bmsityi\backend
.\.venv\Scripts\python -m pytest
```

Frontend checks:

```powershell
cd C:\Users\parth\Desktop\bmsityi\frontend
npm run lint
npm run build
```

## Production Notes

- Change `TEACHER_PASSWORD` and `AUTH_SECRET` before a real deployment.
- Keep `backend/.env` and `frontend/.env.local` out of Git.
- Use HTTPS and a proper production database before external hosting.
- Keep teacher review in the loop before publishing student reports.
