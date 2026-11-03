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

- `assignments-need-custom-rubrics` — Assignments are graded on one fixed rubric instead of rubrics that fit the task
- `autograder-needs-a-proper-redesign` — The notebook autograder needs a proper redesign, once there is enough graded data
- `course-42052-whole-syllabus` — The 42052 course exists only as one guided lesson; the other 12 sessions, the schedule and readiness are missing, and lesson 2's answer keys sit in a public repository
- `courses-and-submissions-cannot-be-deleted` — Courses, assignments and submissions can't be deleted or archived
- `exit-check-no-chatbot` — Every lesson's exit check ends by sending students to a chatbot to challenge their explanation, a chatbot task with no reason
- `frontend-has-no-tests` — The frontend has no tests; CI only type-checks it
- `hebrew-report-pdfs-cannot-be-downloaded` — Hebrew student report PDFs are queued but can never be retrieved from the hosted site
- `instructor-course-page-is-organized-as-fake-steps` — The instructor course page is eight numbered "steps" that aren't steps, with student tools in three places
- `instructor-pages-are-walls-of-text` — Instructor and student pages are walls of text, with no sign of what needs attention
- `lesson-3-how-language-models-work` — Lesson 3 (how language models work) is only a three-step seed, with no runnable demo, no chatbot exercises and no notebook, and it is the next class session
- `lesson-3-part-b-deeper` — Lesson 3 teaches tokens, prediction and grounding but not neural networks, embeddings or transformers, and none of it is hands-on in the browser
- `lesson-3-restructure-two-parts` — Session 3 sends students to a chatbot to learn instead of teaching on the page, uses weights and parameters before neural networks are taught, and frames its second half as optional
- `lesson-3-review-fixes` — Lessons 3 and 3-deeper state a few things that are not true (majority probability, chatbot sizes, one repeating layer, why the embedding model pairs translations)
- `lesson-4-coding-agent` — Lesson 4 (coding agent, from plan to run and check) is only a three-step seed, with no hands-on tool steps, no starter project and no runnable check
- `lesson-5-product-definition` — Lesson 5 (defining a small business product) is only a four-step seed, with no team activity, no spec template and no architecture practice
- `lesson-title-sync-on-install` — Re-importing a lesson fixture never updates the lesson's title, so live course 3 still shows the old titles
- `lessons-one-page-per-lesson` — The instructor's Lessons section stacks every lesson's full card, the course plan's readiness table and the answer keys on one page
- `no-button-to-recheck-site-links` — Add a "re-check all links" button for a round
- `onboarding-guide-has-todo-sections` — ONBOARDING.md still has _TODO_ under Team Tips and Get Started
- `peer-round-scores-never-reach-the-gradebook` — Peer-review round scores have to be copied into the gradebook by hand
- `project-bonus-has-no-editor` — The per-student project bonus can't be edited directly
- `readme-describes-a-localhost-only-app` — README still says "no login, localhost-only" and leaves out recent features
- `retire-bonus-points-phase-2-drop-column` — enrollments.bonus_points is zeroed but still in the schema
- `roster-cannot-be-edited-per-student` — Add, remove, withdraw or fix a single student without re-importing the roster
- `roster-reimport-email-conflicts-are-not-shown` — Roster re-import reports email conflicts that the UI never shows
- `student-portal-is-one-long-scroll` — The student portal is one long scroll with no navigation
- `students-cannot-see-their-own-grades` — Students cannot see their own grades, feedback or attendance status
- `students-need-an-assignment-page` — Students have no page for an assignment
- `suggest-rubrics-per-assignment-from-clusters` — Suggest a rubric for a new assignment from clusters of past rubrics
- `team-formation-closes-at-a-deadline` — Let students form their own teams until a deadline, then lock teams automatically
- `unreleasing-a-peer-round-keeps-its-gradebook-scores` — Un-releasing a peer round leaves its applied scores in the gradebook
- `unteamed-students-need-instructor-approved-auto-assign` — After teams lock, propose teams for unteamed students and apply them only on the instructor's approval
