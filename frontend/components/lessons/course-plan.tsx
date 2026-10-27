'use client';

import { ChangeEvent, useCallback, useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { apiGet, apiPatch, apiPost, errorMessage } from '@/lib/api';

/* The whole course as drafts, instructor side: import a course plan (every
 * session's topic, presentation round or final part, and a draft lesson for
 * it), see each lesson's readiness, and load the private answer keys.
 *
 * Readiness keeps five states apart — drafted, reviewed, runnable, published,
 * live verified — and never sums them into one "ready". Answer keys and the
 * instructor contact are private: they are uploaded from the instructor's own
 * file, stored in the database, and never shown here or sent to students. */

type CourseInfo = { id: number; code: string; name: string; year: number; semester: string };

type KeyCount = { version_number: number; needed: number; missing: string[] } | null;
export type AnswerKeyStatus = { latest: KeyCount; live: KeyCount };

type PlanLesson = {
  id: number;
  slug: string;
  title: string;
  status: 'draft' | 'published' | 'archived';
  latest_version: number | null;
  published_version: number | null;
  answer_keys: AnswerKeyStatus;
};

type PlanSession = {
  session: number;
  title: string;
  presentation_round: number | null;
  final_presentation_part: number | null;
  formal_presentations: boolean;
  planned_presenting_teams: number | null;
  lesson_slug: string;
  fixture_key: string;
  lesson: PlanLesson | null;
  existing_lessons: PlanLesson[];
  content_status: string | null;
  checks: string[];
  homework: { status: string | null; text: string | null } | null;
  readiness: {
    drafted: boolean;
    reviewed_at: string | null;
    runnable: { state: 'not_built' | 'prepared_not_rerun' | 'unknown'; note: string };
    published: boolean;
    live_verified_at: string | null;
    handoff_says_taught: boolean;
    available: string[];
    still_needed: string[];
  };
};

type PlanInfo = {
  code: string;
  title: string;
  academic_year: string;
  semester: string;
  session_count: number;
  matches_course: boolean;
  syllabus_grading: {
    final_project_and_presentation_percent: number;
    milestones_and_labs_percent: number;
    theoretical_quiz_percent: number;
    passing_score: number;
  };
};

type PlanView = { plan_code: string | null; plans: PlanInfo[]; sessions: PlanSession[] };

type KeysView = {
  instructor_contact_set: boolean;
  stored_keys: number;
  lessons: ({ lesson_id: number; slug: string } & AnswerKeyStatus)[];
};

type ImportResult = {
  keys: number;
  added: number;
  replaced: number;
  unchanged: number;
  lessons: string[];
  not_in_file: string[]; // "<slug>/<key>" or a plan lesson's "<slug>": left as they are
  instructor_contact: 'set' | 'unchanged' | 'not in file';
  dry_run: boolean;
};

function fmtDay(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : '';
}

function presentations(s: PlanSession): string {
  if (s.final_presentation_part) return `Finals, part ${s.final_presentation_part}`;
  if (s.presentation_round) return `Round ${s.presentation_round}`;
  return s.formal_presentations ? 'Presentations' : 'No formal presentations';
}

function keysLabel(status: AnswerKeyStatus | undefined): { text: string; pill: string; title: string } {
  const latest = status?.latest;
  if (!latest) return { text: '—', pill: 'pill', title: 'Not installed' };
  if (!latest.needed) return { text: 'none needed', pill: 'pill', title: 'No question needs a key' };
  if (!latest.missing.length) return { text: `${latest.needed}/${latest.needed} loaded`, pill: 'pill pill-ok', title: '' };
  return {
    text: `${latest.missing.length} of ${latest.needed} missing`,
    pill: 'pill pill-warn',
    title: `No key loaded for: ${latest.missing.join(', ')}`
  };
}

/* =============== Course plan =============== */

export function CoursePlanCard({
  courseId,
  course,
  reloadLessons,
  setToast
}: {
  courseId: number;
  course: CourseInfo;
  reloadLessons: () => Promise<void>;
  setToast: (m: string) => void;
}) {
  const base = `/api/courses/${courseId}/plan`;
  const [view, setView] = useState<PlanView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const load = useCallback(async () => {
    setView(await apiGet<PlanView>(base));
    setError(null);
  }, [base]);
  useEffect(() => {
    void load().catch((e) => setError(errorMessage(e)));
  }, [load]);

  if (error && !view) {
    return (
      <Card>
        <div className="label-eyebrow mb-1">Course plan</div>
        <p className="text-[14px] text-ink-2">{error}</p>
        <p className="mt-1 text-[13px] text-ink-3">
          If the server was just updated, its database may still need migration 0026_course_plan_answer_keys.
        </p>
      </Card>
    );
  }
  if (!view || !view.plans.length) return null;

  const plan = view.plans.find((p) => p.code === view.plan_code) ?? view.plans.find((p) => p.matches_course) ?? view.plans[0];
  const imported = view.plan_code === plan.code && view.sessions.length > 0;
  const mismatch = !plan.matches_course;
  const g = plan.syllabus_grading;

  const runImport = async () => {
    const what = imported
      ? `Load the plan’s changes into ${course.code}?\n\nChanged lessons get a new draft version; published versions never change.`
      : `Import the ${plan.code} plan into ${course.code} · ${course.name} · ${course.year} / ${course.semester}?\n\n` +
        `${plan.session_count} lessons are installed as drafts. Nothing is published, and the grade formula is not changed.`;
    if (!window.confirm(what)) return;
    setBusy(true);
    try {
      const result = await apiPost<PlanView & { installs: { action: string }[] }>(`${base}/import`, {
        plan_code: plan.code,
        allow_course_mismatch: mismatch && confirmed
      });
      setView(result);
      const created = result.installs.filter((i) => i.action === 'create').length;
      const changed = result.installs.filter((i) => i.action === 'update_draft' || i.action === 'new_version').length;
      setToast(`Plan imported: ${created} new draft lesson(s), ${changed} updated, nothing published`);
    } catch (e) {
      setToast(errorMessage(e));
    }
    setBusy(false);
    await reloadLessons().catch(() => undefined);
  };

  const mark = async (n: number, body: { reviewed?: boolean; live_verified?: boolean }) => {
    try {
      setView(await apiPatch<PlanView>(`${base}/sessions/${n}`, body));
    } catch (e) {
      setToast(errorMessage(e));
    }
  };

  return (
    <Card className="grid gap-3" data-testid="course-plan">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="label-eyebrow mb-1">
            Course plan · <span className="font-mono normal-case">{plan.code}</span>
          </div>
          <h2 className="font-display text-[24px] leading-tight">
            <span dir="rtl">{plan.title}</span>
          </h2>
          <div className="mt-1 text-[13px] text-ink-3">
            {plan.session_count} sessions · {plan.academic_year} · semester {plan.semester} · from the course-content handoff
          </div>
        </div>
        <Button size="sm" disabled={busy || (mismatch && !confirmed)} onClick={() => void runImport()}>
          {imported ? 'Load plan changes into drafts' : `Import ${plan.session_count} lessons as drafts`}
        </Button>
      </div>

      {mismatch ? (
        <label className="flex items-start gap-2 rounded-md bg-warn-soft px-3 py-2.5 text-[13px]">
          <input type="checkbox" className="mt-0.5" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>
            I checked: this plan, written for course <b>{plan.code}</b>, belongs in <b>{course.code}</b> ({course.name},{' '}
            {course.year} / {course.semester}).
          </span>
        </label>
      ) : null}

      <div className="hint">
        <span className="hint-icon">i</span>
        <div>
          Every lesson comes in as a <strong className="text-ink">draft</strong>; publishing stays your decision, lesson by
          lesson. The plan has no dates, times, rooms, team names, presentation slots or deadlines — those aren’t decided
          in it, so none are shown or created. The written syllabus weighs the grade {g.final_project_and_presentation_percent}%
          project/presentation, {g.milestones_and_labs_percent}% milestones/labs, {g.theoretical_quiz_percent}% theoretical
          quiz (passing {g.passing_score}); importing <strong className="text-ink">does not change</strong> this course’s
          grade formula.
        </div>
      </div>

      {imported ? <ReadinessTable courseId={courseId} sessions={view.sessions} mark={mark} /> : null}
    </Card>
  );
}

function ReadinessTable({
  courseId,
  sessions,
  mark
}: {
  courseId: number;
  sessions: PlanSession[];
  mark: (n: number, body: { reviewed?: boolean; live_verified?: boolean }) => Promise<void>;
}) {
  const th = 'px-2.5 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-3';
  const td = 'px-2.5 py-2 align-top text-[13px]';
  return (
    <div>
      <h3 className="mb-1 font-semibold">Schedule and readiness</h3>
      <p className="mb-2 text-[13px] text-ink-3">
        Five separate states, never one “ready”: <b>drafted</b> (a lesson version exists), <b>reviewed</b> (you checked
        the content), <b>runnable</b> (what the handoff says about runnable material), <b>published</b> (students can open
        it) and <b>live verified</b> (you checked it live with students).
      </p>
      <div className="overflow-x-auto rounded-md border border-line-soft">
        <table className="w-full min-w-[1080px] border-collapse" aria-label="Lesson readiness">
          <thead>
            <tr className="border-b border-line-soft bg-paper-2">
              <th scope="col" className={th}>Session</th>
              <th scope="col" className={th}>Topic</th>
              <th scope="col" className={th}>Presentations</th>
              <th scope="col" className={th}>Lesson</th>
              <th scope="col" className={th}>Drafted</th>
              <th scope="col" className={th}>Reviewed</th>
              <th scope="col" className={th}>Runnable</th>
              <th scope="col" className={th}>Published</th>
              <th scope="col" className={th}>Live verified</th>
              <th scope="col" className={th}>Answer keys</th>
              <th scope="col" className={th}>Still needed</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => {
              const r = s.readiness;
              const keys = keysLabel(s.lesson?.answer_keys);
              return (
                <tr key={s.session} className="border-b border-line-soft last:border-b-0" data-session={s.session}>
                  <td className={`${td} font-semibold`}>{s.session}</td>
                  <td className={td}>
                    <span dir="rtl" className="block">
                      {s.title}
                    </span>
                  </td>
                  <td className={td}>
                    {presentations(s)}
                    {s.planned_presenting_teams ? (
                      <div className="text-[12px] text-ink-3">{s.planned_presenting_teams} teams planned</div>
                    ) : null}
                  </td>
                  <td className={td}>
                    {s.lesson ? (
                      <a
                        className="font-mono text-[12px] text-forest hover:underline"
                        href={`/course/${courseId}/lessons/${s.lesson.id}/preview`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {s.lesson.slug} ↗
                      </a>
                    ) : (
                      <span className="font-mono text-[12px] text-ink-3">{s.lesson_slug}</span>
                    )}
                    {s.existing_lessons.map((l) => (
                      <div key={l.id} className="mt-1 text-[12px] text-ink-3">
                        also the existing lesson <span className="font-mono">{l.slug}</span> ({l.status}
                        {l.published_version ? `, v${l.published_version} live` : ''})
                      </div>
                    ))}
                  </td>
                  <td className={td}>
                    {r.drafted ? (
                      <span className="pill">✓ v{s.lesson?.latest_version}</span>
                    ) : (
                      <span className="text-ink-3">not imported</span>
                    )}
                  </td>
                  <td className={td}>
                    <label className="flex items-center gap-1.5">
                      <input
                        type="checkbox"
                        checked={!!r.reviewed_at}
                        aria-label={`Session ${s.session} reviewed`}
                        onChange={(e) => void mark(s.session, { reviewed: e.target.checked })}
                      />
                      <span className={r.reviewed_at ? '' : 'text-ink-3'}>{r.reviewed_at ? fmtDay(r.reviewed_at) : 'no'}</span>
                    </label>
                  </td>
                  <td className={td}>
                    <span
                      className={r.runnable.state === 'not_built' ? 'pill pill-warn' : 'pill'}
                      title={r.runnable.note}
                    >
                      {r.runnable.state === 'not_built'
                        ? 'not built'
                        : r.runnable.state === 'prepared_not_rerun'
                          ? 'prepared, not re-run'
                          : 'unknown'}
                    </span>
                  </td>
                  <td className={td}>
                    {r.published ? (
                      <span className="pill pill-forest">v{s.lesson?.published_version} live</span>
                    ) : (
                      <span className="text-ink-3">no</span>
                    )}
                  </td>
                  <td className={td}>
                    <label className="flex items-center gap-1.5">
                      <input
                        type="checkbox"
                        checked={!!r.live_verified_at}
                        aria-label={`Session ${s.session} live verified`}
                        onChange={(e) => void mark(s.session, { live_verified: e.target.checked })}
                      />
                      <span className={r.live_verified_at ? '' : 'text-ink-3'}>
                        {r.live_verified_at ? fmtDay(r.live_verified_at) : 'no'}
                      </span>
                    </label>
                    {!r.handoff_says_taught ? <div className="text-[11px] text-ink-3">handoff: not verified taught</div> : null}
                  </td>
                  <td className={td}>
                    <span className={keys.pill} title={keys.title}>
                      {keys.text}
                    </span>
                  </td>
                  <td className={`${td} max-w-[260px] text-[12px] text-ink-2`}>
                    {r.still_needed.length ? (
                      <ul className="list-disc pl-4">
                        {r.still_needed.map((x) => (
                          <li key={x}>{x}</li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-ink-3">nothing listed</span>
                    )}
                    {s.homework?.status && s.homework.status !== 'existing_assignment' ? (
                      <div className="mt-1 text-ink-3">homework: {s.homework.status.replace(/_/g, ' ')}</div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* =============== Private answer keys =============== */

export function AnswerKeysCard({
  courseId,
  reloadLessons,
  setToast
}: {
  courseId: number;
  reloadLessons: () => Promise<void>;
  setToast: (m: string) => void;
}) {
  const base = `/api/courses/${courseId}/answer-keys`;
  const [status, setStatus] = useState<KeysView | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => setStatus(await apiGet<KeysView>(base)), [base]);
  useEffect(() => {
    void load().catch(() => undefined);
  }, [load]);

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // the file's content is never kept in the page
    if (!file) return;
    setErrors([]);
    setBusy(true);
    try {
      let data: unknown;
      try {
        data = JSON.parse(await file.text());
      } catch {
        setErrors(['The file is not valid JSON.']);
        return;
      }
      const check = await postKeys(`${base}?dry_run=true`, data, setErrors);
      if (!check) return;
      const ok = window.confirm(
        `Store ${check.keys} answer key(s) for ${check.lessons.length} lesson(s) in this course?\n\n` +
          `${check.added} new, ${check.replaced} replaced, ${check.unchanged} unchanged. ` +
          `Instructor contact: ${check.instructor_contact}.\n\n` +
          (check.not_in_file.length
            ? `Not in the file (left as they are): ${check.not_in_file.join(', ')}\n\n`
            : '') +
          'Students see feedback only after they answer.'
      );
      if (!ok) return;
      const stored = await postKeys(base, data, setErrors);
      if (stored) setToast(`${stored.keys} answer key(s) stored (${stored.added} new, ${stored.replaced} replaced)`);
    } finally {
      setBusy(false);
      await load().catch(() => undefined);
      await reloadLessons().catch(() => undefined);
    }
  };

  const missing = (status?.lessons ?? []).filter((l) => l.latest?.missing.length || l.live?.missing.length);

  return (
    <Card className="grid gap-3" data-testid="answer-keys">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="label-eyebrow mb-1">Private answer keys</div>
          <h3 className="font-display text-[20px] leading-tight">Answer keys and instructor contact</h3>
          <p className="mt-1 max-w-3xl text-[13px] text-ink-2">
            The app’s code is public, so answer keys and the instructor’s email are never part of it. Import the private
            JSON file here (or with <span className="font-mono">scripts/load_answer_keys.py</span>): every key is checked
            against the lessons first, and one bad entry stores nothing. Keys are never shown on this page, and students
            see feedback only after they answer.
          </p>
        </div>
        <div>
          <input
            ref={input}
            type="file"
            accept="application/json,.json"
            className="hidden"
            aria-label="Private answer-key file"
            onChange={(e) => void onFile(e)}
          />
          <Button size="sm" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
            {busy ? 'Checking…' : 'Import private answer keys…'}
          </Button>
        </div>
      </div>

      {status ? (
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <span className="pill">{status.stored_keys} key(s) stored</span>
          <span className={status.instructor_contact_set ? 'pill pill-ok' : 'pill'}>
            instructor contact {status.instructor_contact_set ? 'set' : 'not set'}
          </span>
          {missing.length ? (
            <span className="pill pill-warn">
              {missing.length} lesson(s) with questions that can’t be checked:{' '}
              {missing.map((l) => l.slug).join(', ')}
            </span>
          ) : status.lessons.length ? (
            <span className="pill pill-ok">every installed lesson has its keys</span>
          ) : null}
        </div>
      ) : null}

      {errors.length ? (
        <div className="hint hint-warm" role="alert">
          <span className="hint-icon">!</span>
          <div>
            <div className="font-semibold text-ink">The file has errors; nothing was stored:</div>
            <ul className="mt-1 list-disc pl-5">
              {errors.map((err, i) => (
                <li key={i} className="font-mono text-[12px]">
                  {err}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

async function postKeys(path: string, data: unknown, setErrors: (e: string[]) => void): Promise<ImportResult | null> {
  try {
    return await apiPost<ImportResult>(path, data);
  } catch (e) {
    let errors: string[] = [];
    try {
      errors = JSON.parse(e instanceof Error ? e.message : '')?.detail?.errors ?? [];
    } catch {
      /* not the API's JSON */
    }
    setErrors(errors.length ? errors : [errorMessage(e)]);
    return null;
  }
}
