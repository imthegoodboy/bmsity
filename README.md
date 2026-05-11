# BmsitAi

BMSIT&M-branded AI answer sheet evaluation portal for teachers and students.

## What It Does

- Teachers create exams from an uploaded answer scheme or a manual rubric.
- The schema agent reads question numbers, per-question marks, total marks, subpart marks, and choice rules such as "best 4 of 8".
- Teachers upload student answer sheets as PDFs or images.
- The evaluation agent detects which questions the student actually attempted, extracts the written answer for each question number, grades against the matching rubric, and only counts the allowed questions.
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
{"status":"ok","openai_configured":true,"model":"gpt-5.4-mini"}
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
2. Upload the answer scheme PDF/image.
3. Confirm the extracted exam shows the correct question count, total marks, and rule.
4. Open `/teacher/check`.
5. Select the exam.
6. Enter student name and USN.
7. Upload the answer sheet PDF or page images.
8. Add the student to the queue.
9. Run agents.
10. Open `/teacher/review`.
11. Confirm attempted/not attempted and counted/not counted questions.
12. Edit marks if needed.
13. Publish.
14. Download the teacher PDF or let the student log in and download it.

## Important Grading Behavior

The system is not hardcoded for one paper. It stores the exam rule extracted from the schema:

- all questions compulsory
- best N of M questions
- mixed per-question marks
- subpart marks summed into a question total
- unattempted questions separated from attempted but low-scoring answers

If the schema extraction says "all questions" but the marks do not make sense, the backend cross-checks the math. Example: 8 questions listed, each 10 marks, paper total 40 means the system stores a best 4 of 8 rule.

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
