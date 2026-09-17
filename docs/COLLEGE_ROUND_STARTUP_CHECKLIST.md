# FIRETRACE college-round startup checklist

Use this checklist before the demo. Do not print or copy the FIRMS key.

## One-command start

From the repository root:

```powershell
npm run dev
```

Wait for all of these messages:

- `Uvicorn running on http://127.0.0.1:8000`
- `model loaded=True`
- `snapshot events=...`
- `NASA FIRMS key configured (value never logged)`
- `Dashboard http://localhost:5173`

Open <http://localhost:5173>. Keep the terminal open for the whole demo; stop
both services with `Ctrl+C` afterward.

## If the combined command was interrupted

Use two terminals from the repository root:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm run dev
```

Then open <http://localhost:5173>. API health is at
<http://127.0.0.1:8000/health>.

## Before presenting

1. Confirm `/health` reports `status: ok`, `model_loaded: true`, and
   `snapshot_available: true`.
2. Start in **Live** mode when NASA FIRMS is available. Confirm the status strip
   says Live NASA FIRMS before describing records as live.
3. If live FIRMS is unavailable or empty, switch to **Demo / Historical** mode
   and say so explicitly. The historical snapshot is the supported fallback.
4. Open one marker and point out its timestamp, satellite/product, FIRMS
   confidence, evidence, RF vote score (uncalibrated), priority, and provenance.
5. Use the Replay tab only as **demo/historical** data. Every replay case states
   that ground truth is unknown.

## Required local state

- Node.js 18 or newer; frontend dependencies already installed.
- Python virtual environment at `backend/.venv`; backend dependencies installed.
- Root `.env` containing a private `FIRMS_MAP_KEY` for live mode.
- Local SQLite store and bundled historical snapshot. Both are used automatically;
  no external database service is required for the college-round demo.

## Truthful demo language

- “AI-assisted satellite thermal-event triage and industrial-context intelligence.”
- “RF vote score, not a calibrated probability.”
- “AI-assisted assessment; human verification required.”
- “Historical/degraded mode is explicit when live FIRMS is unavailable.”
