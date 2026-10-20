'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { InlineText, plainInline } from '@/components/lessons/inline';
import type { Answer, Commitment, DepthKind, Experiment, Progress, StepStatus } from '@/components/lessons/types';
import { BilingualName } from '@/components/ui/bilingual-name';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { apiBase, apiGet, apiPatch, apiPost, errorMessage } from '@/lib/api';

/* Guided lessons, instructor side: install the lesson file bundled with the
 * app into this course as a draft, preview any version exactly as students
 * get it (nothing is saved), publish or unpublish, set the Colab link, and see
 * where understanding breaks down. Three things stay apart in every label:
 * viewed (opened a step), completed (did its required actions; any answer
 * counts) and understood (only first-attempt answers speak to it). Students
 * are listed by name or status, never ranked by time, and saved activity is
 * never read as attendance. */

/* =============== Types =============== */

type CourseInfo = { id: number; code: string; name: string; year: number; semester: string };

type LessonStatus = 'draft' | 'published' | 'archived';
type VersionRow = {
  id: number;
  number: number;
  status: 'draft' | 'published';
  content_hash: string;
  created_at: string | null;
  published_at: string | null;
};
export type LessonSummary = {
  id: number;
  slug: string;
  title: string;
  status: LessonStatus;
  position: number;
  colab_url: string;
  fixture_key: string;
  active_version: { id: number; number: number; content_hash: string; published_at: string | null } | null;
  draft_version: { id: number; number: number; content_hash: string; created_at: string | null } | null;
  versions: VersionRow[]; // oldest first
  fixture_hash: string | null;
  fixture_update_available: boolean;
};
type FixtureRow = {
  key: string;
  slug: string | null;
  title: string | null;
  course_code: string | null;
  matches_course: boolean;
  installed_lesson_id: number | null;
  content_hash: string | null;
  valid: boolean;
  errors: string[];
};

type StudentStatus = 'not_started' | 'in_progress' | 'completed';
type StepStats = { key: string; letter: string; title: string; optional: boolean; viewed: number; completed: number };
type StudentRow = {
  student_id: number;
  name: string;
  is_test: boolean;
  withdrawn: boolean;
  status: StudentStatus;
  version_number: number | null;
  current_step_key: string | null;
  viewed_steps: number;
  completed_required: number;
  required_total: number;
  optional_completed: number;
  last_activity_at: string | null;
  experiments: number;
  committed: boolean;
  final_recorded: boolean;
  revised_after_final: boolean;
  free_text_answers: number;
  flagged: number;
};
type OptionStats = {
  id: string;
  text: string;
  correct: boolean;
  misconception: string | null;
  first_count: number;
  all_count: number;
};
type WrittenResponse = {
  attempt_id: number;
  student_id: number;
  name: string;
  text: string;
  choice?: string | null; // set when this is the explanation of a choice
  submitted_at: string | null;
  attempt_number: number;
  flagged: boolean;
};
type QuestionStats = {
  key: string;
  step: string;
  type: 'single_choice' | 'free_text';
  mode: 'practice' | 'check';
  prompt: string;
  answered: number;
  unanswered: number;
  first_correct: number;
  first_incorrect: number;
  attempts_after_feedback: number;
  revealed_before_answer: number;
  /** Answered, but only after revealing the reasoning: in `answered`, never in first_correct / first_incorrect or the bars. */
  answered_after_reveal: number;
  eventually_correct_after_wrong_first: number;
  /** Choices made on a different definition of this question (another version): left out of the bars. */
  other_version_answers: number;
  options: OptionStats[];
  free_text: WrittenResponse[];
};
type Insights = {
  lesson: LessonSummary;
  totals: {
    enrolled: number;
    not_started: number;
    in_progress: number;
    completed: number;
    excluded_test: number;
    withdrawn: number;
  };
  steps: StepStats[];
  students: StudentRow[];
  questions: QuestionStats[];
};
type DetailAttempt = {
  id: number;
  question_key: string;
  step_key: string;
  kind: 'answer' | 'reveal';
  attempt_number: number;
  answer: Answer | null;
  correct: boolean | null;
  after_feedback: boolean;
  submitted_at: string | null;
  review_flag: boolean;
  /** Made against another definition of the question than the one shown here (another version). */
  question_changed: boolean;
};
type DetailExperiment = Experiment & {
  deleted_at: string | null;
  /** The prediction as first saved; later edits change `hypothesis` only. */
  first_hypothesis: string | null;
  first_hypothesis_at: string | null;
};
type StudentDetail = {
  student: { id: number; name: string; is_test: boolean; withdrawn: boolean };
  /** From the current evidence (completed_at is only when they first finished). */
  status: StudentStatus;
  progress: Progress | null;
  version_number: number | null;
  steps: Record<string, StepStatus> | null;
  attempts: DetailAttempt[];
  experiments: DetailExperiment[];
  commitments: Commitment[];
};

type Run = (fn: () => Promise<unknown>, success?: string) => Promise<void>;
type FlagFn = (attemptId: number, studentId: number, flagged: boolean) => Promise<boolean | null>;

const LESSON_STATUS_PILL: Record<LessonStatus, string> = {
  draft: 'pill',
  published: 'pill pill-forest',
  archived: 'pill pill-warn'
};

const STUDENT_STATUS: Record<StudentStatus, { label: string; pill: string; order: number }> = {
  not_started: { label: 'not started', pill: 'pill', order: 0 },
  in_progress: { label: 'in progress', pill: 'pill pill-info', order: 1 },
  completed: { label: 'completed actions', pill: 'pill pill-ok', order: 2 }
};

const COLAB_HOSTS = ['colab.research.google.com', 'drive.google.com'];
const AUTO_REFRESH_MS = 30_000;

/* =============== Helpers =============== */

// English dates on this English (LTR) page: a Hebrew-locale browser's format
// would be reordered by the bidi algorithm ("20 14:57 ,2026 באוק׳").
function fmtDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—';
}
function fmtShortDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString('en-GB', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—';
}
function shortHash(hash: string | null | undefined): string {
  return hash ? hash.slice(0, 8) : '—';
}
function share(n: number, of: number): string {
  return of > 0 ? `${Math.round((n / of) * 100)}%` : '—';
}
/** A stored fraction 0..1 as the percentage students entered. */
function pct(v: number | null | undefined): string {
  return v == null ? '—' : `${Math.round(v * 1000) / 10}%`;
}
function depthText(kind: DepthKind | null, depth: number | null): string {
  if (kind === 'unlimited') return 'unlimited depth (0 in Colab)';
  if (kind === 'limited' && depth != null) return `depth ${depth}`;
  return 'depth not set';
}
/** Students whose first answer came before any feedback — the only independent ones. */
function independent(q: QuestionStats): number {
  return q.answered - q.answered_after_reveal;
}
function firstTryRate(q: QuestionStats): number | null {
  return q.type === 'single_choice' && independent(q) > 0 ? q.first_correct / independent(q) : null;
}
/** Lowest first-try share first; free-text and unanswered questions last, in lesson order. */
function worstFirst(a: QuestionStats, b: QuestionStats): number {
  const ra = firstTryRate(a);
  const rb = firstTryRate(b);
  if (ra == null || rb == null) return ra == null ? (rb == null ? 0 : 1) : -1;
  return ra - rb || independent(b) - independent(a);
}
/** The wrong choice most students picked on their first try, if any. */
function dominantWrong(q: QuestionStats): OptionStats | null {
  const wrong = q.options.filter((o) => !o.correct && o.first_count > 0);
  return wrong.sort((a, b) => b.first_count - a.first_count)[0] ?? null;
}

/** Same rule as the API (https, a Colab or Drive host, nothing else); null when fine. */
function colabUrlProblem(raw: string): string | null {
  if (raw.length > 1000) return 'The link is too long (1000 characters at most).';
  if (/\s/.test(raw)) return 'The link contains spaces.';
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return 'That isn’t a complete link — it should start with https://';
  }
  if (url.protocol !== 'https:') return 'Use an https:// link.';
  if (url.username || url.password) return 'Use a plain link, without a user name or password.';
  if (url.port || /^https:\/\/[^/?#@]*:\d*(?:[/?#]|$)/i.test(raw)) return 'Use a plain link, without a port number.';
  if (!COLAB_HOSTS.includes(url.hostname)) return 'Use a link on colab.research.google.com or drive.google.com.';
  return null;
}

function Th({ children, className = '', title }: { children?: React.ReactNode; className?: string; title?: string }) {
  return (
    <th title={title} className={`label-eyebrow border-b border-border px-3 py-2.5 text-left font-semibold ${className}`}>
      {children}
    </th>
  );
}
function Td({ children, className = '' }: { children?: React.ReactNode; className?: string }) {
  return <td className={`px-3 py-2.5 align-top ${className}`}>{children}</td>;
}
function TableCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-auto rounded-lg border border-border bg-card shadow-soft">
      <table className="w-full border-collapse text-[14px]">{children}</table>
    </div>
  );
}
function FragmentRows({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

/** A bar with its numbers beside it (the bar alone never carries the meaning). */
function Meter({ value, max, warm = false, label }: { value: number; max: number; warm?: boolean; label?: string }) {
  const width = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-2" title={label}>
      <div className={`progress-bar min-w-[56px] flex-1 ${warm ? 'warm' : ''}`} aria-hidden>
        <span style={{ width: `${width}%` }} />
      </div>
      <span className="tnum w-[46px] shrink-0 text-right text-[12px] text-ink-2">
        {value}/{max}
      </span>
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[13px] transition ${
        active ? 'bg-forest text-paper' : 'border border-border bg-card text-ink-2 hover:border-ink-4 hover:text-ink'
      }`}
    >
      {children}
    </button>
  );
}

function StepLabel({ step, fallback }: { step: StepStats | undefined; fallback: string }) {
  if (!step) return <span className="font-mono text-[12px]">{fallback}</span>;
  return (
    <span className="inline-flex min-w-0 max-w-full items-baseline gap-1.5" title={plainInline(step.title)}>
      <span className="shrink-0 font-semibold text-ink-2">{step.letter}</span>
      <span dir="rtl" className="min-w-0 truncate">
        <InlineText text={step.title} />
      </span>
    </span>
  );
}

/* =============== Step =============== */

export function LessonsStep({
  courseId,
  course,
  setToast
}: {
  courseId: number;
  course: CourseInfo;
  setToast: (m: string) => void;
}) {
  const base = `/api/courses/${courseId}/lessons`;
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null);
  const [fixtures, setFixtures] = useState<FixtureRow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(async () => {
    const [list, fx] = await Promise.all([apiGet<LessonSummary[]>(base), apiGet<FixtureRow[]>(`${base}/fixtures`)]);
    setLessons(list);
    setFixtures(fx);
    setLoadError(null);
    setSelected((cur) => {
      if (cur && list.some((l) => l.id === cur)) return cur;
      return (list.find((l) => l.status === 'published') ?? list[0])?.id ?? null;
    });
  }, [base]);

  useEffect(() => {
    void load().catch((e) => setLoadError(errorMessage(e)));
  }, [load]);

  const run = useCallback<Run>(
    async (fn, success) => {
      try {
        await fn();
        if (success) setToast(success);
      } catch (e) {
        setToast(errorMessage(e));
      }
      await load().catch(() => undefined);
    },
    [load, setToast]
  );

  if (loadError && !lessons) {
    return (
      <div className="grid gap-3.5 pt-6">
        <Card>
          <div className="label-eyebrow mb-1">Lessons</div>
          <h2 className="font-display text-[24px]">Lessons couldn’t be loaded</h2>
          <p className="mt-2 max-w-2xl text-[14px] text-ink-2">{loadError}</p>
          <p className="mt-1 max-w-2xl text-[13px] text-ink-3">
            If the server was just updated, its database may still need the lessons migration (0021_lessons).
          </p>
          <Button className="mt-4" size="sm" variant="outline" onClick={() => void load().catch((e) => setLoadError(errorMessage(e)))}>
            Try again
          </Button>
        </Card>
      </div>
    );
  }
  if (!lessons) return <div className="pt-6 text-ink-3">Loading…</div>;

  const selectedLesson = lessons.find((l) => l.id === selected) ?? null;

  return (
    <div className="grid gap-4 pt-6">
      <div className="hint">
        <span className="hint-icon">i</span>
        <div>
          Install the lesson as a <strong className="text-ink">draft</strong>, preview it exactly as students will get it
          (nothing is saved), then <strong className="text-ink">publish</strong> a version — students find it on their
          course page. Three things are tracked and never merged: <strong className="text-ink">viewed</strong> (opened a
          step), <strong className="text-ink">completed</strong> (did the step’s required actions — any answer counts,
          right or wrong) and <strong className="text-ink">understood</strong>, which only first-try answers and
          written explanations speak to. Viewed ≠ completed ≠ understood. None of it is a grade, and none of it is
          attendance.
        </div>
      </div>

      {fixtures.map((f) => (
        <FixtureCard
          key={f.key}
          base={base}
          course={course}
          fixture={f}
          lesson={lessons.find((l) => l.id === f.installed_lesson_id) ?? null}
          run={run}
        />
      ))}
      {!fixtures.length && !lessons.length ? (
        <Card>
          <div className="text-[14px] text-ink-3">No lesson files are bundled with this server, and no lessons are installed.</div>
        </Card>
      ) : null}

      {lessons.map((l) => (
        <LessonCard
          key={l.id}
          base={base}
          courseId={courseId}
          course={course}
          lesson={l}
          selected={l.id === selectedLesson?.id}
          onSelect={() => setSelected(l.id)}
          run={run}
        />
      ))}

      {selectedLesson ? (
        <InsightsPanel key={selectedLesson.id} courseId={courseId} lesson={selectedLesson} setToast={setToast} />
      ) : null}
    </div>
  );
}

/* =============== Fixture install =============== */

function FixtureCard({
  base,
  course,
  fixture: f,
  lesson,
  run
}: {
  base: string;
  course: CourseInfo;
  fixture: FixtureRow;
  lesson: LessonSummary | null;
  run: Run;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const installed = f.installed_lesson_id != null;
  const mismatch = !f.matches_course;
  const identity = `${course.code} · ${course.name} · ${course.year} / ${course.semester}`;
  const title = f.title ?? f.key;

  if (installed && f.valid && !lesson?.fixture_update_available) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-line-soft bg-card px-4 py-2.5 text-[13px] text-ink-2">
        <span className="pill pill-ok">✓ up to date</span>
        <span>
          Lesson file <span className="font-mono">{f.key}</span> (
          <span dir="rtl">
            <InlineText text={title} />
          </span>
          ) is installed in {course.code}; its latest version matches the app’s copy (
          <span className="font-mono">{shortHash(f.content_hash)}</span>).
        </span>
      </div>
    );
  }

  const install = () => {
    const what = installed
      ? `Load the changed lesson file into a draft of “${title}” in ${identity}?\n\n` +
        'Published versions never change, and students keep the version they started on.'
      : `Install “${title}” into ${identity} as a draft?\n\nStudents see nothing until you publish a version.`;
    const warning = mismatch ? `\n\nThe lesson file was written for course ${f.course_code ?? '?'}, not ${course.code}.` : '';
    if (!window.confirm(what + warning)) return;
    void run(
      () => apiPost(`${base}/install`, { fixture_key: f.key, allow_course_mismatch: mismatch && confirmed }),
      installed ? 'Draft updated from the lesson file' : 'Lesson installed as a draft'
    );
  };

  return (
    <Card className="grid gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="label-eyebrow mb-1">
            Lesson file · <span className="font-mono normal-case">{f.key}</span>
          </div>
          <h3 className="font-display text-[20px] leading-tight">
            <span dir="rtl">
              <InlineText text={title} />
            </span>
          </h3>
          <div className="mt-1 text-[13px] text-ink-3">
            <span className="font-mono">{f.slug ?? '—'}</span> · written for course{' '}
            <span className="font-mono">{f.course_code ?? '—'}</span> · content{' '}
            <span className="font-mono">{shortHash(f.content_hash)}</span>
          </div>
        </div>
        <Button size="sm" disabled={!f.valid || (mismatch && !confirmed)} onClick={install}>
          {installed ? 'Load changes into a draft' : 'Install as draft'}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-md border border-line-soft px-3 py-2 text-[13px]">
        <span className="font-semibold">Installs into:</span>
        <span>{identity}</span>
        <span className="text-ink-3">(course #{course.id})</span>
        {mismatch ? (
          <span className="pill pill-warn">⚠ course code differs from the lesson file’s ({f.course_code ?? '?'})</span>
        ) : (
          <span className="pill pill-ok">✓ course code matches</span>
        )}
      </div>

      {mismatch ? (
        <label className="flex items-start gap-2 rounded-md bg-warn-soft px-3 py-2.5 text-[13px]">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            I checked: this lesson, written for course <b>{f.course_code ?? '?'}</b>, belongs in <b>{identity}</b>. Check
            the year and semester — installing never touches another course, but students of this one would see it once
            published.
          </span>
        </label>
      ) : null}

      {installed ? (
        <div className="text-[13px] text-ink-3">
          Installed as lesson #{f.installed_lesson_id}. The app’s lesson file has changed since the latest version: loading
          it updates the current draft, or starts a new draft version if the latest one is published.
        </div>
      ) : (
        <div className="text-[13px] text-ink-3">
          Installing creates the lesson as a draft (version 1). Running it again later is safe: unchanged content is a
          no-op, and changes go into a draft version.
        </div>
      )}

      {!f.valid ? (
        <div className="hint hint-warm">
          <span className="hint-icon">!</span>
          <div>
            <div className="font-semibold text-ink">The lesson file didn’t pass validation, so it can’t be installed:</div>
            <ul className="mt-1 list-disc pl-5">
              {f.errors.map((err, i) => (
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

/* =============== Lesson card =============== */

function LessonCard({
  base,
  courseId,
  course,
  lesson,
  selected,
  onSelect,
  run
}: {
  base: string;
  courseId: number;
  course: CourseInfo;
  lesson: LessonSummary;
  selected: boolean;
  onSelect: () => void;
  run: Run;
}) {
  const live = lesson.status === 'published' ? lesson.active_version : null;
  const latest = lesson.versions[lesson.versions.length - 1] ?? null;
  const previewHref = (n: number) => `/course/${courseId}/lessons/${lesson.id}/preview?version=${n}`;

  const publish = (v: VersionRow) => {
    if (
      !window.confirm(
        `Publish version ${v.number} of “${lesson.title}”?\n\n` +
          `Students in ${course.code} will see it on their course page. A published version is frozen; ` +
          'students who already started stay on the version they started.'
      )
    )
      return;
    void run(() => apiPost(`${base}/${lesson.id}/publish`, { version_id: v.id }), `Version ${v.number} is live`);
  };
  const unpublish = () => {
    if (
      !window.confirm(
        `Unpublish “${lesson.title}”?\n\nStudents won’t see it until you publish again. Everything they saved is kept.`
      )
    )
      return;
    void run(() => apiPatch(`${base}/${lesson.id}`, { status: 'draft' }), 'Lesson hidden from students');
  };

  return (
    <Card className={`grid gap-4 ${selected ? 'border-forest ring-1 ring-forest-soft' : ''}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="label-eyebrow mb-1">
            Lesson · <span className="font-mono normal-case">{lesson.slug}</span>
          </div>
          <h2 className="font-display text-[24px] leading-tight">
            <span dir="rtl">{lesson.title}</span>
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-ink-3">
            <span className={LESSON_STATUS_PILL[lesson.status]}>{lesson.status}</span>
            {live ? (
              <span>
                Students see version {live.number} · published {fmtDate(live.published_at)}
              </span>
            ) : lesson.status === 'archived' ? (
              <span>Archived — hidden from students</span>
            ) : (
              <span>
                Hidden from students
                {lesson.active_version ? ` (version ${lesson.active_version.number} was live; saved progress is kept)` : ''}
              </span>
            )}
            {lesson.draft_version ? <span>· draft version {lesson.draft_version.number} not published yet</span> : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {latest ? (
            <a
              href={previewHref(latest.number)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center rounded-md border border-terracotta-soft bg-terracotta-tint px-2.5 py-1 text-[13px] text-ink hover:border-terracotta"
            >
              👁 Preview version {latest.number} ↗
            </a>
          ) : null}
          {lesson.draft_version ? (
            <Button
              size="sm"
              onClick={() => {
                const draft = lesson.versions.find((v) => v.id === lesson.draft_version?.id);
                if (draft) publish(draft);
              }}
            >
              Publish version {lesson.draft_version.number}
            </Button>
          ) : null}
          {lesson.status === 'published' ? (
            <Button size="sm" variant="outline" onClick={unpublish}>
              Unpublish
            </Button>
          ) : null}
        </div>
      </div>

      <TableCard>
        <thead>
          <tr>
            <Th className="pl-5">Version</Th>
            <Th>Status</Th>
            <Th>Content</Th>
            <Th>Created</Th>
            <Th>Published</Th>
            <Th className="pr-5 text-right">Actions</Th>
          </tr>
        </thead>
        <tbody>
          {[...lesson.versions].reverse().map((v) => {
            const isLive = live?.id === v.id;
            return (
              <tr key={v.id} className="border-b border-line-soft last:border-b-0">
                <Td className="pl-5 font-semibold">v{v.number}</Td>
                <Td>
                  <span className={v.status === 'published' ? 'pill pill-forest' : 'pill'}>
                    {v.status === 'published' ? 'published · frozen' : 'draft'}
                  </span>
                  {isLive ? <span className="pill pill-ok ml-1.5">✓ live to students</span> : null}
                </Td>
                <Td className="font-mono text-[12px] text-ink-3">{shortHash(v.content_hash)}</Td>
                <Td className="text-[13px] text-ink-2">{fmtDate(v.created_at)}</Td>
                <Td className="text-[13px] text-ink-2">{fmtDate(v.published_at)}</Td>
                <Td className="pr-5 text-right">
                  <div className="flex justify-end gap-2">
                    <a
                      href={previewHref(v.number)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center rounded-md px-2.5 py-1 text-[13px] text-forest hover:bg-paper-2"
                    >
                      Preview ↗
                    </a>
                    {!isLive ? (
                      <Button size="sm" variant={v.status === 'draft' ? 'default' : 'outline'} onClick={() => publish(v)}>
                        {v.status === 'published' ? `Make version ${v.number} live` : `Publish version ${v.number}`}
                      </Button>
                    ) : null}
                  </div>
                </Td>
              </tr>
            );
          })}
        </tbody>
      </TableCard>

      <ColabUrlField base={base} lesson={lesson} run={run} />

      <div className="flex flex-wrap items-center gap-2 border-t border-line-soft pt-4">
        <a
          className="inline-flex items-center rounded-md border border-border bg-card px-2.5 py-1 text-[13px] text-ink hover:bg-paper-2"
          href={`${apiBase()}${base}/${lesson.id}/export.csv`}
        >
          ⬇ Export progress (csv)
        </a>
        <span className="text-[12px] text-ink-3">
          One row per enrolled student: status, required steps done, experiments, commitment, first-try correct count,
          last saved activity. Test and withdrawn students are marked.
        </span>
        {!selected ? (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={onSelect}>
            Show class insights ↓
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

function ColabUrlField({ base, lesson, run }: { base: string; lesson: LessonSummary; run: Run }) {
  const [value, setValue] = useState(lesson.colab_url);
  useEffect(() => setValue(lesson.colab_url), [lesson.colab_url]);
  const trimmed = value.trim();
  const problem = trimmed ? colabUrlProblem(trimmed) : null;
  const dirty = trimmed !== lesson.colab_url;

  const save = (url: string) =>
    run(() => apiPatch(`${base}/${lesson.id}`, { colab_url: url }), url ? 'Colab link saved' : 'Colab link cleared');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (problem || !dirty) return;
    void save(trimmed);
  };

  return (
    <form onSubmit={submit} className="grid gap-1.5">
      <Label htmlFor={`colab-url-${lesson.id}`}>Colab notebook link</Label>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={`colab-url-${lesson.id}`}
          dir="ltr"
          className="h-9 min-w-[280px] flex-1 font-mono text-[12px]"
          placeholder="https://colab.research.google.com/drive/…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-invalid={problem ? true : undefined}
          aria-describedby={`colab-url-help-${lesson.id}`}
        />
        <Button type="submit" size="sm" variant="soft" disabled={!dirty || !!problem}>
          Save link
        </Button>
        {lesson.colab_url ? (
          <>
            <a href={lesson.colab_url} target="_blank" rel="noreferrer" className="text-[13px] text-forest hover:underline">
              Test it ↗
            </a>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                if (window.confirm('Remove the Colab link? Students keep the download-and-upload steps.')) void save('');
              }}
            >
              Clear
            </Button>
          </>
        ) : null}
      </div>
      <div id={`colab-url-help-${lesson.id}`} className="text-[12px]">
        {problem ? (
          <span className="text-bad">{problem}</span>
        ) : lesson.colab_url ? (
          <span className="text-ink-3">
            Students get an “open in Colab” button for this link, with the notebook download as a fallback. Share it as
            “anyone with the link can view”; each student then saves their own copy (File › Save a copy in Drive).
          </span>
        ) : (
          <span className="text-ink-3">
            Not set — students get the notebook download and the colab.research.google.com → File › Upload notebook steps.
            No placeholder link is ever shown. Only https links on colab.research.google.com or drive.google.com are
            accepted.
          </span>
        )}
      </div>
    </form>
  );
}

/* =============== Insights =============== */

function InsightsPanel({
  courseId,
  lesson,
  setToast
}: {
  courseId: number;
  lesson: LessonSummary;
  setToast: (m: string) => void;
}) {
  const base = `/api/courses/${courseId}/lessons/${lesson.id}`;
  const [includeTest, setIncludeTest] = useState(false);
  const [shown, setShown] = useState<{ data: Insights; includeTest: boolean } | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [studentId, setStudentId] = useState<number | null>(null);
  const [openQuestion, setOpenQuestion] = useState<string | null>(null);
  // Publishing or a new draft can change which version the numbers are read against.
  const versionsKey = `${lesson.status}:${lesson.versions.map((v) => `${v.id}${v.status}`).join(',')}`;

  const load = useCallback(async () => {
    try {
      const data = await apiGet<Insights>(`${base}/insights?include_test=${includeTest}`);
      setShown({ data, includeTest });
      setUpdatedAt(new Date());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [base, includeTest]);

  useEffect(() => {
    void load();
  }, [load, versionsKey]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => void load(), AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [autoRefresh, load]);

  const toggleFlag = useCallback<FlagFn>(
    async (attemptId, flaggedStudent, flagged) => {
      try {
        const res = await apiPost<{ id: number; review_flag: boolean }>(`${base}/attempts/${attemptId}/flag`, { flagged });
        setShown((cur) => {
          if (!cur) return cur;
          const questions = cur.data.questions.map((q) => ({
            ...q,
            free_text: q.free_text.map((r) => (r.attempt_id === res.id ? { ...r, flagged: res.review_flag } : r))
          }));
          // Callers pass the toggled value, so the flag was !flagged before.
          const delta = Number(res.review_flag) - Number(!flagged);
          const students = cur.data.students.map((s) =>
            s.student_id === flaggedStudent ? { ...s, flagged: Math.max(0, s.flagged + delta) } : s
          );
          return { ...cur, data: { ...cur.data, questions, students } };
        });
        setToast(res.review_flag ? 'Flagged for review' : 'Review flag removed');
        return res.review_flag;
      } catch (e) {
        setToast(errorMessage(e));
        return null;
      }
    },
    [base, setToast]
  );

  const closeDrawer = useCallback(() => setStudentId(null), []);

  const data = shown?.data ?? null;
  const stepByKey = useMemo(() => Object.fromEntries((data?.steps ?? []).map((s) => [s.key, s])), [data]);
  const questionByKey = useMemo(() => Object.fromEntries((data?.questions ?? []).map((q) => [q.key, q])), [data]);
  const counted = useMemo(
    () => (data ? data.students.filter((s) => !s.withdrawn && (shown?.includeTest || !s.is_test)) : []),
    [data, shown?.includeTest]
  );
  const lastSavedHere = useMemo(() => {
    const out: Record<string, number> = {};
    for (const s of counted) if (s.current_step_key) out[s.current_step_key] = (out[s.current_step_key] ?? 0) + 1;
    return out;
  }, [counted]);

  const openQuestionRow = (key: string) => {
    setOpenQuestion(key);
    window.requestAnimationFrame(() =>
      document.getElementById(`lesson-q-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    );
  };

  return (
    <section className="grid gap-4" aria-label="Class insights">
      <div className="mt-2 flex flex-wrap items-end justify-between gap-3 border-t border-border pt-6">
        <div className="min-w-0">
          <div className="label-eyebrow mb-1">Class insights</div>
          <h2 className="font-display text-[28px] leading-tight">
            <span dir="rtl">{lesson.title}</span>
          </h2>
          <div className="mt-1 text-[13px] text-ink-3">
            {data ? (
              <>
                Counting {data.totals.enrolled} enrolled student{data.totals.enrolled === 1 ? '' : 's'}
                {data.totals.excluded_test ? ` · ${data.totals.excluded_test} test student${data.totals.excluded_test === 1 ? '' : 's'} left out` : ''}
                {data.totals.withdrawn ? ` · ${data.totals.withdrawn} withdrawn, not counted` : ''}
                {updatedAt ? ` · updated ${updatedAt.toLocaleTimeString()}` : ''}
              </>
            ) : (
              'Loading…'
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={includeTest} onChange={(e) => setIncludeTest(e.target.checked)} />
            Include test students
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Refresh every 30 s
          </label>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            ↻ Refresh
          </Button>
        </div>
      </div>

      {error ? (
        <div className="hint hint-warm">
          <span className="hint-icon">!</span>
          <div>Insights couldn’t be loaded: {error}</div>
        </div>
      ) : null}

      {!data ? null : (
        <>
          {data.lesson.status !== 'published' ? (
            <div className="hint hint-soft">
              <span className="hint-icon">i</span>
              <div>
                This lesson isn’t published, so students can’t open it right now. The numbers below cover whatever was
                saved while it was.
              </div>
            </div>
          ) : null}
          {!data.students.length ? (
            <Card>
              <div className="text-[14px] text-ink-3">No students are enrolled in this course yet — import the roster first.</div>
            </Card>
          ) : (
            <>
              <TotalsRow totals={data.totals} />
              <BreakdownCard questions={data.questions} steps={stepByKey} onOpen={openQuestionRow} />
              <StepFunnel steps={data.steps} counted={data.totals.enrolled} lastSavedHere={lastSavedHere} />
              <QuestionTable
                questions={data.questions}
                steps={stepByKey}
                open={openQuestion}
                setOpen={setOpenQuestion}
                onFlag={toggleFlag}
              />
              <StudentTable
                students={data.students}
                includeTest={shown?.includeTest ?? false}
                steps={stepByKey}
                liveVersion={data.lesson.status === 'published' ? data.lesson.active_version?.number ?? null : null}
                onOpen={setStudentId}
              />
            </>
          )}
        </>
      )}

      {studentId != null && data ? (
        <StudentDrawer
          base={base}
          studentId={studentId}
          steps={data.steps}
          questions={questionByKey}
          onClose={closeDrawer}
          onFlag={toggleFlag}
        />
      ) : null}
    </section>
  );
}

function TotalsRow({ totals }: { totals: Insights['totals'] }) {
  const tiles: { label: string; value: number; of?: number; sub: string }[] = [
    {
      label: 'Enrolled · counted',
      value: totals.enrolled,
      sub: totals.excluded_test ? `${totals.excluded_test} test excluded` : 'every enrolled student, visited or not'
    },
    { label: 'Not started', value: totals.not_started, of: totals.enrolled, sub: 'nothing saved yet' },
    { label: 'In progress', value: totals.in_progress, of: totals.enrolled, sub: 'started; some required actions left' },
    {
      label: 'Completed actions',
      value: totals.completed,
      of: totals.enrolled,
      sub: 'every required step done — not a grade, not proof of understanding'
    },
    { label: 'Withdrawn', value: totals.withdrawn, sub: 'listed separately, never counted' }
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-lg border border-border bg-card p-4 shadow-soft">
          <div className="label-eyebrow">{t.label}</div>
          <div className="mt-1.5 font-display text-[28px] leading-none tnum">
            {t.value}
            {t.of != null ? <span className="ml-1.5 text-[14px] text-ink-3">{share(t.value, t.of)}</span> : null}
          </div>
          <div className="mt-1.5 text-[12px] leading-snug text-ink-3">{t.sub}</div>
        </div>
      ))}
    </div>
  );
}

/** At a glance, for class: the questions most students got wrong on their own,
 * and the misconceptions behind their first wrong answers. */
function BreakdownCard({
  questions,
  steps,
  onOpen
}: {
  questions: QuestionStats[];
  steps: Record<string, StepStats>;
  onOpen: (key: string) => void;
}) {
  const graded = questions.filter((q) => firstTryRate(q) != null);
  const worst = [...graded].sort(worstFirst).slice(0, 4);

  const tags = new Map<string, { tag: string; count: number; questions: string[] }>();
  for (const q of graded) {
    for (const o of q.options) {
      if (o.correct || o.first_count === 0) continue;
      const tag = o.misconception ?? `untagged wrong choice (${q.key} · ${o.id})`;
      const entry = tags.get(tag) ?? { tag, count: 0, questions: [] };
      entry.count += o.first_count;
      if (!entry.questions.includes(q.key)) entry.questions.push(q.key);
      tags.set(tag, entry);
    }
  }
  const topTags = Array.from(tags.values())
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
    .slice(0, 6);
  const maxTag = topTags[0]?.count ?? 0;

  const revealedFirst = questions.reduce((n, q) => n + q.revealed_before_answer, 0);
  const mostRevealed = [...questions].sort((a, b) => b.revealed_before_answer - a.revealed_before_answer)[0];
  const corrected = questions.reduce((n, q) => n + q.eventually_correct_after_wrong_first, 0);
  const written = questions.reduce((n, q) => n + q.free_text.length, 0);
  const flagged = questions.reduce((n, q) => n + q.free_text.filter((r) => r.flagged).length, 0);
  const letter = (key: string) => {
    const q = questions.find((x) => x.key === key);
    return (q && steps[q.step]?.letter) ?? '';
  };

  return (
    <Card className="grid gap-4">
      <div>
        <h3 className="font-display text-[20px]">Where understanding breaks down</h3>
        <p className="text-[13px] text-ink-3">
          From each student’s <b>first</b> answer, given before any feedback — the only independent evidence here. Right
          answers after feedback are shown separately and don’t count as understanding.
        </p>
      </div>

      {!graded.length ? (
        <div className="rounded-md bg-paper-2 px-3 py-3 text-[13px] text-ink-3">
          No answers yet. This fills in as students answer; opening a step doesn’t count.
        </div>
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          <div className="grid content-start gap-3">
            <div className="label-eyebrow">Lowest first-try results</div>
            {worst.map((q) => {
              const wrong = dominantWrong(q);
              return (
                <button
                  key={q.key}
                  type="button"
                  onClick={() => onOpen(q.key)}
                  className="grid gap-1 rounded-md border border-line-soft px-3 py-2.5 text-left transition hover:border-ink-4"
                >
                  <div className="flex items-baseline justify-between gap-2 text-[12px] text-ink-3">
                    <span>
                      <span className="font-semibold text-ink-2">{steps[q.step]?.letter ?? q.step}</span> ·{' '}
                      <span className="font-mono">{q.key}</span>
                      {q.mode === 'check' ? ' · individual check' : ''}
                    </span>
                    <span className="tnum text-[13px] font-semibold text-ink">
                      {q.first_correct} of {independent(q)} right first try ({share(q.first_correct, independent(q))})
                      {q.answered_after_reveal ? (
                        <span className="font-normal text-ink-3"> · {q.answered_after_reveal} answered only after revealing</span>
                      ) : null}
                    </span>
                  </div>
                  <div dir="rtl" className="text-start text-[14px] leading-snug">
                    <InlineText text={q.prompt} />
                  </div>
                  <Meter value={q.first_correct} max={independent(q)} label="right on the first try, before any feedback" />
                  {wrong ? (
                    <div className="grid gap-0.5 text-[12px] text-ink-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        Most common wrong first answer ·{' '}
                        <span className="tnum font-semibold">
                          {wrong.first_count} student{wrong.first_count === 1 ? '' : 's'}
                        </span>
                        <span className="pill pill-warn">{wrong.misconception ?? `choice ${wrong.id}`}</span>
                      </div>
                      <div className="flex items-baseline gap-1.5 text-ink-3">
                        <span className="font-mono">{wrong.id}</span>
                        <span dir="rtl" className="min-w-0 flex-1 text-start">
                          <InlineText text={wrong.text} />
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-[12px] text-ink-3">No wrong first answers.</div>
                  )}
                </button>
              );
            })}
          </div>

          <div className="grid content-start gap-3">
            <div className="label-eyebrow">Misconceptions behind first wrong answers</div>
            {topTags.length ? (
              topTags.map((t) => (
                <div key={t.tag} className="grid gap-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
                    <span className="font-mono font-semibold">{t.tag}</span>
                    <span className="text-[12px] text-ink-3">
                      in {t.questions.map((k) => `${letter(k)} ${k}`).join(', ')}
                    </span>
                  </div>
                  <Meter value={t.count} max={maxTag} warm label={`${t.count} first answers`} />
                </div>
              ))
            ) : (
              <div className="text-[13px] text-ink-3">No wrong first answers so far.</div>
            )}
            <div className="text-[12px] text-ink-3">
              Bars compare tags with each other: the number is how many first answers picked a choice with that
              misconception.
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-x-5 gap-y-1.5 border-t border-line-soft pt-3 text-[13px] text-ink-2">
        <span>
          <span className="tnum font-semibold">{revealedFirst}</span> reveal{revealedFirst === 1 ? '' : 's'} of the
          reasoning before any answer
          {revealedFirst && mostRevealed?.revealed_before_answer ? (
            <span className="text-ink-3">
              {' '}
              (most on <span className="font-mono">{mostRevealed.key}</span>)
            </span>
          ) : null}
        </span>
        <span>
          <span className="tnum font-semibold">{corrected}</span> right answer{corrected === 1 ? '' : 's'} reached only
          after a wrong first try
        </span>
        <span>
          <span className="tnum font-semibold">{written}</span> written response{written === 1 ? '' : 's'} to read
          (ungraded){flagged ? ` · ${flagged} flagged` : ''}
        </span>
      </div>
    </Card>
  );
}

function StepFunnel({
  steps,
  counted,
  lastSavedHere
}: {
  steps: StepStats[];
  counted: number;
  lastSavedHere: Record<string, number>;
}) {
  return (
    <Card className="grid gap-3">
      <div>
        <h3 className="font-display text-[20px]">Step funnel</h3>
        <p className="text-[13px] text-ink-3">
          <b>Viewed</b> = opened the step. <b>Completed</b> = did all of its required actions (any answer counts, right
          or wrong; ticks are self-reported). Neither means understood — see the first-try results.{' '}
          <b>Last saved here</b> = the step each student’s progress was last saved on; it says nothing about who is in
          class.
        </p>
      </div>
      <div className="overflow-auto">
        <table className="w-full border-collapse text-[14px]">
          <thead>
            <tr>
              <Th className="pl-0">Step</Th>
              <Th className="w-[26%]">Viewed</Th>
              <Th className="w-[26%]">Completed actions</Th>
              <Th className="text-right">Last saved here</Th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s) => (
              <tr key={s.key} className="border-b border-line-soft last:border-b-0">
                <Td className="pl-0">
                  <div className="flex items-baseline gap-2">
                    <span className="w-4 shrink-0 font-display text-[16px] text-ink-3">{s.letter}</span>
                    <span dir="rtl" className="min-w-0">
                      <InlineText text={s.title} />
                    </span>
                    {s.optional ? <span className="pill pill-terra">optional · not in required totals</span> : null}
                  </div>
                </Td>
                <Td>
                  <Meter value={s.viewed} max={counted} warm label={`${s.viewed} of ${counted} viewed`} />
                </Td>
                <Td>
                  <Meter value={s.completed} max={counted} label={`${s.completed} of ${counted} completed the actions`} />
                </Td>
                <Td className="tnum text-right">{lastSavedHere[s.key] ?? 0}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function QuestionTable({
  questions,
  steps,
  open,
  setOpen,
  onFlag
}: {
  questions: QuestionStats[];
  steps: Record<string, StepStats>;
  open: string | null;
  setOpen: (key: string | null) => void;
  onFlag: FlagFn;
}) {
  const [order, setOrder] = useState<'lesson' | 'worst'>('lesson');
  const rows = order === 'lesson' ? questions : [...questions].sort(worstFirst);

  return (
    <div className="grid gap-2.5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="font-display text-[20px]">Questions</h3>
          <p className="max-w-3xl text-[13px] text-ink-3">
            <b>First try</b> = each student’s first submitted answer, before any feedback. Practice questions allow retries
            after feedback; individual checks keep the first answer and log every revision. Written answers are never
            graded.
          </p>
        </div>
        <div className="flex gap-1.5">
          <Chip active={order === 'lesson'} onClick={() => setOrder('lesson')}>
            Lesson order
          </Chip>
          <Chip active={order === 'worst'} onClick={() => setOrder('worst')}>
            Lowest first try first
          </Chip>
        </div>
      </div>
      <TableCard>
        <thead>
          <tr>
            <Th className="pl-5">Question</Th>
            <Th
              className="text-right"
              title="Right on the first try, before any feedback / students whose first answer came before any feedback. Answers given only after revealing the reasoning are counted apart."
            >
              Right first try (before feedback)
            </Th>
            <Th className="text-right">Unanswered</Th>
            <Th className="text-right" title="Answers submitted after the student had already seen feedback or the reasoning">
              Tries after feedback
            </Th>
            <Th className="text-right" title="Asked to see the reasoning before submitting any answer">
              Revealed before answering
            </Th>
            <Th className="text-right" title="Wrong on the first try, right on a later try — not independent understanding">
              Right only later
            </Th>
            <Th className="pr-5" />
          </tr>
        </thead>
        <tbody>
          {rows.map((q) => {
            const isOpen = open === q.key;
            return (
              <FragmentRows key={q.key}>
                <tr id={`lesson-q-${q.key}`} className="scroll-mt-4 border-b border-line-soft">
                  <Td className="pl-5">
                    <div className="text-[12px] text-ink-3">
                      <span className="font-semibold text-ink-2">{steps[q.step]?.letter ?? q.step}</span> ·{' '}
                      <span className="font-mono">{q.key}</span> · {q.mode === 'check' ? 'individual check' : 'practice'} ·{' '}
                      {q.type === 'free_text' ? 'written' : 'choice'}
                    </div>
                    <div dir="rtl" className="mt-0.5 max-w-[620px] leading-snug">
                      <InlineText text={q.prompt} />
                    </div>
                  </Td>
                  <Td className="w-[170px] text-right">
                    {q.type === 'single_choice' ? (
                      q.answered ? (
                        <>
                          <div className="tnum font-semibold">
                            {q.first_correct}/{independent(q)}{' '}
                            <span className="font-normal text-ink-3">({share(q.first_correct, independent(q))})</span>
                          </div>
                          <div className="mt-1">
                            <Meter value={q.first_correct} max={independent(q)} label="right on the first try, before any feedback" />
                          </div>
                          {q.answered_after_reveal ? (
                            <div className="mt-1 text-[12px] text-ink-3">
                              + {q.answered_after_reveal} answered only after revealing
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <span className="text-ink-3">no answers</span>
                      )
                    ) : (
                      <>
                        <span className="pill">ungraded</span>
                        <div className="mt-1 text-[12px] text-ink-3">{q.answered} answered</div>
                      </>
                    )}
                  </Td>
                  <Td className="tnum text-right">{q.unanswered}</Td>
                  <Td className="tnum text-right">{q.attempts_after_feedback}</Td>
                  <Td className="tnum text-right">{q.revealed_before_answer}</Td>
                  <Td className="tnum text-right">
                    {q.type === 'single_choice' ? q.eventually_correct_after_wrong_first : '—'}
                  </Td>
                  <Td className="pr-5 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-expanded={isOpen}
                      aria-controls={`lesson-q-detail-${q.key}`}
                      onClick={() => setOpen(isOpen ? null : q.key)}
                    >
                      {isOpen ? 'Hide ▴' : `Details${q.free_text.length ? ` · ${q.free_text.length} written` : ''} ▾`}
                    </Button>
                  </Td>
                </tr>
                {isOpen ? (
                  <tr id={`lesson-q-detail-${q.key}`} className="border-b border-line-soft bg-paper-2">
                    <td colSpan={7} className="px-5 py-4">
                      <QuestionDetail q={q} onFlag={onFlag} />
                    </td>
                  </tr>
                ) : null}
              </FragmentRows>
            );
          })}
        </tbody>
      </TableCard>
    </div>
  );
}

function QuestionDetail({ q, onFlag }: { q: QuestionStats; onFlag: FlagFn }) {
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const correctIds = new Set(q.options.filter((o) => o.correct).map((o) => o.id));
  const responses = flaggedOnly ? q.free_text.filter((r) => r.flagged) : q.free_text;

  return (
    <div className="grid gap-5">
      {q.type === 'single_choice' ? (
        <div className="grid gap-2.5">
          <div className="label-eyebrow">
            Choices · bar = first answers before any feedback · all = including retries
          </div>
          {q.answered_after_reveal ? (
            <div className="text-[12px] text-ink-3">
              {q.answered_after_reveal} student{q.answered_after_reveal === 1 ? '' : 's'} answered only after revealing the
              reasoning — counted in “all”, not in the bars.
            </div>
          ) : null}
          {q.other_version_answers ? (
            <div className="text-[12px] text-ink-3">
              {q.other_version_answers} answer{q.other_version_answers === 1 ? ' was' : 's were'} given to another version of
              this question (its options read differently) — not included in these numbers.
            </div>
          ) : null}
          {q.options.map((o) => (
            <div key={o.id} className="grid items-center gap-x-4 gap-y-1 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_140px]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-[12px] text-ink-3">{o.id}</span>
                  {o.correct ? (
                    <span className="pill pill-ok">✓ correct</span>
                  ) : (
                    <span className="pill pill-warn">✗ {o.misconception ?? 'wrong (untagged)'}</span>
                  )}
                </div>
                <div dir="rtl" className="mt-0.5 text-[13px] leading-snug">
                  <InlineText text={o.text} />
                </div>
              </div>
              <Meter value={o.first_count} max={independent(q)} warm={!o.correct} label={`${o.first_count} first answers`} />
              <div className="tnum text-right text-[12px] text-ink-3">
                {o.first_count} first · {o.all_count} all
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="label-eyebrow">
            {q.type === 'free_text' ? 'Written answers' : 'Written explanations'} · ungraded · {q.free_text.length}
            <span className="ml-1 normal-case tracking-normal text-ink-3">
              (each student’s first and latest try, plus flagged ones · every try is in the student’s drilldown)
            </span>
          </div>
          {q.free_text.some((r) => r.flagged) ? (
            <label className="flex items-center gap-1.5 text-[12px] text-ink-2">
              <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
              Only flagged
            </label>
          ) : null}
        </div>
        {!q.free_text.length ? (
          <div className="text-[13px] text-ink-3">
            {q.type === 'free_text' ? 'No written answers yet.' : 'No explanations written for this question yet.'}
          </div>
        ) : (
          <ul className="grid max-h-[520px] gap-2 overflow-auto">
            {responses.map((r) => (
              <li key={r.attempt_id} className="rounded-md border border-line-soft bg-card px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-3">
                  <BilingualName name={r.name} />
                  <span>
                    · try {r.attempt_number}
                    {r.attempt_number === 1 ? ' (first)' : ''} · {fmtDate(r.submitted_at)}
                  </span>
                  {r.choice ? (
                    <span>
                      · chose <span className="font-mono">{r.choice}</span>{' '}
                      {correctIds.has(r.choice) ? '(correct)' : '(wrong)'}
                    </span>
                  ) : null}
                  <span className="pill">ungraded</span>
                  <button
                    type="button"
                    aria-pressed={r.flagged}
                    onClick={() => void onFlag(r.attempt_id, r.student_id, !r.flagged)}
                    className={`ml-auto rounded-full border px-2.5 py-0.5 text-[12px] ${
                      r.flagged ? 'border-terracotta bg-terracotta-tint text-ink' : 'border-border bg-card text-ink-2 hover:border-ink-4'
                    }`}
                  >
                    {r.flagged ? '⚑ Flagged for review' : '⚐ Flag for review'}
                  </button>
                </div>
                <p dir="auto" className="mt-1.5 whitespace-pre-wrap text-[14px] leading-relaxed">
                  {r.text}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function StudentTable({
  students,
  includeTest,
  steps,
  liveVersion,
  onOpen
}: {
  students: StudentRow[];
  includeTest: boolean;
  steps: Record<string, StepStats>;
  liveVersion: number | null; // students pinned to another version are marked
  onOpen: (studentId: number) => void;
}) {
  const [sort, setSort] = useState<'name' | 'status'>('name');
  const [filter, setFilter] = useState<'all' | StudentStatus>('all');
  const [search, setSearch] = useState('');
  const [showWithdrawn, setShowWithdrawn] = useState(false);

  const withdrawn = students.filter((s) => s.withdrawn).length;
  const optionalTotal = Object.values(steps).filter((st) => st.optional).length;
  const pool = students.filter((s) => (includeTest || !s.is_test) && (showWithdrawn || !s.withdrawn));
  const count = (st: StudentStatus) => pool.filter((s) => s.status === st).length;
  const q = search.trim().toLowerCase();
  const byName = (a: StudentRow, b: StudentRow) => a.name.localeCompare(b.name);
  const rows = pool
    .filter((s) => (filter === 'all' || s.status === filter) && (!q || s.name.toLowerCase().includes(q)))
    .sort((a, b) => (sort === 'status' ? STUDENT_STATUS[a.status].order - STUDENT_STATUS[b.status].order : 0) || byName(a, b));

  const FILTERS: { key: 'all' | StudentStatus; label: string; n: number }[] = [
    { key: 'all', label: 'All', n: pool.length },
    { key: 'not_started', label: 'Not started', n: count('not_started') },
    { key: 'in_progress', label: 'In progress', n: count('in_progress') },
    { key: 'completed', label: 'Completed actions', n: count('completed') }
  ];

  return (
    <div className="grid gap-2.5">
      <div>
        <h3 className="font-display text-[20px]">Students</h3>
        <p className="max-w-3xl text-[13px] text-ink-3">
          Every enrolled student, whether or not they opened the lesson. Ordered by name or status only — never by time.{' '}
          <b>Last saved</b> is when something was last saved; it isn’t attendance. Click a name for the student’s
          path.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <Chip key={f.key} active={filter === f.key} onClick={() => setFilter(f.key)}>
            {f.label}
            <span className={`tnum text-[12px] ${filter === f.key ? 'opacity-70' : 'text-ink-3'}`}>{f.n}</span>
          </Chip>
        ))}
        <span className="mx-1 h-5 w-px bg-border" aria-hidden />
        <span className="text-[12px] text-ink-3">Order:</span>
        <Chip active={sort === 'name'} onClick={() => setSort('name')}>
          Name
        </Chip>
        <Chip active={sort === 'status'} onClick={() => setSort('status')}>
          Status
        </Chip>
        <div className="ml-auto flex items-center gap-3">
          {withdrawn ? (
            <label className="flex items-center gap-1.5 text-[13px]">
              <input type="checkbox" checked={showWithdrawn} onChange={(e) => setShowWithdrawn(e.target.checked)} />
              Show withdrawn ({withdrawn})
            </label>
          ) : null}
          <Input
            className="h-9 w-[220px]"
            placeholder="Search by name"
            aria-label="Search students by name"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      <TableCard>
        <thead>
          <tr>
            <Th className="pl-5">Student</Th>
            <Th>Status</Th>
            <Th title="Required steps whose actions are all done / required steps; optional extensions are listed apart">
              Required steps
            </Th>
            <Th>Current step</Th>
            <Th title="Experiment records (runs) the student entered, deleted ones not counted; and the saved choice before the final test">
              Experiments · commitment
            </Th>
            <Th className="text-right" title="Written answers submitted · how many are flagged for review">
              Written
            </Th>
            <Th className="pr-5" title="When something was last saved — not attendance">
              Last saved
            </Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr
              key={s.student_id}
              className={`cursor-pointer border-b border-line-soft last:border-b-0 hover:bg-paper-2 ${s.withdrawn ? 'text-ink-3' : ''}`}
              onClick={() => onOpen(s.student_id)}
            >
              <Td className="whitespace-nowrap pl-5">
                <button
                  type="button"
                  className="text-left hover:underline"
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpen(s.student_id);
                  }}
                >
                  <BilingualName name={s.name} size={14} />
                </button>
                {s.is_test || s.withdrawn ? (
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    {s.is_test ? <span className="pill pill-info">test student</span> : null}
                    {s.withdrawn ? <span className="pill pill-warn">withdrawn</span> : null}
                  </div>
                ) : null}
              </Td>
              <Td>
                <span className={STUDENT_STATUS[s.status].pill}>{STUDENT_STATUS[s.status].label}</span>
              </Td>
              <Td className="w-[126px] min-w-[112px]">
                {s.required_total ? <Meter value={s.completed_required} max={s.required_total} /> : '—'}
                {optionalTotal ? (
                  <div
                    className="mt-0.5 whitespace-nowrap text-[11px] text-ink-3"
                    title="Optional extensions completed — never part of the required total"
                  >
                    + optional {s.optional_completed}/{optionalTotal}
                  </div>
                ) : null}
              </Td>
              <Td className="text-[13px]">
                <div className="max-w-[150px]">
                  {s.current_step_key ? <StepLabel step={steps[s.current_step_key]} fallback={s.current_step_key} /> : '—'}
                </div>
                {s.version_number != null && s.version_number !== liveVersion ? (
                  <div className="text-[11px] text-ink-3">pinned to version {s.version_number}</div>
                ) : null}
              </Td>
              <Td className="text-[13px]">
                <div className={`tnum ${s.experiments ? '' : 'text-ink-4'}`}>
                  {s.experiments} run{s.experiments === 1 ? '' : 's'}
                </div>
                {s.committed ? (
                  <div className="mt-1 grid justify-items-start gap-1">
                    <span className="pill pill-forest">✓ committed</span>
                    {s.final_recorded ? <span className="text-[11px] text-ink-3">final result recorded</span> : null}
                    {s.revised_after_final ? (
                      <span className="pill pill-warn" title="Chose again after a final-test result was recorded">
                        re-chose after final
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </Td>
              <Td className="tnum text-right">
                {s.free_text_answers}
                {s.flagged ? (
                  <div className="whitespace-nowrap text-[12px] text-terracotta" title={`${s.flagged} flagged for review`}>
                    ⚑ {s.flagged}
                  </div>
                ) : null}
              </Td>
              <Td className="whitespace-nowrap pr-5 text-[13px] text-ink-2">{fmtShortDate(s.last_activity_at)}</Td>
            </tr>
          ))}
          {!rows.length ? (
            <tr>
              <td colSpan={7} className="px-5 py-6 text-center text-[13px] text-ink-3">
                Nobody matches that view.
              </td>
            </tr>
          ) : null}
        </tbody>
      </TableCard>
    </div>
  );
}

/* =============== Student drilldown =============== */

function StudentDrawer({
  base,
  studentId,
  steps,
  questions,
  onClose,
  onFlag
}: {
  base: string;
  studentId: number;
  steps: StepStats[];
  questions: Record<string, QuestionStats>;
  onClose: () => void;
  onFlag: FlagFn;
}) {
  const [detail, setDetail] = useState<StudentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    apiGet<StudentDetail>(`${base}/students/${studentId}`)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [base, studentId]);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      opener?.focus();
    };
  }, [onClose]);

  const flag = async (a: DetailAttempt) => {
    const next = await onFlag(a.id, studentId, !a.review_flag);
    if (next == null) return;
    setDetail((d) => d && { ...d, attempts: d.attempts.map((x) => (x.id === a.id ? { ...x, review_flag: next } : x)) });
  };

  const stepMeta = Object.fromEntries(steps.map((s) => [s.key, s]));
  const progress = detail?.progress ?? null;
  const allRequiredDone =
    !!detail?.steps && steps.filter((s) => !s.optional).every((s) => detail.steps?.[s.key]?.completed);
  const status: StudentStatus = detail?.status ?? (!progress ? 'not_started' : allRequiredDone ? 'completed' : 'in_progress');
  const stepKeys = detail?.steps ? Object.keys(detail.steps) : [];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink/20" aria-hidden onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="lesson-student-title"
        className="fixed inset-y-0 right-0 z-50 w-full max-w-[680px] overflow-y-auto border-l border-border bg-card px-6 py-6 shadow-lift"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="label-eyebrow mb-1">Student path</div>
            <h2 id="lesson-student-title" className="font-display text-[24px] leading-tight">
              {detail ? <BilingualName name={detail.student.name} size={21} /> : 'Loading…'}
            </h2>
            {detail ? (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className={STUDENT_STATUS[status].pill}>{STUDENT_STATUS[status].label}</span>
                {detail.student.is_test ? <span className="pill pill-info">test student</span> : null}
                {detail.student.withdrawn ? <span className="pill pill-warn">withdrawn</span> : null}
                {detail.version_number != null ? <span className="pill">on version {detail.version_number}</span> : null}
              </div>
            ) : null}
          </div>
          <Button ref={closeRef} size="sm" variant="ghost" onClick={onClose} aria-label="Close student path">
            ✕ Close
          </Button>
        </div>

        {error ? <div className="mt-4 text-[14px] text-bad">{error}</div> : null}

        {detail ? (
          <div className="mt-5 grid gap-6">
            <div className="text-[13px] text-ink-2">
              {progress ? (
                <>
                  Started {fmtDate(progress.started_at)} · last saved {fmtDate(progress.updated_at)}
                  {progress.completed_at
                    ? ` · first completed all required actions ${fmtDate(progress.completed_at)}${
                        status === 'completed' ? '' : ' (not complete now: some evidence was removed since)'
                      }`
                    : ''}
                </>
              ) : (
                'Nothing saved yet: the student hasn’t started this lesson (or opened it without saving anything).'
              )}
            </div>

            <DrawerSection title="Steps" note="Viewed = opened · completed = did the step’s required actions. Not a grade.">
              {detail.steps ? (
                <ul className="grid gap-1">
                  {stepKeys.map((key) => {
                    const st = detail.steps![key];
                    const meta = stepMeta[key];
                    return (
                      <li key={key} className="flex flex-wrap items-center gap-2 text-[13px]">
                        <span className="min-w-0 flex-1">
                          <StepLabel step={meta} fallback={key} />
                          {meta?.optional ? <span className="ml-1.5 text-[11px] text-ink-3">(optional)</span> : null}
                        </span>
                        <span className={st.viewed ? 'pill pill-info' : 'pill'}>{st.viewed ? 'viewed' : 'not viewed'}</span>
                        <span className={st.completed ? 'pill pill-ok' : 'pill'}>
                          {st.completed ? '✓ completed' : `${st.done}/${st.total} actions`}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="text-[13px] text-ink-3">No version to compare against yet.</div>
              )}
              {progress?.acks.length ? (
                <div className="mt-2 text-[12px] text-ink-3">
                  Self-reported ticks (not verified):{' '}
                  {progress.acks.map((k) => (
                    <span key={k} className="pill mr-1 font-mono">
                      {k}
                    </span>
                  ))}
                </div>
              ) : null}
            </DrawerSection>

            <DrawerSection
              title={`Answers, in order (${detail.attempts.length})`}
              note="Every submission is kept. The first try is the independent one; tries after feedback and revealed reasoning are marked. Autosaved drafts aren’t submissions and aren’t shown."
            >
              {!detail.attempts.length ? (
                <div className="text-[13px] text-ink-3">No answers yet.</div>
              ) : (
                <ol className="grid">
                  {detail.attempts.map((a) => (
                    <AttemptItem
                      key={a.id}
                      a={a}
                      question={questions[a.question_key]}
                      letter={stepMeta[a.step_key]?.letter ?? a.step_key}
                      onFlag={() => void flag(a)}
                    />
                  ))}
                </ol>
              )}
            </DrawerSection>

            <DrawerSection
              title={`Experiment records (${detail.experiments.length})`}
              note="Entered by the student — not checked against Colab. Deleted records are kept here."
            >
              {!detail.experiments.length ? (
                <div className="text-[13px] text-ink-3">No experiment records.</div>
              ) : (
                <div className="grid gap-2">
                  {detail.experiments.map((e) => (
                    <ExperimentItem key={e.run_uuid} e={e} />
                  ))}
                </div>
              )}
            </DrawerSection>

            <DrawerSection
              title={`Commitments (${detail.commitments.length})`}
              note="The chosen settings and reason, saved before the final test. Earlier choices are never rewritten."
            >
              {!detail.commitments.length ? (
                <div className="text-[13px] text-ink-3">No commitment saved.</div>
              ) : (
                <div className="grid gap-2">
                  {detail.commitments.map((c) => (
                    <CommitmentItem key={c.id} c={c} />
                  ))}
                </div>
              )}
            </DrawerSection>
          </div>
        ) : null}
      </aside>
    </>
  );
}

function DrawerSection({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-2">
      <div>
        <h3 className="font-display text-[18px]">{title}</h3>
        {note ? <p className="text-[12px] text-ink-3">{note}</p> : null}
      </div>
      {children}
    </section>
  );
}

function AttemptItem({
  a,
  question,
  letter,
  onFlag
}: {
  a: DetailAttempt;
  question: QuestionStats | undefined;
  letter: string;
  onFlag: () => void;
}) {
  // An answer to another version of the question isn't read with this version's option texts and tags.
  const option =
    a.answer?.choice != null && !a.question_changed ? question?.options.find((o) => o.id === a.answer?.choice) : undefined;
  return (
    <li className="grid gap-1 border-b border-line-soft py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-ink-3">
        <span className="tnum">{fmtDate(a.submitted_at)}</span>
        <span>·</span>
        <span className="font-semibold text-ink-2">{letter}</span>
        <span className="font-mono">{a.question_key}</span>
        {a.kind === 'reveal' ? (
          <span className="pill pill-info">
            {a.attempt_number === 0 ? 'revealed the reasoning before answering' : 'revealed the reasoning'}
          </span>
        ) : (
          <>
            <span className="pill">try {a.attempt_number}</span>
            {a.attempt_number === 1 && !a.after_feedback ? <span className="pill pill-forest">first try</span> : null}
            {a.attempt_number === 1 && a.after_feedback ? (
              <span className="pill pill-terra">first answer, after revealing — not independent</span>
            ) : a.after_feedback ? (
              <span className="pill pill-terra">after feedback</span>
            ) : null}
            {a.correct === true ? (
              <span className="pill pill-ok">✓ correct</span>
            ) : a.correct === false ? (
              <span className="pill pill-bad">✗ incorrect</span>
            ) : (
              <span className="pill">ungraded</span>
            )}
          </>
        )}
      </div>
      {question ? (
        <div dir="rtl" className="truncate text-[12px] text-ink-3" title={plainInline(question.prompt)}>
          {plainInline(question.prompt)}
        </div>
      ) : null}
      {a.answer?.choice != null ? (
        <div className="text-[13px]">
          Chose <span className="font-mono">{a.answer.choice}</span>
          {option ? (
            <>
              :{' '}
              <span dir="rtl">
                <InlineText text={option.text} />
              </span>
              {!option.correct && option.misconception ? (
                <span className="pill pill-warn ml-1.5">{option.misconception}</span>
              ) : null}
            </>
          ) : null}
          {a.question_changed ? (
            <span className="ml-1.5 text-[12px] text-ink-3">
              (answered another version of this question — its options read differently there)
            </span>
          ) : null}
        </div>
      ) : null}
      {a.answer?.text ? (
        <div className="grid gap-1">
          <p dir="auto" className="whitespace-pre-wrap rounded-md bg-paper-2 px-3 py-2 text-[13px] leading-relaxed">
            {a.answer.text}
          </p>
          <div>
            <button
              type="button"
              aria-pressed={a.review_flag}
              onClick={onFlag}
              className={`rounded-full border px-2.5 py-0.5 text-[12px] ${
                a.review_flag ? 'border-terracotta bg-terracotta-tint text-ink' : 'border-border bg-card text-ink-2 hover:border-ink-4'
              }`}
            >
              {a.review_flag ? '⚑ Flagged for review' : '⚐ Flag for review'}
            </button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function ExperimentItem({ e }: { e: DetailExperiment }) {
  // The student may save a prediction first and edit the record after the run:
  // show the first saved prediction whenever it differs from the current one.
  const rewritten = !!e.first_hypothesis && e.first_hypothesis !== e.hypothesis;
  const texts: [string, string][] = [
    ...(rewritten
      ? ([
          [`First prediction (saved ${fmtDate(e.first_hypothesis_at)})`, e.first_hypothesis as string],
          [`Prediction — edited later (last edit ${fmtDate(e.updated_at)})`, e.hypothesis]
        ] as [string, string][])
      : ([
          [
            e.first_hypothesis
              ? `Prediction (unchanged since saved ${fmtDate(e.first_hypothesis_at)})`
              : 'Prediction (student-entered; may have been edited later)',
            e.hypothesis
          ]
        ] as [string, string][])),
    ['Observation', e.observation],
    ['Explanation', e.explanation]
  ];
  return (
    <div className={`rounded-md border border-line-soft p-3 ${e.deleted_at ? 'bg-paper-2 opacity-75' : ''}`}>
      <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-ink-3">
        <span>{fmtDate(e.created_at)}</span>
        {e.updated_at !== e.created_at ? <span>· edited {fmtDate(e.updated_at)}</span> : null}
        <span>· revision {e.revision}</span>
        {e.complete ? <span className="pill pill-ok">complete record</span> : <span className="pill">incomplete</span>}
        {e.deleted_at ? <span className="pill pill-warn">deleted {fmtDate(e.deleted_at)}</span> : null}
      </div>
      <div className="mt-1 text-[13px]">
        <b>{depthText(e.depth_kind, e.depth)}</b> · {e.training_examples ?? '—'} training examples
      </div>
      <div className="tnum text-[13px] text-ink-2">
        train {pct(e.train_accuracy)} · validation {pct(e.validation_accuracy)} · baseline (validation){' '}
        {pct(e.baseline_validation)}
      </div>
      {texts.map(([label, text]) =>
        text ? (
          <div key={label} className="mt-1.5 text-[13px]">
            <div className="text-[11px] text-ink-3">{label}</div>
            <p dir="auto" className="whitespace-pre-wrap leading-relaxed">
              {text}
            </p>
          </div>
        ) : null
      )}
    </div>
  );
}

function CommitmentItem({ c }: { c: Commitment }) {
  return (
    <div className="rounded-md border border-line-soft p-3">
      <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-ink-3">
        <span>{fmtDate(c.committed_at)}</span>
        {c.after_final_seen ? (
          <span className="pill pill-warn">chosen after a final-test result was recorded — the test is no longer independent</span>
        ) : (
          <span className="pill pill-ok">chosen before any final-test result</span>
        )}
        {c.run_uuid ? <span>· from a saved experiment record</span> : null}
      </div>
      <div className="mt-1 text-[13px]">
        <b>{depthText(c.depth_kind, c.depth)}</b> · {c.training_examples} training examples
      </div>
      <p dir="auto" className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed">
        {c.justification}
      </p>
      {c.final ? (
        <div className="mt-2 rounded-md bg-paper-2 px-3 py-2 text-[13px]">
          <div className="tnum">
            Final test: accuracy {pct(c.final.accuracy)} · precision {pct(c.final.precision)} · recall {pct(c.final.recall)}
          </div>
          <div className="text-[12px] text-ink-3">recorded {fmtDate(c.final.recorded_at)} · student-entered</div>
          {c.final.note ? (
            <p dir="auto" className="mt-1 whitespace-pre-wrap">
              {c.final.note}
            </p>
          ) : null}
        </div>
      ) : (
        <div className="mt-1 text-[12px] text-ink-3">No final-test result recorded for this choice.</div>
      )}
    </div>
  );
}
