# course-grader

`course-grader` is a localhost-only, multi-course grading system for an applied AI course.

- Backend: FastAPI + SQLAlchemy + Alembic
- Worker: Celery + Redis
- Frontend: Next.js + TypeScript + shadcn-style UI components
- Persistence: SQLite (`./data/db.sqlite3`)
- Artifacts/exports/secrets: `./data`

## Features

- Multi-course management (`code`, `name`, `year`, `semester`)
- Roster XLSX import (`תעודת זהות`, `שם`, attendance extraction/computation)
- Assignment ZIP ingestion with robust filename parser:
  - `ID_<id1>+ID_<id2>+..._WorkCode_<n>.<ext>`
  - `OriginalityReturn_<score>.PDF`
- Group submissions (up to 5) with student membership mapping
- Colab URL paste table and immediate snapshot fetch queue
  - Public fetch attempts
  - Private notebooks via Google OAuth + Drive readonly scope
- Notebook run queue/history (snapshot/latest), pin run for grading
- Notebook execution with:
  - sequential run
  - continue-on-error (`allow_errors=True`)
  - hard total timeout (default 15 minutes)
  - run ratio and penalty multiplier (`run_ratio ** 1.5`)
  - executed notebook + HTML + logs artifacts
- Rubrics (0-5 dimensions) + dimension curves (monotonic piecewise 0..5 -> 0..5)
- Calibration action to target `FinalBase ~ 83` using tunable dimensions only
- Attendance threshold model + helper action `Set threshold so <=25% fail`
- Per-student override deltas per component (reason required)
- Presentation XLSX import (initial/final sheets, group blocks, Hebrew criteria mapping, bonus import)
- Report/code consistency heuristic summary
- Gradebook per course + CSV export
- Student PDF report export in Hebrew to:
  - `./data/exports/<course_code>_<year>_<semester>/student_reports`

## Repository layout

- `docker-compose.yml`
- `backend/`
- `frontend/`
- `data/`
- `Makefile`

## Prerequisites (macOS + Docker Desktop)

1. Install Docker Desktop.
2. Ensure Docker daemon is running.
3. Open this repo in terminal.

## Quick start (automatic)

```bash
# from repo root
make start
```

What `make start` does automatically:

- Creates required `./data` folders
- Creates a template `./data/secrets/google_client.json` if missing
- Starts Docker Desktop (if not already running)
- Waits for Docker daemon readiness
- Runs `docker compose up -d --build`
- Waits for backend health endpoint
- Prints service URLs

Services:

- Frontend: [http://localhost:3000](http://localhost:3000)
- Backend API: [http://localhost:8000](http://localhost:8000)
- Redis: `localhost:6379`

The backend container runs Alembic migrations automatically on startup.

Useful commands:

```bash
make status   # container status + backend health
make logs     # stream logs
make open     # open frontend and backend docs in browser (macOS)
make down     # stop everything
make restart  # down + up
```

## Google OAuth setup (for private Colab notebooks)

1. In Google Cloud Console, create OAuth client credentials for an Installed/Desktop app.
2. Save client JSON to:
   - `./data/secrets/google_client.json`
3. Start OAuth flow from API:
   - `GET /api/oauth/google/start`
4. Open returned URL in browser, grant readonly Drive access.
5. Callback endpoint stores token at:
   - `./data/secrets/google_token.json`

Notes:

- Scope: `https://www.googleapis.com/auth/drive.readonly`
- Redirect URI used by backend: `http://localhost:8000/api/oauth/google/callback`

## Main workflow

1. Create course on home page.
2. Upload roster XLSX.
3. Upload assignment ZIP (set assignment type + workcode).
4. Paste Colab URL in course submissions table.
5. Queue notebook run (`snapshot` or `fetch latest + run`).
6. Open review page per submission:
   - notebook HTML + PDF split view
   - rubric sliders
   - run history + pin
   - notes and student feedback
7. Import presentations XLSX.
8. Review gradebook and export CSV.
9. Queue student Hebrew PDF report export.

## Scoring model

Final:

```text
Final = 0.10*HW1 + 0.10*HW2 + 0.70*ProjectWithBonus + 0.10*Attendance
ProjectWithBonus = ProjectBase + BonusPoints
ProjectBase = 0.50*ProjectCode + 0.20*ProjectReport + 0.10*InitialTalk + 0.20*FinalTalk
```

- HW1: binary completion (100/0)
- Attendance: threshold pass/fail; exemptions force 100
- Bonus: per-student points added to project after rubric + curve adjustments
- Notebook-based components (`HW2`, `ProjectCode`) multiplied by penalty (`run_ratio ** 1.5`)

## Development commands

```bash
make up
make down
make logs
make backend-test
make backend-migrate
```

## Tests

Backend unit tests include fixture-based loaders/parsers:

- `backend/tests/fixtures/sample_roster.xlsx`
- `backend/tests/fixtures/sample_presentations.xlsx`
- `backend/tests/fixtures/sample_submissions.zip`

Run:

```bash
cd backend
pytest -q
```

## API highlights

- `POST /api/courses`
- `POST /api/courses/{course_id}/imports/roster`
- `POST /api/courses/{course_id}/imports/submissions-zip`
- `POST /api/courses/{course_id}/imports/presentations`
- `GET /api/courses/{course_id}/submissions`
- `POST /api/submissions/{submission_id}/snapshot`
- `POST /api/submissions/{submission_id}/runs`
- `POST /api/runs/{run_id}/pin`
- `PUT /api/submissions/{submission_id}/rubric`
- `POST /api/courses/{course_id}/curves/calibrate-mean-83`
- `GET /api/courses/{course_id}/gradebook`
- `GET /api/courses/{course_id}/gradebook/csv`
- `POST /api/courses/{course_id}/exports/student-reports`

## Security and scope

- No login/auth screen by design (localhost-only deployment).
- This repository is intended for local/internal use.
