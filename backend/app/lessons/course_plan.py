"""A whole course's plan, built from a course-content handoff: one session per
topic slot (title, presentation round or final part, the draft lesson that
teaches it) plus each lesson's readiness as the handoff states it.

The handoff lives outside the app (content/course-<code>/ at the repository
root, which the hosted API bundle does not include). build_plan() converts it
into files under app/lessons/content/course-<code>/: plan.json and one lesson
fixture per session, in the same LessonContent schema as every other lesson.
scripts/build_course_plan.py writes them; a test checks they match the
handoff. The handoff's private fields (answer keys, instructor email) are not
in the repository, so neither are they in anything built here.

Nothing here invents course facts: no dates, times, rooms, teams, slots,
deadlines or weights. Fields the handoff leaves open stay out.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PLAN_FORMAT = 1

# Latin runs inside Hebrew (Python, CSV, AI API, tree_depth) are kept LTR.
_TOKEN = r"[A-Za-z](?:[A-Za-z0-9_+#/.\-]*[A-Za-z0-9+#])?"
_LATIN_RUN = re.compile(rf"{_TOKEN}(?:[ ]+{_TOKEN})*")

# Hebrew labels for the parts of a seed. Interface wording only: they name
# what the handoff supplies and add no course content.
_LABELS = {
    "prerequisites": "מה צריך לפני שמתחילים",
    "goal": "מטרת השיעור",
    "wrap_title": "מסכמים",
    "worked_example": "דוגמה פתורה",
    "exit_check": "לסיום: במילים שלכם",
    "exit_check_help": "תשובה קצרה, משפט או שניים. אין כאן ציון – זה עוזר לכם (ולמרצה) לראות מה התבהר.",
    "work_product": "התוצר של השיעור",
    "extension": "להעמקה (רשות)",
    "homework": "מטלה",
}

# The exit question's section: a title and one line under it (operator rule,
# 2026-11-03: each lesson asks its own concrete question, not a generic one).
EXIT_CHECK_TITLE = _LABELS["exit_check"]
EXIT_CHECK_HELP = _LABELS["exit_check_help"]

_LETTERS = "ABCDEFGHIJ"


def ltr(text: str) -> str:
    """Hebrew text with each Latin run wrapped as [[ltr]] (seeds carry no markup)."""
    return _LATIN_RUN.sub(lambda m: f"[[{m.group(0)}]]", text)


def _text(*paragraphs: str) -> dict:
    return {"type": "text", "body": [ltr(p) for p in paragraphs]}


def _assets_root() -> Path:
    from app.lessons import ASSETS_ROOT  # imported here: app.lessons imports this module

    return ASSETS_ROOT


def _download(asset: str, label: str) -> dict:
    return {"type": "download", "asset": asset, "label": label}


def _colab(asset: str, lead: str, executed: str | None = None) -> list[dict]:
    """The step's notebook as a Colab block; the lead (shown above its button)
    says what to do in this notebook for this step. An executed copy, if any,
    is offered for reading below it."""
    blocks: list[dict] = [
        {
            "type": "colab",
            "notebook_asset": asset,
            "lead": ltr(lead),
            "instructions": [
                ltr("הורידו את המחברת (הכפתור למטה), פתחו את colab.research.google.com, בחרו Upload והעלו את הקובץ."),
                ltr("מריצים תא בלחיצה על ▶, תא אחרי תא לפי הסדר. מעבד רגיל (CPU) מספיק."),
            ],
            "return_note": "חזרו ללשונית הזו – המקום שלכם נשמר",
        },
    ]
    if executed:
        blocks.append(
            {
                "type": "expander",
                "title": "אין גישה לקולאב?",
                "blocks": [
                    {
                        "type": "download",
                        "asset": executed,
                        "label": "העותק המורץ של המחברת (ipynb)",
                        "description": "פלט אמיתי מהרצה שלנו, לקריאה.",
                    }
                ],
            }
        )
    return blocks


def seed_to_content(
    seed: dict,
    course_code: str,
    assets: dict[str, dict] | None = None,
    downloads: dict[str, list[dict]] | None = None,
) -> dict:
    """One lesson seed (content/course-<code>/lessons/lesson-NN.json) as
    LessonContent. Each seed step becomes a step: understand, try, check. A
    last step holds the worked example and an exit question (free text,
    recorded and never graded). The check's answer key is not in the seed and
    is not added here.

    assets/downloads attach files the handoff already prepared: assets by
    key, downloads by step key (download or Colab blocks for the step's try
    section)."""
    downloads = downloads or {}
    questions: dict[str, dict] = {}
    steps: list[dict] = []
    for i, step in enumerate(seed["steps"]):
        check = step["check"]
        if check.get("kind") != "single_choice":
            raise ValueError(f"{seed['slug']}: check {check.get('key')} is not single_choice")
        questions[check["key"]] = {
            "key": check["key"],
            "step": step["key"],
            # check: no reveal before the first answer, so the right option is
            # never sent before an attempt; retries stay open (formative).
            "mode": "check",
            "prompt": ltr(check["prompt_he"]),
            "type": "single_choice",
            "options": [{"id": c["id"], "text": ltr(c["text_he"])} for c in check["choices"]],
        }
        blocks: list[dict] = []
        if i == 0 and seed.get("prerequisites_he"):
            blocks.append(
                {
                    "type": "callout",
                    "tone": "info",
                    "title": _LABELS["prerequisites"],
                    "body": [ltr("; ".join(seed["prerequisites_he"]))],
                }
            )
        try_blocks = [_text(step["do_he"]), *downloads.get(step["key"], [])]
        blocks += [
            {"type": "section", "label": "understand", "blocks": [_text(step["understand_he"])]},
            {"type": "section", "label": "try", "blocks": try_blocks},
            {"type": "section", "label": "check", "blocks": [{"type": "question", "question": check["key"]}]},
        ]
        steps.append(
            {
                "key": step["key"],
                "letter": _LETTERS[i],
                "title": ltr(step["title_he"]),
                "blocks": blocks,
                "completion": [{"type": "answered", "question": check["key"]}],
            }
        )

    exit_key = f"{seed['slug']}-exit"
    questions[exit_key] = {
        "key": exit_key,
        "step": "wrap-up",
        "mode": "check",
        "prompt": ltr(seed["exit_check_he"]),
        "type": "free_text",
        "min_chars": 10,
    }
    wrap: list[dict] = [
        {"type": "callout", "tone": "note", "title": _LABELS["worked_example"], "body": [ltr(seed["worked_example_he"])]},
        {
            "type": "section",
            "label": "check",
            "title": _LABELS["exit_check"],
            "blocks": [_text(_LABELS["exit_check_help"]), {"type": "question", "question": exit_key}],
        },
        {"type": "callout", "tone": "info", "title": _LABELS["work_product"], "body": [ltr(seed["work_product_he"])]},
    ]
    # Only an assignment that already exists is shown; a proposal is not
    # assigned and stays in the instructor's readiness view.
    if seed.get("homework_status") == "existing_assignment" and seed.get("homework_he"):
        wrap.append({"type": "callout", "tone": "info", "title": _LABELS["homework"], "body": [ltr(seed["homework_he"])]})
    if seed.get("optional_extension_he"):
        wrap.append({"type": "expander", "title": _LABELS["extension"], "blocks": [_text(seed["optional_extension_he"])]})
    steps.append(
        {
            "key": "wrap-up",
            "letter": _LETTERS[len(steps)],
            "title": _LABELS["wrap_title"],
            "blocks": wrap,
            "completion": [{"type": "answered", "question": exit_key}],
        }
    )
    return {
        "schema_version": 1,
        "slug": seed["slug"],
        "title": seed["title_he"],
        "guiding_question": ltr(seed["learning_goal_he"]),
        "course_code": course_code,
        "assets": assets or {},
        "steps": steps,
        "questions": questions,
    }


# Files the handoff prepared for lessons 1 and 2, attached as downloads. The
# lesson-2 files are the ones the live lesson-2 fixture already serves
# (identical sha256); lesson 1's notebook is copied to frontend/public.
_PREPARED: dict[str, dict] = {
    "lesson-01": {
        # The handoff's notebook spans the whole lesson (problem, chatbot
        # approaches, the calculator, sharing, wrap-up). Step B gets a notebook
        # of its own, built from it by scripts/build_step_notebooks.py: only
        # the calculator sections (3-6 and the optional automatic check, 8).
        "assets": {
            "notebook_b": {
                "built": True,
                "path": "/lessons/lesson-01/v2/lesson-1-b-dessert-calculator-he.ipynb",
                "filename": "lesson-1-b-dessert-calculator-he.ipynb",
                "mime": "application/x-ipynb+json",
                "label": "מחברת שלב B: מחשבון דוכן הקינוחים (ipynb)",
            },
            "notebook_b_executed": {
                "built": True,
                "path": "/lessons/lesson-01/v2/lesson-1-b-dessert-calculator-he-executed.ipynb",
                "filename": "lesson-1-b-dessert-calculator-he-executed.ipynb",
                "mime": "application/x-ipynb+json",
                "label": "מחברת שלב B – עותק מורץ (ipynb)",
            },
        },
        "colab": {
            "dessert": (
                "notebook_b",
                "הריצו את התאים לפי הסדר; בתא «מחשבון דוכן קינוחים» שנו את הכמות ל-100, 66 ו-67 ואז לכמות שלילית, ובדקו את הרווח.",
                "notebook_b_executed",
            )
        },
    },
    "lesson-02": {
        "assets": {
            "csv": {
                "source": "materials/lesson-02/assets/lesson2-customer-data.csv",
                "path": "/lessons/lesson-2/v1/lesson2-customer-data.csv",
                "filename": "lesson2-customer-data.csv",
                "mime": "text/csv",
                "label": "טבלת הלקוחות לתרגול (CSV)",
            },
            "notebook": {
                "source": "materials/lesson-02/notebooks/lesson-2-machine-learning-he.ipynb",
                "path": "/lessons/lesson-2/v1/lesson-2-machine-learning-he.ipynb",
                "filename": "lesson-2-machine-learning-he.ipynb",
                "mime": "application/x-ipynb+json",
                "label": "מחברת שיעור 2 (ipynb)",
            },
        },
        "downloads": {"inspect": ["csv", "notebook"]},
    },
}

# Lessons authored in this repository: an expanded student flow written from
# the seed (more steps, runnable material, exercises), not generated from it.
# build_plan leaves their fixture alone (it is not stale against the seed), and
# a test checks that the seed's checks, worked example, exit check and work
# product survive in it unchanged. "runnable" is what this repository built and
# ran; the instructor's own review is still the reviewed/live-verified marks.
AUTHORED: dict[str, dict] = {
    "lesson-03": {
        "runnable": "Two required parts (lesson-03, then lesson-03-deeper), each with a Colab notebook built and "
        "executed end to end in this repository on CPU, no API key or paid service (part 1: a neuron, a tiny "
        "network trained, real embeddings; part 2: real tokenizers, a small open model's next-token "
        "probabilities and measured attention, grounding checks); not yet run by the instructor in Colab",
    },
    "lesson-04": {
        "runnable": "Starter web app (zip) built here; its check (node check.js, and check.html in a browser) runs "
        "in CI with the documented output. The Google Antigravity steps were checked against Google's docs on "
        "2026-11-03 but not run in Antigravity, here or by the instructor",
        # The seed's homework proposal adapted to the lesson's tool; still a
        # proposal (instructor's readiness table only, no deadline or weight).
        "homework_he": "הצעה: בצוות, יישמו שינוי קטן אחד בתיקייה או במאגר של הפרויקט שלכם בעזרת Google Antigravity, "
        "ותעדו תוכנית, נקודת שמירה, שינוי, diff, הרצה ובדיקה. אין להניח גישה חינמית או רישיון לכל ספק.",
    },
    "lesson-05": {
        "runnable": "SPEC.md template (download, sha256 in the lesson's assets) and an in-browser architecture-map "
        "self-check, built and tested here. The agent's spec interview in Google Antigravity was not run, here "
        "or by the instructor; AI API access is left to lesson 7",
        # The syllabus milestone (project proposal + spec), as a proposal for
        # the instructor's readiness table only: no deadline, weight or route.
        "homework_he": "הצעת פרויקט + SPEC.md (לפי התבנית)",
    },
    "lesson-06": {
        "runnable": "README template and a one-page team git routine (downloads, sha256 in the lesson's assets) built "
        "and tested here. The agent's scaffolding in Google Antigravity, the GitHub push/clone round and the "
        "fresh-clone run were not run, here or by the instructor; the GitHub steps follow GitHub's docs, checked "
        "on 2026-11-03",
        # A proposal for the instructor's readiness table only: no deadline,
        # weight or submission route.
        "homework_he": "שלד עובד + README + קישור למאגר",
    },
    "lesson-07": {
        "runnable": "Reference implementation (zip, sha256 in the lesson's assets) whose mock check (node check.js: "
        "15 checks, no network, no key) runs in CI, and a .env.example download, built and tested here. The live "
        "Gemini API call follows Google's docs (checked 2026-11-04) and reached the API only with an invalid key, "
        "which it rejected as expected; it was not run with a real key, here or by the instructor. The agent steps "
        "in Google Antigravity were not run",
        # A proposal for the instructor's readiness table only: no deadline,
        # weight or submission route.
        "homework_he": "תכונת AI אחת מקצה לקצה + בדיקת פלט + תרחיש כשל",
    },
}

# Sessions taught in more than one REQUIRED lesson: the session's own lesson
# is part 1, and these follow it in order (part 2, ...). Authored in this
# repository, installed as drafts with the plan right after the session's
# lesson. Slugs of fixtures in content/course-<code>/. Session 3: part 1
# lesson-03 (neurons, training, embeddings), part 2 lesson-03-deeper (how a
# language model writes).
_PARTS: dict[int, list[str]] = {3: ["lesson-03-deeper"]}

# A session whose topic an installed fixture already teaches (the live lesson
# 2, "from-data-to-prediction", fixture key lesson-2).
_EXISTING_FIXTURES = {2: ["lesson-2"]}


def fixture_key(code: str, slug: str) -> str:
    return f"{code}-{slug}"


def build_plan(handoff: Path) -> tuple[dict, dict[str, dict], dict[str, Path]]:
    """(plan, lesson contents by slug, public files to copy: site path ->
    handoff file) from a handoff directory. An AUTHORED lesson has no
    generated content: its fixture is the hand-written one."""
    import hashlib

    course = json.loads((handoff / "course.json").read_text(encoding="utf-8"))
    readiness = {r["lesson"]: r for r in json.loads((handoff / "readiness.json").read_text(encoding="utf-8"))}
    code = course["code"]
    seeds = {}
    for path in sorted((handoff / "lessons").glob("lesson-*.json")):
        seed = json.loads(path.read_text(encoding="utf-8"))
        seeds[seed["number"]] = seed

    contents: dict[str, dict] = {}
    copies: dict[str, Path] = {}
    lessons: dict[str, dict] = {}
    sessions: list[dict] = []
    for entry in course["schedule"]:
        number = entry["session"]
        seed = seeds[number]
        slug = seed["slug"]
        prepared = _PREPARED.get(slug, {})
        assets: dict[str, dict] = {}
        for key, spec in prepared.get("assets", {}).items():
            # "built": a file this repository builds itself (already in
            # frontend/public); otherwise a handoff file, copied there.
            source = _assets_root() / spec["path"].lstrip("/") if spec.get("built") else handoff / spec["source"]
            assets[key] = {
                "path": spec["path"],
                "filename": spec["filename"],
                "mime": spec["mime"],
                "label": spec["label"],
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            if not spec.get("built"):
                copies[spec["path"]] = source
        downloads = {
            step: [_download(a, assets[a]["label"]) for a in keys] for step, keys in prepared.get("downloads", {}).items()
        }
        for step, (asset, lead, *executed) in prepared.get("colab", {}).items():
            downloads.setdefault(step, []).extend(_colab(asset, lead, *executed))
        if slug not in AUTHORED:
            contents[slug] = seed_to_content(seed, code, assets, downloads)
        ready = readiness.get(number, {})
        lessons[slug] = {
            "number": number,
            "title": seed["title_he"],
            "content_status": seed["content_status"],
            "checks": [s["check"]["key"] for s in seed["steps"]],
            "readiness": {
                "status": ready.get("status"),
                "available": ready.get("available", []),
                "still_needed": ready.get("still_needed", []),
                "published_or_taught_verified": bool(ready.get("published_or_taught_verified")),
            },
            "homework": {
                "status": seed.get("homework_status"),
                "text": AUTHORED.get(slug, {}).get("homework_he", seed.get("homework_he")),
            },
        }
        if slug in AUTHORED:
            lessons[slug]["authored"] = {k: v for k, v in AUTHORED[slug].items() if k != "homework_he"}
        sessions.append(
            {
                "session": number,
                "title": entry["teaching_title_he"],
                "lesson_slug": slug,
                "fixture_key": fixture_key(code, slug),
                "existing_fixture_keys": _EXISTING_FIXTURES.get(number, []),
                "part_fixture_keys": [fixture_key(code, s) for s in _PARTS.get(number, [])],
                "presentation_round": entry["presentation_round"],
                "final_presentation_part": entry["final_presentation_part"],
                "formal_presentations": entry["formal_presentations"],
                "planned_presenting_teams": entry["planned_presenting_teams"],
            }
        )
    grading = course["grading"]
    plan = {
        "format": PLAN_FORMAT,
        "course_code": code,
        "title": course["title_he"],
        "academic_year": course["academic_year"],
        "semester": course["semester"],
        "session_count": course["session_count"],
        "source": f"content/course-{code}",
        "sessions": sessions,
        "lessons": lessons,
        # The written syllabus, for reference only: the app's grade formula is
        # not changed by importing a plan.
        "syllabus_grading": {
            "final_project_and_presentation_percent": grading["final_project_and_presentation_percent"],
            "milestones_and_labs_percent": grading["milestones_and_labs_percent"],
            "theoretical_quiz_percent": grading["theoretical_quiz_percent"],
            "passing_score": grading["passing_score"],
        },
    }
    return plan, contents, copies


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
