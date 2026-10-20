# ARCS.md — what's in flight, at arc level

<!-- GENERATED FILE — DO NOT EDIT BY HAND. Regenerate with `roadmap sync`. Edit roadmap/arcs/*.yaml instead. -->

The narrative layer above `roadmap/ROADMAP.md`: *why* each theme is still open. Work items live in the roadmap graph and are listed per arc below; the prose here is the arc's own, and is the one place a multi-PR theme gets explained rather than enumerated. For when this was last regenerated ask git — `git log -1 --format=%cI -- ARCS.md` — because nothing here derives from the clock or from a graph-wide total, so two branches editing different arcs merge cleanly.

## Legend

| State | Meaning |
|---|---|
| 🟠 open | Open tail — unfinished items, or a stated unresolved decision. |
| 🔵 blocked | Nothing startable — every unfinished item is blocked, or the blocker is outside the graph and was declared. |
| 🟡 dark | Code merged, flag off **in prod env**. Declared, never derived. |
| 🟢 closed | Tail is empty and somebody said so. Declared, never derived. |

`dark`, `closed` and `blocked` may be **declared** by a human with dated evidence, because each is about something the items cannot show: an environment flag, a closure whose finished items `prune` has deleted, or a blocker outside the graph entirely. `blocked` is *also* derived when every unfinished item is itself blocked. `open` is never declared — it is the fallback every check fires on, so stating it would only silence them.

## Items with no arc

Startable and legitimate — an item does not need an arc. Listed so the narrative layer's coverage gap is visible rather than implied.

- `courses-and-submissions-cannot-be-deleted` — Courses, assignments and submissions can't be deleted or archived
- `frontend-has-no-tests` — The frontend has no tests; CI only type-checks it
- `hebrew-report-pdfs-cannot-be-downloaded` — Hebrew student report PDFs are queued but can never be retrieved from the hosted site
- `no-button-to-recheck-site-links` — Add a "re-check all links" button for a round
- `onboarding-guide-has-todo-sections` — ONBOARDING.md still has _TODO_ under Team Tips and Get Started
- `peer-round-scores-never-reach-the-gradebook` — Peer-review round scores have to be copied into the gradebook by hand
- `project-bonus-has-no-editor` — The per-student project bonus can't be edited directly
- `readme-describes-a-localhost-only-app` — README still says "no login, localhost-only" and leaves out recent features
- `roster-cannot-be-edited-per-student` — Add, remove, withdraw or fix a single student without re-importing the roster
- `students-cannot-see-their-own-grades` — Students cannot see their own grades, feedback or attendance status
- `team-formation-closes-at-a-deadline` — Let students form their own teams until a deadline, then lock teams automatically
