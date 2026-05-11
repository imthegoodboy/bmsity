# BmsitAi

BMSIT&M-branded AI answer sheet evaluation portal for teachers and students.

## What Works

- Teacher login with token-based access.
- Student login by USN, with first-login password change.
- Separate pages for exams, checking, review, analytics, and the student portal.
- Create exams manually or extract rubrics from answer scheme files.
- Upload one or many answer sheet pages for each student.
- Evaluate submissions with OpenAI vision models, one queued agent run per student.
- Teacher review, mark editing, publishing, re-checking, and PDF export.
- Student dashboard with question-wise marks, feedback, weak areas, and PDF download after publish.
- Class analytics from real completed submissions.

## Backend

```powershell
cd backend
Copy-Item .env.example .env
# Add OPENAI_API_KEY and change TEACHER_PASSWORD + AUTH_SECRET before production use.
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Frontend

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open `http://127.0.0.1:3000`.

Routes:

- `/` homepage
- `/login` teacher/student login
- `/teacher/exams` create exams and rubrics
- `/teacher/check` upload student answer sheets and run checking agents
- `/teacher/review` review, edit marks, publish, and export PDF
- `/teacher/analytics` class analytics
- `/student` published student reports

## Login

Teacher email defaults to `teacher@bmsit.ac.in`.
Teacher password comes from `TEACHER_PASSWORD` in `backend/.env`.

Students can login after a teacher creates a submission for their USN. Their first password is their USN, then the portal requires a new password.

## Verification

```powershell
cd backend
.\.venv\Scripts\python -m pytest

cd ..\frontend
npm run lint
npm run build
```
