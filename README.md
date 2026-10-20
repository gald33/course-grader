# course-grader

`course-grader` is a localhost-only, multi-course grading system for an applied AI course.

- Backend: FastAPI + SQLAlchemy + Alembic
- Worker: database-backed job queue (`python -m app.tasks.worker`)
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
- Peer review of team presentations (see below): schedule & slot selection, individual anonymous student reviews from a mobile Hebrew page, versioned rubrics, AI grader, moderation, per-round normalised scores, XLSX export
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

## Peer review

Teams present once per review round; every student individually reviews the other teams presenting in the round.
Default structure (created by **Peer review → Create default schedule**): 13 sessions, four progress rounds
(sessions 2–3, 4–5, 6–7, 8–9), sessions 10–11 free for postponed presentations, and the final round (12–13),
four teams per session. All of it is editable.

Instructor workflow (course page → **Peer review**):

1. **Teams & links** — create teams, assign students, generate personal review links (`/r/<token>`) and share them privately.
2. **Schedule & windows** — open date selection (teams volunteer for a session until the deadline), random-assign the rest,
   move / postpone / swap presentations (a presentation keeps its round and reviews when moved), open reviewing (freezes the
   rubric and snapshots team membership), open each session for reviews, close the round, release results.
3. **Rubrics** — criteria, descriptions, weights, scale labels, text prompts (required or not) and instructions, separately for
   progress and final rounds. A round pins the version current when its reviewing opened; later edits create a new version.
4. **Reviews & participation** — per-student completion, exemptions (with reason), every review with reviewer identity, and
   exclusion of inappropriate reviews (reason kept, original never deleted).
5. **Scores & export** — scoring settings, AI grader, team and student scores, bonus, XLSX export.

Students open their link on a phone: today's presentations first, a 1–5 form per team with the two text prompts, their own
normalised shares updating live, drafts kept on the device until submitted, editing until the review window closes, slot
selection, team materials, and — after release — their team's aggregate scores and anonymised feedback.

**Anonymity.** Reviewer identity is stored for participation tracking and moderation and is shown only in the instructor
Reviews tab. Student API responses and released feedback never include reviewer ids, names, or timestamps, and exports
replace reviewers with random pseudonyms.

**Scoring (one assignment grade per round).**

```text
total[r,p]   = Σ_c w_c · score_c / Σ_c w_c                  (review r of presentation p)
n[r,p]       = total[r,p] / Σ_q total[r,q]                  (each reviewer's scores sum to 1 over the round)
TeamScore[p] = share of all normalised score given to p     (Σ_p TeamScore = 1)
Review[s]    = Σ_p TeamScore[p] · n[s,p]                    (× completion rate of required reviews, optional)
Raw[s]       = Review[s] · TeamScore[team(s)], normalised so Σ_s Raw = 1
Normalised   = rescaled to the round's target mean (80) and SD (10), clamped to 0–100
Final        = Normalised + bonus (override component peer_round_<n>_bonus)
```

The AI grader is one more reviewer (one call per round with every team's materials, using the frozen rubric; needs
`ANTHROPIC_API_KEY`). By default a missing review is treated as missing: a team's score averages the normalised scores it
actually received, so a larger team (fewer eligible reviewers) or an absent reviewer doesn't lower it; switch the round to
"literal share" to count missing reviews as zero instead. Presentations with no valid reviews are "not yet scored".
Round scores are reported and exported on their own; they are not added to the gradebook formula automatically.
Once a graded round is released, **Scores & export → Apply to gradebook** writes each scored student's round Final as one
override with component `peer_round_<n>` (reason names the round). Running it again updates those overrides in place and
removes them for students who no longer have a score; it never duplicates them.

**Letting students in.** The app is localhost-only by default. To reach students' phones, set `INSTRUCTOR_TOKEN` in `.env`
(instructor API routes then require it; the instructor UI asks for it once and keeps a cookie), restart, and expose the
frontend port, e.g. `cloudflared tunnel --url http://localhost:3000`. The frontend proxies `/api` to the backend, so only
port 3000 needs to be reachable. Set the tunnel URL as **Link base URL** in Teams & links before copying links.

## Hosted app

- Instructors: https://course-grader-pi.vercel.app (unlock with the instructor token, `HOSTED_INSTRUCTOR_TOKEN` in `.env`)
- Students: https://course-grader-pi.vercel.app/login
- API: https://course-grader-api.vercel.app (Vercel team "AI class", region `fra1`)

Frontend and API are two Vercel projects deployed from `frontend/` and `backend/`; the frontend proxies
`/api/*` to the API, so the browser only talks to one origin. Data lives in Supabase (`eu-central-1`).

- Pushes to `main` deploy both automatically (Vercel Git integration; pull requests get frontend previews).
  `make deploy` deploys the working tree by hand (Vercel CLI logged in with `vercel login --global-config ~/.vercel-yvc`).
- `make migrate-hosted` applies new migrations to Supabase. Run it before deploying code that needs them.
- `make worker-hosted` starts the notebook worker in the background on this machine (Docker Desktop running),
  against the hosted database and storage; `make worker-hosted-logs` / `make worker-hosted-stop`. Notebook
  runs, snapshot fetches, and report exports queued in the hosted app wait until it runs.
- API settings (database URL via the transaction pooler, storage, keys, instructor token, session secret)
  are Vercel environment variables of the `course-grader-api` project.

## Supabase (database, files, job queue)

The app runs on SQLite and local files by default. To use Supabase instead (needed for hosting):

- **Database**: set `DATABASE_URL` to the Session pooler URI and run `alembic upgrade head`. The schema is
  identical on SQLite and Postgres; migration `0010` keeps every table out of Supabase's public REST API
  (row-level security on, API roles revoked), since the app connects as the database owner.
- **Files**: `STORAGE_BACKEND=supabase` with `SUPABASE_PROJECT_URL` and `SUPABASE_SECRET_KEY`. New uploads and
  run outputs go to a private bucket; downloads redirect to short-lived signed URLs. Files stored before the
  switch keep working from local disk.
- **Background jobs**: a `jobs` table in the same database replaces Celery/Redis. The API enqueues; the worker
  (`python -m app.tasks.worker`, or the `worker` compose service) can run on any machine with the same
  `DATABASE_URL`, e.g. the instructor's Mac while the API is hosted.
- Run the API in the same region as the database (Supabase `eu-central-1` -> Vercel `fra1`): pages issue many
  small queries, so cross-region latency multiplies.

Tests run against Postgres too: `TEST_DATABASE_URL=postgresql://... pytest -q`.

## Student accounts

Students sign in at `/login` with their email; after signing in they land on their review page. Emails come
from the roster import (Yedion exports work: only ID, name, and the external email are read).

The instructor creates the accounts in **Peer review → Teams & links → Student accounts**. No email is sent:
the first password is the student's national ID number, and the student must choose their own password at
first login. A forgotten password is reset to the ID number from the same panel. Until a student changes it,
anyone who knows their email and ID number can sign in as them; the panel shows who hasn't yet.

Supabase Auth stores the passwords. In the Supabase dashboard, keep **Authentication → Sign In / Providers →
Email** enabled with a minimum password length of at most 9 and no extra character requirements (ID numbers
are 9 digits).

Email invites (`/accounts/invite`, landing on `/auth/callback`) also exist, but need an SMTP server in
Supabase: its built-in sender only reaches your own Supabase team.

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

CI (GitHub Actions, `.github/workflows/ci.yml`) runs the backend tests, applies the migrations to a fresh
database, and type-checks the frontend on every pull request and on pushes to `main`. It skips the
student-notebook ML stack, which the app and tests never import.

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

- No login/auth screen by design (localhost-only deployment). Set `INSTRUCTOR_TOKEN` before exposing the app to students;
  student review links authenticate with their own per-student token.
- This repository is intended for local/internal use.
