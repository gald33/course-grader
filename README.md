# course-grader

`course-grader` is a multi-course grading system for an applied AI course. It runs on the instructor's machine
(SQLite, local files, open instructor routes) or hosted on Vercel + Supabase with an instructor token and student
logins; see [Security and scope](#security-and-scope).

- Backend: FastAPI + SQLAlchemy + Alembic
- Worker: database-backed job queue (`python -m app.tasks.worker`)
- Frontend: Next.js + TypeScript + shadcn-style UI components
- Persistence: SQLite (`./data/db.sqlite3`) locally, Postgres (Supabase) when hosted
- Artifacts/exports/secrets: `./data` locally, a private Supabase Storage bucket when hosted

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
  - Student-formed teams (join codes), with an instructor lock and maximum team size
  - Practice rounds that never count toward a grade
  - One counted score per review (default: a final score 0–100); other criteria are optional remarks
  - Rounds that require a working site link, checked when the team saves it
  - Test students (an instructor-owned student account that never counts) and read-only "View as student"
- Student accounts: email + password login (Supabase Auth), first password = national ID
- Student PDF report export in Hebrew: one zip of PDFs per export, stored through the storage backend
  (`./data/artifacts/exports/<course_code>_<year>_<semester>/student_reports_<timestamp>.zip` locally, the private bucket
  when hosted) and downloaded from the gradebook

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

Course setup and grading:

1. Create course on home page.
2. Upload roster XLSX (Yedion exports work). Emails from the roster become student logins.
3. Upload assignment ZIP (set assignment type + workcode).
4. Paste Colab URL in course submissions table.
5. Queue notebook run (`snapshot` or `fetch latest + run`). On the hosted app the queued job waits for
   `make worker-hosted`.
6. Open review page per submission:
   - notebook HTML + PDF split view
   - rubric sliders
   - run history + pin
   - notes and student feedback
7. Import presentations XLSX.
8. Review gradebook and export CSV.
9. Queue the student Hebrew PDF reports (**Queue Hebrew PDFs** in the gradebook); when the job finishes, download
   the zip from the link that appears. Hosted, the job waits for `make worker-hosted`.

Peer review this semester (course page → **Peer review**; details in [Peer review](#peer-review)):

1. **Teams & links → Student accounts**: create the student accounts (first password = ID number) and, if you want
   to see the site as a student, a test student.
2. **Teams & links → Teams**: leave "Students can create, join and leave teams themselves" on and set the max team
   size; students open a team and share its join code. Move stragglers by hand, then lock teams once final.
3. Optionally **+ Add practice round** so students try the review form on an ungraded round.
4. Create the default schedule, open date selection, random-assign the rest, open reviewing and each session.
5. Use **View as student** / **Preview** to check what a student sees.
6. Close the round, check participation and exclusions, run the AI grader if wanted, then release results and
   export the XLSX.

## Scoring model

Final:

```text
Final = 0.10*HW1 + 0.10*HW2 + 0.70*ProjectWithBonus + 0.10*Attendance
ProjectWithBonus = ProjectBase + BonusPoints
ProjectBase = 0.50*ProjectCode + 0.20*ProjectReport + 0.10*InitialTalk + 0.20*FinalTalk
```

- HW1: binary completion (100/0)
- HW1, HW2, ProjectCode and the presentation score can take a share from applied peer-review rounds (see Peer review)
- Attendance: threshold pass/fail; exemptions force 100
- Bonus: per-student points added to project after rubric + curve adjustments — the sum of the student's `bonus` overrides (also written by the presentation import)
- Notebook-based components (`HW2`, `ProjectCode`) multiplied by penalty (`run_ratio ** 1.5`)

## Peer review

Teams present once per review round; every student individually reviews the other teams presenting in the round.
Default structure (created by **Peer review → Create default schedule**): 13 sessions, four progress rounds
(sessions 2–3, 4–5, 6–7, 8–9), sessions 10–11 free for postponed presentations, and the final round (12–13),
four teams per session. All of it is editable.

Instructor workflow (course page → **Peer review**):

1. **Teams & links** — student accounts (and a test student), teams, and personal review links (`/r/<token>`).
   Students can form their own teams: a student without a team opens one (it gets a 6-character join code to share)
   or joins one by code, and can leave; an empty team with no review history is removed. The instructor sets the
   maximum team size, can lock team changes, sees each team's join code and how many students have no team, and can
   still move any student. Hosted, students reach their page by logging in; locally, share the links privately.
2. **Schedule & windows** — open date selection (teams volunteer for a session until the deadline), random-assign the rest,
   move / postpone / swap presentations (a presentation keeps its round and reviews when moved), open reviewing (freezes the
   rubric and snapshots team membership), open each session for reviews, close the round, release results.
3. **Rubrics** — criteria, descriptions, weights, scale labels, text prompts (required or not) and instructions, separately for
   progress and final rounds. A round pins the version current when its reviewing opened; later edits create a new version.
   **+ Add practice round** creates an ungraded round: every presentation accepts reviews while it is open, team
   changes are kept in sync, and its exports are suffixed `_practice_not_graded`.
4. **Reviews & participation** — per-student completion, exemptions (with reason), every review with reviewer identity, and
   exclusion of inappropriate reviews (reason kept, original never deleted).
5. **Scores & export** — scoring settings, AI grader, team and student scores, bonus, XLSX export.

Each rubric criterion has a "counts" flag; only counted criteria enter the score. The default rubric counts a single
final score from 0 to 100 (a criterion with a "max" takes any number from 0 to max); the 1–5 criteria and text prompts
are optional remarks. Released results show students only the normalised team result and averages of the remarks,
never a raw average of the counted score.

A round can require a working site link (`link_required`, set with `PATCH /api/courses/{course_id}/peer/rounds/{round_id}`;
there is no toggle for it in the UI yet). When a team saves its link the server checks that it loads as an HTML page from a
public address and flags links to code, chats or files; reviewers get an "open the site" button with the result, and
the team sees a banner until the link works. The round's schedule view shows each team's link status, and
**Re-check all links** there
(`POST /api/courses/{course_id}/peer/rounds/{round_id}/check-links`) re-checks every link in the round.

**Test students and "View as student".** The accounts card can create a test student (an email of your own, e.g. a
`+alias`; random first password, changed at first login). It signs in and reviews like any student but is left out of
round scores and normalisation, the anonymised export, the grade sheet, attendance stats and the student count.
**View as student** (Peer review step) and **Preview** (per student in Teams & links) open any student's page read-only.

Students open their link on a phone: today's presentations first, a 1–5 form per team with the two text prompts, their own
normalised shares updating live, drafts kept on the device until submitted, editing until the review window closes, slot
selection, team materials, and — after release — their team's aggregate scores and anonymised feedback.

**Anonymity.** Reviewer identity is stored for participation tracking and moderation and is shown only in the instructor
Reviews tab. Student API responses and released feedback never include reviewer ids, names, or timestamps, and exports
replace reviewers with random pseudonyms.

**Scoring (one assignment grade per round).**

```text
total[r,p]   = Σ_c w_c · score_c / Σ_c w_c   over counted c  (review r of presentation p)
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
Round scores reach the gradebook only when applied. Each graded round names the gradebook task it grades (HW1, HW2,
project code or presentation) and a peer share `w` (default 0.30) in **Scores & export**. Once the round is released,
**Apply to gradebook** writes each scored student's round Final as one override with component `peer_round_<n>`
(reason names the round); running it again updates those rows in place and removes them for students who no longer have
a score, and **Remove from gradebook** deletes them. For a task with applied rounds:

```
Task = (1 − w)·Own + w·Peer + Override
```

`Own` is the task's usual score (autograder/rubric after curve and penalty, the manual grade, or HW1's 100/0); `Peer` is the
mean of the student's applied round Finals for that task (each includes the round bonus, `peer_round_<n>_bonus`) and `w`
the mean of those rounds' shares; `Override` is the task's ordinary per-component override (an absolute bonus). A round
the student has no score in is left out, and with no applied round the task is `Own + Override` as before. The gradebook
marks such cells "peer", the student page notes "כולל ביקורת עמיתים", and the CSV has `<task>_peer` columns.

**Letting students in from a local install.** Without hosting, the app is localhost-only by default. To reach students' phones, set `INSTRUCTOR_TOKEN` in `.env`
(instructor API routes then require it; the instructor UI asks for it once and keeps a cookie), restart, and expose the
frontend port, e.g. `cloudflared tunnel --url http://localhost:3000`. The frontend proxies `/api` to the backend, so only
port 3000 needs to be reachable. Set the tunnel URL as **Link base URL** in Teams & links before copying links.

## Hosted app

- Instructors: https://course-grader-pi.vercel.app (unlock with the hosted `INSTRUCTOR_TOKEN`; kept locally as `HOSTED_INSTRUCTOR_TOKEN` in `.env`)
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

Frontend smoke test (Playwright): builds the frontend, migrates and seeds a fresh SQLite database
(`backend/scripts/seed_e2e.py`), starts both servers on ports 8100/3100, and checks that the instructor
course page and the student review page render. It needs the backend's Python dependencies; point
`PYTHON` at that interpreter if it isn't `python3`:

```bash
cd frontend
npx playwright install chromium   # once
PYTHON=../backend/.venv/bin/python npm run test:e2e
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs the backend tests, applies the migrations to a fresh
database, type-checks the frontend, and runs the frontend smoke test on every pull request and on pushes
to `main`. It skips the
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
- `POST /api/courses/{course_id}/exports/student-reports`, then `GET /api/tasks/{task_id}` and
  `GET /api/courses/{course_id}/exports/student-reports/{task_id}/download` (zip; a signed-URL redirect when hosted)

Peer review (instructor, prefix `/api/courses/{course_id}/peer`):

- `POST /setup` (default schedule), `GET /overview`
- `GET /teams`, `POST /teams`, `PUT /team-settings` (`teams_open`, `max_team_size`), `PUT /students/{student_id}/team`
- `PUT /rubrics/{kind}`
- `POST /rounds/practice`, `PATCH /rounds/{round_id}`, `POST /rounds/{round_id}/actions/{action}`
- `POST /rounds/{round_id}/check-links`
- `GET /rounds/{round_id}/scores`, `POST /rounds/{round_id}/llm-review`, `GET /rounds/{round_id}/export.xlsx`
- `GET /links`, `POST /links/generate`
- `GET /student-view/{student_id}` (read-only student page)

Student accounts (instructor, prefix `/api/courses/{course_id}/accounts`): `GET ""`, `POST /create`,
`POST /{student_id}/reset-password`, `POST /test-student`, `POST /invite`.

Students (no instructor token):

- `/api/student-auth/*`: `login`, `logout`, `me`, `change-password`, `set-password`, `forgot`
- `/api/r/{token}`: the review page (`GET ""`), reviews, slot selection, materials and slides, and
  `POST /team`, `POST /team/join`, `POST /team/leave`, `PATCH /team`

## Security and scope

The same code runs in two setups; `INSTRUCTOR_TOKEN` is what separates them.

**Local (default).** `INSTRUCTOR_TOKEN` unset: there is no instructor login, and every API route is open to anyone
who can reach ports 3000/8000, so keep it on localhost. Students have no way in unless you expose the app
(see "Letting students in from a local install" under [Peer review](#peer-review)), and then you must set the token.

**Hosted (Vercel + Supabase) or any exposed install.** With `INSTRUCTOR_TOKEN` set (on the hosted app, a Vercel
environment variable of `course-grader-api`), the backend middleware (`backend/app/api/auth.py`) requires it on every
`/api` route except:

- `/api/health`, `/api/oauth/google/callback`, `/api/auth/status`, `/api/auth/instructor-session`
- student routes under `/api/r/` and `/api/student-auth/`

The instructor UI asks for the token once (`POST /api/auth/instructor-session`) and keeps it in an HTTP-only
`cg_instructor` cookie for 30 days; API clients can send the `X-Instructor-Token` header instead.

Students authenticate in two ways:

- **Review link**: the `/r/<token>` URL itself is the credential (a random per-enrollment token; regenerate it from
  Teams & links if one leaks). Student API responses never include other reviewers' identities.
- **Login** (hosted): email + password through Supabase Auth at `/login`, which sets a signed `cg_student` cookie
  (`SESSION_SECRET`, or a key derived from `SUPABASE_SECRET_KEY`) and sends the student to their review link. Until a
  student changes the first password (their ID number), anyone who knows their email and ID can sign in as them.

Data: Supabase tables are kept out of Supabase's public REST API (migration `0010`), and stored files are in a private
bucket served through short-lived signed URLs. `.env` and the Google OAuth files in `./data/secrets` are git-ignored.
