'use client';

import { useCallback, useEffect, useState } from 'react';

/* One assignment as the student sees it (Hebrew, RTL, phone-first): what it
 * is, whether they submitted, what earns credit, and, once the instructor
 * releases its grade, the score and how it was reached. Rendered for students
 * at /r/<token>/assignments/<id> and read-only in "view as student"; both
 * build it from the same course payload, so they see the same page.
 *
 * Scores are gated by the server: `result` (and a custom rubric's scores)
 * are only present while the assignment's grade is released. This page
 * renders what it is given and never derives a score itself. */

type Dimension = { key: string; max: number; score?: number | null; rationale?: string };
type RubricComponent = { key: string; max: number; dimensions: Dimension[] };
type ScoredComponent = RubricComponent & { multiplier: number; missing: boolean; subtotal: number };

export type AssignmentSummary = {
  id: number;
  name: string;
  assignment_type: string;
  workcode: number;
  // When the system recorded the student's submission (its import time).
  submission: { recorded_at: string | null } | null;
  counts: boolean;
  released: boolean;
  rubric: RubricComponent[];
  result: {
    manual: boolean;
    components: ScoredComponent[];
    feedback: string;
    score: number | null;
    project?: { code: number; report: number; presentation: number | null; bonus: number };
    peer: { rounds: number[]; weight: number; peer: number; auto: number | null } | null;
    adjustment: number | null;
  } | null;
};

/* A custom rubric (/api/r/<token> "rubrics", from the custom rubrics work):
 * criteria always, scores only after release. Absent on a backend without
 * custom rubrics, and for an assignment that has none. */
export type CustomRubric = {
  assignment_id: number;
  name: string;
  assignment_type: string;
  released: boolean;
  counts: boolean;
  criteria: { name: string; description: string; max_points: number; score?: number | null; rationale?: string }[];
  total?: number | null;
  max_total?: number;
  feedback?: string;
};

export type AssignmentData = {
  course: { name: string };
  assignments?: AssignmentSummary[];
  rubrics?: CustomRubric[];
};

export type PortalFrom = 'info' | 'grades' | 'home';

const TYPE_LABEL: Record<string, string> = { HW1: 'תרגיל', HW2: 'תרגיל', PROJECT: 'פרויקט' };

const COMPONENT_LABEL: Record<string, string> = {
  hw2_code: 'המחברת (קוד)',
  project_code: 'קוד',
  project_report: 'דוח'
};
// The custom rubric replaces these (the code part); the report stays fixed.
const CODE_COMPONENTS = new Set(['hw2_code', 'project_code']);

const DIMENSION_LABEL: Record<string, string> = {
  data_scope_adequacy: 'היקף הנתונים',
  processing_description: 'הסבר עיבוד הנתונים',
  processing_implementation: 'מימוש עיבוד הנתונים',
  num_models_baseline: 'מספר מודלים ומודל בסיס',
  models_quality: 'בחירת המודלים',
  experiments_comparison: 'ניסויים והשוואה',
  variable_plots: 'גרפים של המשתנים',
  results_plots: 'גרפים של התוצאות',
  order: 'סדר',
  clarity: 'בהירות',
  code_quality: 'איכות הקוד',
  english_comments_compliance: 'הערות קוד באנגלית',
  research_question_hypothesis: 'שאלת מחקר והשערה',
  data_description: 'תיאור הנתונים',
  data_processing: 'עיבוד הנתונים',
  models_comparison: 'השוואת מודלים',
  results_analysis: 'ניתוח התוצאות',
  consistency_with_code: 'התאמה בין הדוח לקוד'
};

const num = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

/* "score / max", kept left-to-right inside the RTL page. */
function Fraction({ score, max }: { score: number | null; max: number }) {
  return <span dir="ltr">{`${score == null ? '—' : num(score)} / ${num(max)}`}</span>;
}

function formatDate(iso: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleString('he-IL', { day: 'numeric', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function typeLabel(a: Pick<AssignmentSummary, 'assignment_type'>) {
  return TYPE_LABEL[a.assignment_type] ?? 'מטלה';
}

/* The portal's list of assignments; each opens its own page. `from` is the
 * portal tab the list sits on, so the page's back link returns there. */
export function AssignmentsCard({
  assignments,
  href,
  from
}: {
  assignments: AssignmentSummary[];
  href: (id: number, from: PortalFrom) => string;
  from: PortalFrom;
}) {
  if (!assignments.length) return null;
  return (
    <section aria-labelledby={`assignments-${from}`} className="rounded-lg border border-border bg-card p-4 shadow-soft">
      <h2 id={`assignments-${from}`} className="font-hebrew text-[18px]">
        המטלות בקורס
      </h2>
      <ul className="mt-2 grid gap-2">
        {assignments.map((a) => (
          <li key={a.id}>
            <a
              href={href(a.id, from)}
              className="flex min-h-[48px] items-center justify-between gap-3 rounded-md border border-border bg-paper px-4 py-2 text-[15px] text-ink no-underline hover:border-forest"
            >
              <span className="min-w-0">
                <span className="block">{a.name}</span>
                <span className="block text-[12px] text-ink-3">
                  {typeLabel(a)} · {a.submission ? 'הוגש' : 'לא נמצאה הגשה'}
                  {a.result ? ' · הציון פורסם' : ''}
                </span>
              </span>
              <span aria-hidden className="shrink-0 text-ink-3">
                ←
              </span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function AssignmentView({
  assignmentId,
  loader,
  backHref,
  banner
}: {
  assignmentId: number;
  loader: () => Promise<AssignmentData>;
  backHref: string;
  banner?: React.ReactNode;
}) {
  const [data, setData] = useState<AssignmentData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    loader()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // The loader identity changes on every render; the assignment and back link pin it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignmentId, backHref]);

  useEffect(() => {
    load();
  }, [load]);

  const assignment = data?.assignments?.find((a) => a.id === assignmentId) ?? null;
  const custom = data?.rubrics?.find((r) => r.assignment_id === assignmentId) ?? null;

  return (
    <div dir="rtl" lang="he" className="min-h-screen">
      {banner}
      <main className="mx-auto w-full max-w-[640px] px-4 pb-24 pt-4">
        <a href={backHref} className="text-[14px] text-forest hover:underline">
          → חזרה לעמוד הקורס
        </a>
        {error ? (
          <div className="mt-4 rounded-lg border border-bad-soft bg-card p-5 text-[15px]">
            <p role="alert">{error}</p>
            <button type="button" onClick={load} className="mt-3 text-[14px] text-forest underline">
              נסו שוב
            </button>
          </div>
        ) : !data ? (
          <div className="py-16 text-center text-ink-3">טוען…</div>
        ) : !assignment ? (
          <div className="mt-4 rounded-lg border border-border bg-card p-5 text-[15px] text-ink-2">
            המטלה לא נמצאה בקורס הזה.
          </div>
        ) : (
          <AssignmentBody assignment={assignment} custom={custom} courseName={data.course.name} />
        )}
      </main>
    </div>
  );
}

function AssignmentBody({ assignment: a, custom, courseName }: { assignment: AssignmentSummary; custom: CustomRubric | null; courseName: string }) {
  const result = a.result;
  // The custom rubric replaces the fixed code part; its scores arrive only once released.
  const customScored = custom?.released ?? false;
  const fixed = (result ? result.components : a.rubric).filter((c) => !(custom && CODE_COMPONENTS.has(c.key)));
  const feedback = result?.feedback || (customScored ? custom?.feedback ?? '' : '');
  const recorded = formatDate(a.submission?.recorded_at ?? null);

  return (
    <>
      <header className="pb-2 pt-3">
        <div className="text-[12px] tracking-wide text-ink-3">
          {courseName} · {typeLabel(a)}
        </div>
        <h1 className="font-hebrew text-[26px] leading-tight">{a.name}</h1>
      </header>

      <section aria-label="סטטוס" className="rounded-lg border border-border bg-card p-4 shadow-soft">
        <dl className="grid gap-1.5 text-[14px]">
          <Row label="הגשה" value={a.submission ? '✓ הוגש' : 'לא נמצאה הגשה'} />
          {recorded ? <Row label="נקלט במערכת" value={recorded} /> : null}
          <Row label="ציון" value={a.released ? 'פורסם' : 'טרם פורסם'} />
        </dl>
        {a.submission && !a.counts ? (
          <p className="mt-2 text-[13px] text-ink-3">יש לך הגשה מאוחרת יותר מאותו סוג, והיא זו שנספרת בציון.</p>
        ) : null}
      </section>

      {result ? <ResultCard assignment={a} /> : null}

      <section aria-labelledby="rubric" className="mt-4 rounded-lg border border-border bg-card p-4 shadow-soft">
        <h2 id="rubric" className="font-hebrew text-[20px]">
          על מה מקבלים ניקוד
        </h2>
        {!custom && fixed.length === 0 ? (
          <p className="mt-2 text-[14px] text-ink-2">
            אין למטלה הזו מחוון מפורט: ההגשה עצמה מזכה בציון, אלא אם המרצה קבע/ה ציון אחר.
          </p>
        ) : null}
        {result?.manual ? <p className="mt-2 text-[14px] text-ink-2">הציון במטלה הזו נקבע ידנית על ידי המרצה, ולא לפי המחוון.</p> : null}
        {custom ? <CustomRubricSection rubric={custom} scored={customScored} /> : null}
        {fixed.map((c) => (
          <FixedComponent key={c.key} component={c} />
        ))}
        {!result && !customScored ? <p className="mt-3 text-[13px] text-ink-3">הניקוד יופיע כאן אחרי שהמרצה יפרסם את הציון.</p> : null}
      </section>

      {feedback ? (
        <section aria-labelledby="feedback" className="mt-4 rounded-lg border border-border bg-card p-4 shadow-soft">
          <h2 id="feedback" className="font-hebrew text-[18px]">
            משוב מהמרצה
          </h2>
          <p className="mt-2 whitespace-pre-line text-[15px] leading-relaxed" dir="auto">
            {feedback}
          </p>
        </section>
      ) : null}
    </>
  );
}

function ResultCard({ assignment: a }: { assignment: AssignmentSummary }) {
  const result = a.result!;
  return (
    <section aria-labelledby="result" className="mt-4 rounded-lg border border-forest-soft bg-card p-4 shadow-card">
      <h2 id="result" className="font-hebrew text-[20px]">
        הציון שלך
      </h2>
      {result.score != null ? (
        <div className="mt-3 rounded-md bg-forest-tint px-3 py-3 text-center">
          <div className="tnum font-display text-[32px] text-forest" data-testid="assignment-score">
            {num(result.score)}
          </div>
          <div className="text-[13px] text-ink-2">מתוך 100</div>
        </div>
      ) : (
        <p className="mt-2 text-[14px] text-ink-2">ההגשה הזו לא נספרת בציון (נספרת ההגשה המאוחרת יותר מאותו סוג).</p>
      )}
      <dl className="mt-3 grid gap-1 text-[14px] text-ink-2">
        {result.project ? (
          <>
            <Row label="קוד (60%)" value={num(result.project.code)} />
            <Row label="דוח (20%)" value={num(result.project.report)} />
            {result.project.presentation != null ? <Row label="הצגה (20%)" value={num(result.project.presentation)} /> : null}
            {result.project.bonus ? <Row label="בונוס" value={`+${num(result.project.bonus)}`} /> : null}
          </>
        ) : null}
        {result.peer ? (
          <>
            {result.peer.auto != null ? <Row label="ציון הבדיקה" value={num(result.peer.auto)} /> : null}
            <Row
              label={`ביקורת עמיתים (${Math.round(result.peer.weight * 100)}%, סבב ${result.peer.rounds.join(', ')})`}
              value={num(result.peer.peer)}
            />
          </>
        ) : null}
        {result.adjustment ? <Row label="התאמה של המרצה" value={`${result.adjustment > 0 ? '+' : ''}${num(result.adjustment)}`} /> : null}
      </dl>
    </section>
  );
}

function FixedComponent({ component: c }: { component: RubricComponent | ScoredComponent }) {
  const scored = 'subtotal' in c ? c : null;
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[15px] font-semibold">{COMPONENT_LABEL[c.key] ?? c.key}</h3>
        {scored ? (
          <span className="tnum text-[14px] font-semibold">
            <Fraction score={scored.subtotal} max={c.max} />
          </span>
        ) : (
          <span className="text-[13px] text-ink-3">{num(c.max)} נק׳</span>
        )}
      </div>
      {scored?.missing ? <p className="mt-1 text-[13px] text-bad">לא נמצא דוח בהגשה, ולכן החלק הזה קיבל 0.</p> : null}
      {scored && scored.multiplier < 1 ? (
        <p className="mt-1 text-[13px] text-ink-3">
          כולל הפחתה על תאים שלא רצו במחברת (הניקוד הוכפל ב-<span dir="ltr">{num(scored.multiplier)}</span>).
        </p>
      ) : null}
      <ul className="mt-1.5 grid gap-1.5">
        {c.dimensions.map((d) => (
          <Criterion
            key={d.key}
            name={DIMENSION_LABEL[d.key] ?? d.key}
            max={d.max}
            score={scored ? d.score ?? null : undefined}
            rationale={d.rationale}
          />
        ))}
      </ul>
    </div>
  );
}

function CustomRubricSection({ rubric, scored }: { rubric: CustomRubric; scored: boolean }) {
  const maxTotal = rubric.max_total ?? rubric.criteria.reduce((s, c) => s + c.max_points, 0);
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[15px] font-semibold">מחוון המטלה</h3>
        {scored && rubric.total != null ? (
          <span className="tnum text-[14px] font-semibold">
            <Fraction score={rubric.total} max={maxTotal} />
          </span>
        ) : (
          <span className="text-[13px] text-ink-3">{num(maxTotal)} נק׳</span>
        )}
      </div>
      <ul className="mt-1.5 grid gap-1.5">
        {rubric.criteria.map((c, i) => (
          <Criterion
            key={i}
            name={c.name}
            description={c.description}
            max={c.max_points}
            score={scored ? c.score ?? null : undefined}
            rationale={scored ? c.rationale : undefined}
          />
        ))}
      </ul>
    </div>
  );
}

/* One criterion. `score` undefined: not released (no score shown); null:
 * released but not scored. */
function Criterion({
  name,
  description,
  max,
  score,
  rationale
}: {
  name: string;
  description?: string;
  max: number;
  score?: number | null;
  rationale?: string;
}) {
  return (
    <li className="rounded-md border border-line-soft bg-paper px-3 py-2 text-[14px]" data-testid="criterion">
      <div className="flex justify-between gap-2">
        <span dir="auto">{name}</span>
        <span className="tnum shrink-0 text-ink-2">
          {score === undefined ? `${num(max)} נק׳` : <Fraction score={score} max={max} />}
        </span>
      </div>
      {description ? (
        <p className="mt-0.5 text-[13px] text-ink-3" dir="auto">
          {description}
        </p>
      ) : null}
      {rationale ? (
        <p className="mt-1 text-[13px] leading-relaxed text-ink-2" dir="auto">
          {rationale}
        </p>
      ) : null}
    </li>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt>{label}</dt>
      <dd className="tnum text-ink">{value}</dd>
    </div>
  );
}
