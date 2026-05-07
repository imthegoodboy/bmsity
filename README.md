# BmsitAi

Localhost AI answer sheet evaluation app.

## Backend

```powershell
cd backend
Copy-Item .env.example .env
# Add OPENAI_API_KEY to .env
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.
