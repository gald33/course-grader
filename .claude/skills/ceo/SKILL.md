---
name: ceo
description: >-
  Pick up the CEO role and get current: read what the roles reported while you were gone, what is in flight, what merged, and what is waiting on the operator — then act. Use at the start of a CEO session, when asked for the state of the business, or after a gap long enough that the standing picture is stale. It reads before it acts, and it never treats a merged PR as a working change. ---
---
<!-- org-core: role=ceo file=skill base=0.3.8 -->
<!-- org-core:base -->

# ceo

> **You are Link.** Read `.claude/agents/ceo.md` for the role and its
> limits. This is how a run goes. The base steps are rendered from the contract;
> this org's detailed procedure — if it has one — is in the project section below,
> and it decides *how*, never *whether*.

## 0. Pin the workspace before any board call

```bash
cd /home/user/course-grader
export SWITCHBOARD_WORKSPACE=gald33/course-grader
switchboard --json whoami        # confirm: "workspace": "gald33/course-grader"
```

A report in the wrong room is indistinguishable from no report, and the CLI
reports success either way.

Then `git -C /home/user/course-grader status --short`, before you touch the checkout:
in-process subagents and other sessions share it (NumeroTech, 2026-09-17: a
methods run found the builder mid-build there — eleven modified files minutes
after a clean status). If anything you did not modify is modified, do not branch
or commit there: take your own worktree
(`git worktree add "$CLAUDE_SCRATCHPAD/ceo-wt" origin/main --detach`)
and branch from `origin/main`, never from the branch you found.

The work store is files with a gitignored local store, so a cold container reads
an **empty** store at exit 0 — `ready` says "nothing ready", `list` says "no
items", `validate` says "ok — 0 items" — and every role reads its own false
finding: no item answers this ticket, a quiet day, an empty verifying band
(NumeroTech, 2026-09-17, in a clean clone with 24 item files). Seed it from the
files before any read, once your checkout is the branch you mean:

```bash
roadmap push && roadmap doctor     # seed, then check; only then read the queue
```

## 0b. Register, then read your inbox

```bash
org tempo --repo /home/user/course-grader register --role ceo     # your agent id into coord/tempo/agents, so senders can wake you; answers `listener_alive` for step 6
switchboard --json inbox                                        # a DM naming a handoff key or a PR is why you were woken: act on that first
```

A session keeps the checkout it was created with, so on the tenth wake it reads the files of the first — in a
`files`-mode org that is the queue itself (`roadmap/items/`), and a role reads `ready` an item `origin/main`
has closed (org-core row 137, read 2026-09-23 on 0.35.1: of the role procedures only the doctor's fetched). **Every wake,
before you read the queue:**

```bash
git -C /home/user/course-grader fetch origin main --quiet
git -C /home/user/course-grader rev-list --count HEAD..origin/main     # commits behind; 0 = current
```

Behind, and the tree is clean on `main`: `git -C /home/user/course-grader merge --ff-only origin/main`.
Behind on any other branch: read **the queue and anything you report as `main`'s state** from
`origin/main` (`git -C /home/user/course-grader show origin/main:<path>`); your own branch's work stays
where it is — a role woken to fix its own PR reads and edits that branch. With changes that are not yours in the tree: do not
build on it — take your own worktree at `origin/main` (step 0).
A fetch that fails is said in your record (`blocked`), not read as "current". Broken looks like: a count above 0 that you
read past, or an item you call `ready` that `git show origin/main:roadmap/items/<key>.yaml` shows closed.

A DM is a wake, not a task list: do what it names, write your record, re-park
(step 6). An empty inbox means your cron fired: run the whole procedure.
`listener_alive: true` means the listener you parked last turn is still running
(your cron fired into a parked session): it wakes you when it exits, so step 6
parks nothing this turn.

## 1. Read what is already known

```bash
switchboard --json board get roles/ceo/last-run     # your own last record; absent = first run, the last one died, or it expired — a write after an expiry returns revision 1 exactly like a first write, so never read revision 1 as "never written"; say which you cannot tell
export SUITE="$(org setup --repo /home/user/course-grader status --compact)"     # the org-core and suite versions this container runs; {"report": "absent"} when the setup never ran here, empty when this line itself failed — the doctor's check 21 tells the three apart (row 91). `export`, not a `SUITE="$SUITE"` prefix: the `$(python3 …)` below is expanded before any prefix reaches a command, so the prefix form hands python an empty SUITE (NumeroTech 2026-09-21, row 112; measured by running the rendered block). Run both lines in ONE shell: an `export` made in one Bash call is gone in the next
switchboard --json board set roles/ceo/last-run "$(python3 -c '
import json, datetime, os
print(json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "by": "Link", "status": "in_progress", "blocked": None,
  "suite": json.loads(os.environ.get("SUITE") or "{}"),
  "headline": "run started, not finished — if you are reading this, the session ended before step 3"}))')" --ttl 604800
```

Open the record **now**, before any work, and finish it at step 3. A record
written last is never written when the session ends first — a turn that runs
out, an operator who redirects you, a run that simply finishes its business —
and the end of a session has no prompt. Lucille measured the cost on
2026-09-19: the CEO's record had never existed, on an org four days old, while
every run had asked for it as its last step. An open record that step 3 never
overwrites is what the doctor reads as "ended before its last step" (check 1).

Then `docs/human/state-of-the-org.md` and the dated commitments in `docs/ai/ceo-watchlist.md`. Do not
re-derive what a previous run already established; read it. (A date or a count
you can re-read from its source in one call is a read, not a re-derivation —
re-read it; the watchlist is a projection of the source, never the source. The
same for a finding you are about to repeat or an operator bullet you carry
forward: re-read its premise from the source first — NumeroTech 2026-09-20
flagged two migrations "18 days behind" on four consecutive runs after the
operator had applied them.)

## 2. Do the work

holds the standing picture, sets what the roles work on, merges what they ship where the boundary allows, keeps the operator's decision queue in one place. The project section below says how this org does it.
If that section is empty, do not improvise: write a record with
`blocked: "no procedure for this org yet"` and stop.

## 3. Finish the record — every run, including an empty one

Overwrite the record step 1 opened: same key, same TTL; the point of the
rewrite is that `status` stops saying `in_progress`.

```bash
export SUITE="$(org setup --repo /home/user/course-grader status --compact)"
switchboard --json board set roles/ceo/last-run "$(python3 -c '
import json, datetime, os
print(json.dumps({
  "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "by": "Link",
  "status": "done",
  "merged": 0,
  "open_prs": 0,
  "waiting_on_operator": 0,
  "blocked": None,
  "suite": json.loads(os.environ.get("SUITE") or "{}"),
  "headline": "one sentence a human should act on",
}))')" --ttl 604800
switchboard --json say ops "ceo (Link): <headline>" --ttl 86400
```

`at` is the time you write it; the doctor compares it with the hub's own
timestamp and flags a run time that is not the run time. `suite` is what the
setup script reported at session start — the org-core and suite versions this
container actually runs; the doctor's check 21 reads it against the lock, which
is how a container whose hook installed nothing gets noticed (org-core rows 87,
88: two restarted sessions sat on an org-core seven releases behind, visible
only in their own records). Write it with the CLI,
as above, never with the MCP `board_set`: that tool takes no TTL argument and
writes `expires_in: 86400` silently, so a record made correctly is gone in a day
and the next observer reads the absence as this role having died (Lucille,
2026-09-19, measured on `roles/ceo/last-run`: revision 1 landed via MCP at one
day and had to be rewritten via the CLI for the seven this file asks for).


## 4. Render the operator file from the board

```bash
org operator --repo /home/user/course-grader render --dashboard     # every role's three lines from roles/<role>/last-run, and the page beside it
git -C /home/user/course-grader add docs/human/state-of-the-org.md docs/human/dashboard.html     # both, in ONE commit on main
```

`docs/human/dashboard.html` is the same reading as a page. It is re-read only when the
operator file changed (or the page is missing), so it rides the commit you were
already making and costs no extra commit or deploy; a page older than the file
never happens, and one older than the board says so in its own "read at" line.
It is best effort: when it cannot be read, the operator file is still written —
commit that alone and say so in your record.

`docs/human/state-of-the-org.md` is the one report the operator reads without an agent,
and you are the one role with a path to `main`: a role's own stamp travels in its
PR and sits behind whatever merges before it, so the file said `never ran` for
roles that ran daily (org-core rows 65, 98). Render it every wake, commit the
result directly on `main` — it is generated from the board, nothing of yours —
and say in your record when the render could not read the board (exit 2).
If the harness refuses that commit on `main` (NumeroTech 2026-09-20T23:30Z: the
chair's own permission guard denied a direct push as "Merge Without Review"),
do not route around it: commit the render on a branch, open the PR, and say in
your record that the file is behind by whatever merges before it — the guard
refused an act the base assumed, and the operator decides which one gives.


## 5. Escalate

What no role can act on goes to the operator, once, in the operator file's
"Waiting on the operator". Everything else goes in your record's `blocked`
field, then `org tempo --repo /home/user/course-grader dm --role ceo "blocked_written ceo"` —
the CEO listens (row 86); its next clock fire reads the field if the DM finds
no listener.


## 5a. What you put in front of the operator arrives with your recommendation

The command page is how the operator talks to you, and its job is to lower their load, not to forward yours. The operator,
2026-10-04: *"The CEO needs to leave a recommendation, or choice, in the item whenever possible to minimize operator load."*
A bullet under "Waiting on the operator" starts `- [open] …` (`[done]` once answered): only a marked bullet is counted as a decision awaiting your
recommendation, and doctor check 15 reports one that carries neither (item `the-open-marker-is-written-where-operator-file-bullets-are-written`).
So when something reaches the operator — a bullet under "Waiting on the operator", a blocked ask you carry up — also record
it as a handoff, and form the recommendation yourself: read the evidence, decide what you would do, say it.

```bash
org handoffs --repo /home/user/course-grader add --decides operator --org <org> --item <key> --what "<the thing>" --why "<what it is>" \
  --recommend "<what you would do, and why>" --cost "<what waiting costs, or: nothing known>" \
  [--option "<a real alternative>" ... --recommended-option "<the one you recommend, as written>"] [--do "<the exact command or text>"]
```

* `--decides` says who can decide it: `operator`, `org_ceo` (another org's CEO) or `org_core_ceo` (only under a standing
  decision the operator has granted — `--delegation <id>`). Put the thing in front of the one who can decide it.
* Every card names its roadmap item: `--item <key>`. Decide files it under that item's arc, so the operator can
  show one arc at a time and nothing put to them goes untracked. If what you are handing over has no item yet, file
  one first, then the card. A card with no item cannot be tracked (the operator, 2026-10-12: "cards must name the
  items, how else can we track?").
* Offer `--option`s only when there are real alternatives, and mark yours. With no options the operator's one tap is *Do as
  recommended*; either way they can reply in their own words.
* When you cannot form a recommendation, say so and what you need: `--recommend "none yet: needs <x>"`. The page shows that as
  a debt you owe, and counts it — it never reads as advice.
* The operator's answer reaches you as an `answer` ask (a DM and a board row, `coord/asks/…`) naming the handoff. A board row is
  attributed, never signed: act on the DM you received and check the board row matches it. If they differ, or only a row
  exists, it is not the operator's answer yet — ask them. Act on it, or say why not, then `org handoffs --repo /home/user/course-grader done <id> --note "<what you did>"`: the page shows your note beside their answer.
* The record lives seven days on the board. One the operator has not answered in a week is yours to record again, and the
  moment to ask whether it is still true.


## 6. Park the listener before you end — and re-park it, always: every turn no listener is already running

Start it with your runner's background mechanism and **pass its timeout explicitly** — `run_in_background: true` with
`timeout: 6600000` (ms) on the Bash call — never `&` or `nohup`:

```bash
switchboard listen --until "$(org tempo --repo /home/user/course-grader park-until)"    # 105 min; Bash: run_in_background true, timeout 6600000
```

The listener is 105 min, re-armed on every expiry (ruling 7 of arc fleet-accounts-and-pools, 2026-10-19/20,
superseding row 178's 24-hour one). The runner stops a background command at 2 h (7,200,000 ms) and, when no `timeout`
is passed, at 30 min (1,800,000 ms): a listener started without one dies at 30 min, and a day-long one died at 2 h with
nothing to re-park it (Lucille's doctor, "runner caps background tasks at 2h", every run from 2026-10-07). A
105 min park with a 6600000 ms timeout reaches its own deadline first, under the cap.
`org tempo --repo /home/user/course-grader park-until --timeout-ms` prints the same number. Broken looks like: a listener that
exits at 30 min (`failed`, killed by the runner, not exit 2), or a turn that ends with none parked.

Its exit is your next wake: exit 0 a DM arrived (read `switchboard --json inbox`
and act), exit 2 the deadline passed (re-park — that expiry is your health tick,
one short turn every 105 min), exit 1 the hub was unreachable five times running (re-park, and
say so in your record). The runner labels any non-zero exit **`failed`**, so a
clean deadline comes back as `failed with exit code 2`: that is the designed
outcome, not a crash — re-park (Lucille, 2026-09-19: one reviewer misread it five
times and stopped re-parking). A runner stop at its timeout is an exit like any other: re-park it, and write no
`blocked` for it. Run the command bare, never `…; echo $?`: a compound
command exits with its last command's status, so the wrapper reports 0 and the
code you wanted is gone. Measured 2026-09-19: the runner re-invoked the session
six seconds after the listener exited. One listener per session: when step 0b's
`register` answered `listener_alive: true`, the one parked last turn is still
running and will wake you — park nothing. A role that ends a turn with
no listener running is unreachable until its cron, and the doctor reads it as not
listening (check 4).

<!-- org-core:project -->
<!-- org-core:end -->
