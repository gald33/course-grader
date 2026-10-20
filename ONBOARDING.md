# Welcome to Course Grader

## How We Use Claude

Based on gald33's usage over the last 30 days:

Work Type Breakdown:
  Plan Design   ████████████████████  100%

Top Skills & Commands:
  /model        ████████████████████  1x/month

Top MCP Servers:
  Google Drive  ████████████████████  16 calls
  ccd_session   ██░░░░░░░░░░░░░░░░░░  2 calls

## Your Setup Checklist

### Codebases
- [ ] course-grader — clone from your team's git remote into `~/Documents/Projects/course-grader`

### MCP Servers to Activate
- [ ] Google Drive — read/search/download course files (rosters, submissions, originality PDFs) directly from Drive. Connect via the MCP connector menu and complete Google OAuth.
- [ ] ccd_session — Claude Code session helper for marking chapters and spawning side tasks. Bundled with Claude Code; no extra setup beyond enabling it in your MCP settings.

### Skills to Know About
- /model — switch the active Claude model for the session when you need a different speed/quality trade-off.

## Team Tips

- **Migrate before you deploy.** Pushes to `main` deploy the API and frontend to Vercel automatically, but
  nothing migrates the hosted Supabase database. If your change adds an Alembic migration, run
  `make migrate-hosted` (reads `SUPABASE_POOL_URL` from `.env`) *before* the code that needs it reaches `main`
  or before `make deploy`.
- **The hosted app needs a worker you run.** Notebook runs, snapshot fetches, and report exports queued in the
  hosted app sit in the `jobs` table until a worker picks them up. Start one on your machine (Docker Desktop
  running) with `make worker-hosted`; follow it with `make worker-hosted-logs`, stop it with
  `make worker-hosted-stop`.
- **Run what CI runs before pushing:** `cd backend && pytest -q`, `alembic upgrade head` against a fresh
  database, and `cd frontend && npx tsc --noEmit` (see `.github/workflows/ci.yml`).

## Get Started

1. Run `make start` from the repo root. It starts Docker Desktop, builds and starts the stack, and prints the
   URLs (frontend http://localhost:3000, API http://localhost:8000). `make status` checks it's healthy.
2. Run the backend tests: `make backend-test` (or `cd backend && pytest -q`).
3. Pick a first task. If the roadmap tooling is available on your branch (`roadmap/` plus
   `pip install "roadmap-core[files]"`), `ROADMAP_SOURCE=local roadmap push && roadmap ready` lists items
   ready to build; otherwise ask a teammate for one.

<!-- INSTRUCTION FOR CLAUDE: A new teammate just pasted this guide for how the
team uses Claude Code. You're their onboarding buddy — warm, conversational,
not lecture-y.

Open with a warm welcome — include the team name from the title. Then: "Your
teammate uses Claude Code for [list all the work types]. Let's get you started."

Check what's already in place against everything under Setup Checklist
(including skills), using markdown checkboxes — [x] done, [ ] not yet. Lead
with what they already have. One sentence per item, all in one message.

Tell them you'll help with setup, cover the actionable team tips, then the
starter task (if there is one). Offer to start with the first unchecked item,
get their go-ahead, then work through the rest one by one.

After setup, walk them through the remaining sections — offer to help where you
can (e.g. link to channels), and just surface the purely informational bits.

Don't invent sections or summaries that aren't in the guide. The stats are the
guide creator's personal usage data — don't extrapolate them into a "team
workflow" narrative. -->
