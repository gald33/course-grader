'use client';

/* The student's experiment log for the Colab runs. Values are typed in by the
 * student (never fetched from Colab) and labelled as such. Percentages are
 * entered 0–100 and sent as *_pct; the API stores fractions. Depth is either a
 * whole number or "unlimited" (Colab's 0) — never a numeric 0. The add/edit
 * form is a draft (progress drafts key experiment_form, mirrored on the
 * device) until it is saved; invalid values come back per field and nothing
 * the student typed is cleared. */

import { useId, useRef, useState } from 'react';

import { InlineText, Ltr } from '@/components/lessons/inline';
import type { LessonApi } from '@/components/lessons/lesson-player';
import { newUuid } from '@/components/lessons/student-backend';
import {
  LessonApiError,
  type Block,
  type DepthKind,
  type Experiment,
  type ExperimentInput
} from '@/components/lessons/types';

export const MAX_DEPTH = 50;
export const MIN_EXAMPLES = 20;
export const MAX_EXAMPLES = 720;

/* ---------------- Shared helpers (also used by commitment.tsx / summary.tsx) ---------------- */

export function depthLabel(kind: DepthKind | null, depth: number | null): string {
  if (kind === 'unlimited') return 'ללא הגבלה (בקולאב 0)';
  if (kind === 'limited' && depth != null) return String(depth);
  return '—';
}

/** A stored fraction as the percentage the student typed. */
export function pctText(fraction: number | null | undefined): string {
  return fraction == null ? '—' : `${+(fraction * 100).toFixed(4)}%`;
}

export function pctInput(fraction: number | null | undefined): string {
  return fraction == null ? '' : String(+(fraction * 100).toFixed(4));
}

/** '' → null; a number (comma or dot decimals) → number; anything else → NaN. */
export function parseNumber(raw: string): number | null {
  const s = raw.trim().replace(',', '.');
  if (s === '') return null;
  return /^[-+]?\d+(\.\d+)?$/.test(s) || /^[-+]?\.\d+$/.test(s) ? Number(s) : NaN;
}

export function depthValue(kind: DepthKind | null, depth: number | null): string {
  return kind === 'unlimited' ? 'unlimited' : kind === 'limited' && depth != null ? String(depth) : '';
}

export function depthFromValue(v: string): { depth_kind: DepthKind | null; depth: number | null } {
  if (v === 'unlimited') return { depth_kind: 'unlimited', depth: null };
  if (v === '') return { depth_kind: null, depth: null };
  return { depth_kind: 'limited', depth: Number(v) };
}

export function FieldError({ id, message }: { id: string; message?: string | null }) {
  if (!message) return null;
  return (
    <span id={id} className="text-[13px] text-bad">
      ⚠ {message}
    </span>
  );
}

export function DepthSelect({
  id,
  value,
  onChange,
  error,
  disabled
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  error?: string | null;
  disabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-1 content-start gap-1 text-[14px]">
      <label htmlFor={id} className="font-semibold">
        עומק מרבי <span className="text-[12px] font-normal text-ink-3">(<Ltr>tree_depth</Ltr>)</span>
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        aria-invalid={!!error}
        aria-describedby={`${id}-hint${error ? ` ${id}-error` : ''}`}
        onChange={(e) => onChange(e.target.value)}
        className="h-11 w-full rounded-md border border-border bg-white px-2"
      >
        <option value="">בחרו עומק</option>
        {Array.from({ length: MAX_DEPTH }, (_, i) => i + 1).map((d) => (
          <option key={d} value={String(d)}>
            {d}
          </option>
        ))}
        <option value="unlimited">ללא הגבלה (בקולאב: 0)</option>
      </select>
      <span id={`${id}-hint`} className="text-[12px] text-ink-3">
        בקולאב <Ltr>0</Ltr> פירושו ללא הגבלה – כאן בוחרים ״ללא הגבלה״, לא <Ltr>0</Ltr>.
      </span>
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}

export function NumberField({
  id,
  label,
  hint,
  value,
  onChange,
  error,
  warning,
  suffix,
  integer,
  disabled
}: {
  id: string;
  label: React.ReactNode;
  hint?: React.ReactNode;
  value: string;
  onChange: (v: string) => void;
  error?: string | null;
  warning?: string | null;
  suffix?: string;
  integer?: boolean;
  disabled?: boolean;
}) {
  const described = [hint ? `${id}-hint` : '', error ? `${id}-error` : '', warning ? `${id}-warn` : ''].filter(Boolean).join(' ');
  return (
    <div className="grid grid-cols-1 content-start gap-1 text-[14px]">
      <label htmlFor={id} className="font-semibold">
        {label}
      </label>
      <div dir="ltr" className="flex items-center gap-1.5">
        <input
          id={id}
          type="text"
          inputMode={integer ? 'numeric' : 'decimal'}
          autoComplete="off"
          value={value}
          disabled={disabled}
          aria-invalid={!!error}
          aria-describedby={described || undefined}
          onChange={(e) => onChange(e.target.value)}
          className="h-11 w-full min-w-0 rounded-md border border-border bg-white px-3 text-left text-[16px] tnum"
        />
        {suffix ? (
          <span aria-hidden className="text-[15px] text-ink-2">
            {suffix}
          </span>
        ) : null}
      </div>
      {hint ? (
        <span id={`${id}-hint`} className="text-[12px] text-ink-3">
          {hint}
        </span>
      ) : null}
      <FieldError id={`${id}-error`} message={error} />
      {warning && !error ? (
        <span id={`${id}-warn`} className="text-[12px] text-warn">
          ⚠ {warning}
        </span>
      ) : null}
    </div>
  );
}

/** Soft check: Colab shows accuracy as a fraction (0.762); here it's 76.2. */
export function fractionWarning(raw: string): string | null {
  const v = parseNumber(raw);
  return v != null && !Number.isNaN(v) && v > 0 && v <= 1 ? 'נראה כמו שבר מקולאב. כאן מזינים אחוזים: 0.762 → 76.2' : null;
}

export function fieldsOf(e: unknown): Record<string, string> {
  if (e instanceof LessonApiError && e.detail.fields && typeof e.detail.fields === 'object') {
    return e.detail.fields as Record<string, string>;
  }
  return {};
}

/* ---------------- The log ---------------- */

type LogBlock = Extract<Block, { type: 'experiment_log' }>;

type Form = {
  run_uuid: string;
  editing: boolean;
  expected_revision: number | null;
  depth: string; // '' | '1'..'50' | 'unlimited'
  training_examples: string;
  train: string;
  validation: string;
  baseline: string;
  hypothesis: string;
  observation: string;
  explanation: string;
};

const FORM_KEY = 'experiment_form';

// Form field → the request field the API reports errors for.
const SERVER_FIELD: Record<string, string[]> = {
  depth: ['depth', 'depth_kind'],
  training_examples: ['training_examples'],
  train: ['train_accuracy_pct'],
  validation: ['validation_accuracy_pct'],
  baseline: ['baseline_validation_pct'],
  hypothesis: ['hypothesis'],
  observation: ['observation'],
  explanation: ['explanation']
};

function blankForm(run_uuid: string): Form {
  return {
    run_uuid,
    editing: false,
    expected_revision: null,
    depth: '',
    training_examples: '',
    train: '',
    validation: '',
    baseline: '',
    hypothesis: '',
    observation: '',
    explanation: ''
  };
}

function parseForm(raw: string | undefined): Form | null {
  if (!raw) return null;
  try {
    const f = JSON.parse(raw);
    if (!f || typeof f.run_uuid !== 'string') return null;
    const s = (v: unknown) => (typeof v === 'string' ? v : '');
    return {
      run_uuid: f.run_uuid,
      editing: f.editing === true,
      expected_revision: typeof f.expected_revision === 'number' ? f.expected_revision : null,
      depth: s(f.depth),
      training_examples: s(f.training_examples),
      train: s(f.train),
      validation: s(f.validation),
      baseline: s(f.baseline),
      hypothesis: s(f.hypothesis),
      observation: s(f.observation),
      explanation: s(f.explanation)
    };
  } catch {
    return null;
  }
}

function isBlank(f: Form) {
  return (
    !f.editing &&
    [f.depth, f.training_examples, f.train, f.validation, f.baseline, f.hypothesis, f.observation, f.explanation].every(
      (v) => !v.trim()
    )
  );
}

function formFromExperiment(e: Experiment): Form {
  return {
    run_uuid: e.run_uuid,
    editing: true,
    expected_revision: e.revision,
    depth: depthValue(e.depth_kind, e.depth),
    training_examples: e.training_examples == null ? '' : String(e.training_examples),
    train: pctInput(e.train_accuracy),
    validation: pctInput(e.validation_accuracy),
    baseline: pctInput(e.baseline_validation),
    hypothesis: e.hypothesis,
    observation: e.observation,
    explanation: e.explanation
  };
}

function toInput(f: Form): { input: ExperimentInput | null; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const num = (field: string, raw: string) => {
    const v = parseNumber(raw);
    if (v != null && Number.isNaN(v)) errors[field] = 'הזינו מספר';
    return v == null || Number.isNaN(v) ? null : v;
  };
  const settings = depthFromValue(f.depth);
  const input: ExperimentInput = {
    expected_revision: f.editing ? f.expected_revision : null,
    depth_kind: settings.depth_kind,
    depth: settings.depth,
    training_examples: num('training_examples', f.training_examples),
    train_accuracy_pct: num('train_accuracy_pct', f.train),
    validation_accuracy_pct: num('validation_accuracy_pct', f.validation),
    baseline_validation_pct: num('baseline_validation_pct', f.baseline),
    hypothesis: f.hypothesis,
    observation: f.observation,
    explanation: f.explanation
  };
  return { input: Object.keys(errors).length ? null : input, errors };
}

/** Did a create whose answer got lost actually land? */
function matches(e: Experiment, input: ExperimentInput) {
  const close = (a: number | null, pct: number | null) => (a == null ? pct == null : pct != null && Math.abs(a * 100 - pct) < 1e-4);
  return (
    e.depth_kind === input.depth_kind &&
    e.depth === input.depth &&
    e.training_examples === input.training_examples &&
    close(e.train_accuracy, input.train_accuracy_pct) &&
    close(e.validation_accuracy, input.validation_accuracy_pct) &&
    close(e.baseline_validation, input.baseline_validation_pct) &&
    e.hypothesis === input.hypothesis.trim() &&
    e.observation === input.observation.trim() &&
    e.explanation === input.explanation.trim()
  );
}

function missingParts(e: Experiment): string[] {
  const out: string[] = [];
  if (!e.depth_kind) out.push('עומק');
  if (e.training_examples == null) out.push('מספר דוגמאות');
  if (e.train_accuracy == null) out.push('דיוק אימון');
  if (e.validation_accuracy == null) out.push('דיוק אימות');
  if (e.baseline_validation == null) out.push('קו בסיס');
  if (!e.observation.trim()) out.push('תצפית');
  return out;
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('he-IL', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function points(v: number) {
  return `${+Math.abs(v).toFixed(2)}`;
}

/** How a run compares to its baseline (and its own training accuracy). */
export function BaselineHint({ validation, baseline, train }: { validation: number | null; baseline: number | null; train?: number | null }) {
  if (validation == null || baseline == null) return null;
  const diff = (validation - baseline) * 100;
  const gap = train != null ? (train - validation) * 100 : null;
  return (
    <p className="text-[13px] leading-relaxed text-ink-2">
      {diff > 0 ? (
        <>
          <span aria-hidden>▲ </span>האימות גבוה מקו הבסיס ב-<Ltr>{points(diff)}</Ltr> נקודות אחוז.
        </>
      ) : (
        <>
          <span aria-hidden>▼ </span>האימות {diff === 0 ? 'שווה לקו הבסיס' : <>נמוך מקו הבסיס ב-<Ltr>{points(diff)}</Ltr> נקודות אחוז</>} – העץ לא מראה
          כאן יתרון על ניחוש קבוע.
        </>
      )}
      {gap != null ? (
        <>
          {' '}
          פער אימון–אימות: <Ltr>{points(gap)}</Ltr> נקודות{gap < 0 ? ' (האימות גבוה מהאימון)' : ''}.
        </>
      ) : null}
    </p>
  );
}

export function ExperimentLog({ block, api }: { block: LogBlock; api: LessonApi }) {
  const freshUuid = useRef(newUuid());
  const stored = parseForm(api.draft(FORM_KEY));
  const form = stored ?? blankForm(freshUuid.current);
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ tone: 'ok' | 'warn' | 'bad'; text: string; retry?: boolean } | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const id = useId();
  const experiments = api.experiments;
  const complete = experiments.filter((e) => e.complete).length;

  const setForm = (next: Form | null) => {
    api.setDraft(FORM_KEY, next && !isBlank(next) ? JSON.stringify(next) : null);
  };
  const update = (patch: Partial<Form>) => {
    setForm({ ...form, ...patch });
    setFieldErrors((f) => {
      const n = { ...f };
      for (const k of Object.keys(patch)) for (const field of SERVER_FIELD[k] ?? []) delete n[field];
      return n;
    });
  };
  const reset = () => {
    freshUuid.current = newUuid();
    setForm(null);
    setFieldErrors({});
  };

  const save = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setMessage(null);
    const { input, errors } = toInput(form);
    if (!input) {
      setFieldErrors(errors);
      setMessage({ tone: 'bad', text: 'חלק מהערכים אינם מספרים – תקנו את השדות המסומנים.' });
      return;
    }
    setBusy(true);
    try {
      await api.saveExperiment(form.run_uuid, input);
      reset();
      setMessage({ tone: 'ok', text: form.editing ? '✓ השינויים נשמרו.' : '✓ הריצה נשמרה ביומן.' });
    } catch (err) {
      if (err instanceof LessonApiError && err.code === 'invalid_values') {
        setFieldErrors(fieldsOf(err));
        setMessage({ tone: 'bad', text: `${err.message}. שום דבר לא נשמר, והטופס נשאר כפי שהוא.` });
      } else if (err instanceof LessonApiError && err.code === 'stale') {
        const current = (err.detail.current as Experiment | null | undefined) ?? null;
        if (current && matches(current, input)) {
          // A retried save whose first attempt had already landed.
          api.replaceExperiment(form.run_uuid, current);
          reset();
          setMessage({ tone: 'ok', text: '✓ הריצה נשמרה ביומן.' });
        } else if (current) {
          api.replaceExperiment(form.run_uuid, current);
          setForm({ ...form, editing: true, expected_revision: current.revision });
          setMessage({
            tone: 'warn',
            text: 'הריצה הזו עודכנה בלשונית או במכשיר אחר. הגרסה השמורה מוצגת עכשיו ברשימה; הטופס שלך לא השתנה – שמירה נוספת תחליף את הגרסה השמורה.'
          });
        } else {
          api.replaceExperiment(form.run_uuid, null);
          setForm({ ...form, run_uuid: newUuid(), editing: false, expected_revision: null });
          setMessage({
            tone: 'warn',
            text: 'הריצה הזו נמחקה בלשונית או במכשיר אחר. הטופס שלך נשאר – אפשר לשמור אותו כריצה חדשה.'
          });
        }
      } else {
        const retry = err instanceof LessonApiError && err.code === 'network';
        setMessage({ tone: 'bad', text: `לא נשמר: ${err instanceof Error ? err.message : String(err)}`, retry });
      }
    } finally {
      setBusy(false);
    }
  };

  const edit = (e: Experiment) => {
    if (!isBlank(form) && !(form.editing && form.run_uuid === e.run_uuid)) {
      if (!window.confirm('בטופס יש טיוטה שלא נשמרה. להחליף אותה בריצה שבחרת לעריכה?')) return;
    }
    setMessage(null);
    setFieldErrors({});
    setForm(formFromExperiment(e));
    formRef.current?.scrollIntoView({ block: 'start' });
    window.setTimeout(() => formRef.current?.querySelector<HTMLElement>('textarea, select, input')?.focus(), 0);
  };

  const remove = async (e: Experiment, n: number) => {
    if (!window.confirm(`למחוק את ריצה ${n} מהיומן? היא תוסר מהרשימה שלך (המרצה עדיין יראה שהייתה ונמחקה).`)) return;
    setMessage(null);
    setBusy(true);
    try {
      await api.deleteExperiment(e.run_uuid, e.revision);
      if (form.editing && form.run_uuid === e.run_uuid) reset();
      setMessage({ tone: 'ok', text: `✓ ריצה ${n} נמחקה.` });
    } catch (err) {
      if (err instanceof LessonApiError && err.code === 'stale') {
        const current = (err.detail.current as Experiment | null | undefined) ?? null;
        api.replaceExperiment(e.run_uuid, current);
        setMessage({
          tone: 'warn',
          text: current
            ? 'הריצה עודכנה בלשונית או במכשיר אחר, ולכן לא נמחקה. בדקו את הגרסה המעודכנת ונסו שוב.'
            : 'הריצה כבר נמחקה בלשונית או במכשיר אחר.'
        });
      } else {
        setMessage({ tone: 'bad', text: `לא נמחק: ${err instanceof Error ? err.message : String(err)}` });
      }
    } finally {
      setBusy(false);
    }
  };

  const validationPct = parseNumber(form.validation);
  const baselinePct = parseNumber(form.baseline);
  const trainPct = parseNumber(form.train);
  const ok = (v: number | null) => (v == null || Number.isNaN(v) ? null : v / 100);
  const hypothesisOnly =
    !form.editing && !!form.hypothesis.trim() && [form.depth, form.training_examples, form.train, form.validation, form.baseline, form.observation, form.explanation].every((v) => !v.trim());
  const editingIndex = form.editing ? experiments.findIndex((x) => x.run_uuid === form.run_uuid) : -1;

  return (
    <section aria-labelledby={`${id}-title`} className="grid grid-cols-1 gap-4 rounded-lg border border-border bg-card p-4">
      <div className="grid grid-cols-1 gap-1">
        <h4 id={`${id}-title`} className="font-hebrew text-[18px]">
          יומן הניסויים שלי
        </h4>
        <p className="text-[13px] text-ink-2">
          ריצות מלאות ביומן: <Ltr>{complete}</Ltr> מתוך <Ltr>{block.min_complete}</Ltr> נדרשות. ריצה מלאה = הגדרות, שלוש התוצאות
          ותצפית.
        </p>
        <p className="text-[12px] text-ink-3">
          <span className="pill">נתונים שהוזנו ידנית — לא נבדקו מול קולאב</span>
        </p>
      </div>

      {block.suggested_runs.length ? (
        <details className="rounded-md border border-line-soft bg-paper px-3 py-2">
          <summary className="cursor-pointer text-[14px] font-semibold text-forest">ריצות מוצעות</summary>
          <ol className="mt-2 grid grid-cols-1 gap-2">
            {block.suggested_runs.map((r, i) => (
              <li key={i} className="flex items-start justify-between gap-3 text-[14px]">
                <span className="min-w-0 flex-1 leading-relaxed">
                  <span className="font-semibold">
                    עומק {depthLabel(r.depth_kind, r.depth)} · <Ltr>{r.training_examples}</Ltr> דוגמאות
                  </span>{' '}
                  <span className="text-ink-2">
                    – <InlineText text={r.note} />
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => update({ depth: depthValue(r.depth_kind, r.depth), training_examples: String(r.training_examples) })}
                  className="h-9 shrink-0 rounded-md border border-forest px-3 text-[13px] text-forest"
                >
                  למלא בטופס
                </button>
              </li>
            ))}
          </ol>
        </details>
      ) : null}

      {experiments.length ? (
        <ol className="grid grid-cols-1 gap-3" aria-label="הריצות ששמרת, לפי סדר השמירה">
          {experiments.map((e, i) => {
            const missing = missingParts(e);
            return (
              <li key={e.run_uuid} className="rounded-md border border-border bg-paper p-3 text-[14px]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold">ריצה {i + 1}</span>
                  {e.complete ? (
                    <span className="pill pill-ok">✓ ריצה מלאה</span>
                  ) : (
                    <span className="pill pill-warn">חלקית – חסר: {missing.join(', ')}</span>
                  )}
                </div>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[13px] sm:grid-cols-3">
                  <div>
                    <dt className="text-ink-3">עומק</dt>
                    <dd>{depthLabel(e.depth_kind, e.depth)}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-3">דוגמאות אימון</dt>
                    <dd>
                      <Ltr>{e.training_examples ?? '—'}</Ltr>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-3">דיוק אימון</dt>
                    <dd>
                      <Ltr>{pctText(e.train_accuracy)}</Ltr>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-3">דיוק אימות</dt>
                    <dd>
                      <Ltr>{pctText(e.validation_accuracy)}</Ltr>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-3">קו בסיס (אימות)</dt>
                    <dd>
                      <Ltr>{pctText(e.baseline_validation)}</Ltr>
                    </dd>
                  </div>
                </dl>
                <div className="mt-2">
                  <BaselineHint validation={e.validation_accuracy} baseline={e.baseline_validation} train={e.train_accuracy} />
                </div>
                {e.hypothesis ? <TextRow label="השערה" text={e.hypothesis} /> : null}
                {e.observation ? <TextRow label="תצפית" text={e.observation} /> : null}
                {e.explanation ? <TextRow label="פרשנות" text={e.explanation} /> : null}
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[12px] text-ink-3">
                    נשמרה {formatTime(e.created_at)}
                    {e.updated_at !== e.created_at ? ` · עודכנה ${formatTime(e.updated_at)}` : ''} · הוזן ידנית
                  </span>
                  <span className="flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => edit(e)}
                      className="h-9 rounded-md border border-border px-3 text-[13px]"
                      aria-label={`עריכת ריצה ${i + 1}`}
                    >
                      עריכה
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => remove(e, i + 1)}
                      className="h-9 rounded-md border border-bad-soft px-3 text-[13px] text-bad"
                      aria-label={`מחיקת ריצה ${i + 1}`}
                    >
                      מחיקה
                    </button>
                  </span>
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-[14px] text-ink-2">עוד אין ריצות ביומן. התחילו בהשערה לריצה הראשונה.</p>
      )}

      <div aria-live="polite">
        {message ? (
          <p
            role={message.tone === 'bad' ? 'alert' : undefined}
            className={`flex flex-wrap items-center gap-2 rounded-md px-3 py-2 text-[14px] ${
              message.tone === 'ok' ? 'bg-ok-soft text-ok' : message.tone === 'warn' ? 'bg-warn-soft text-ink' : 'bg-bad-soft text-bad'
            }`}
          >
            <span>{message.text}</span>
            {message.retry ? (
              <button type="button" onClick={() => void save()} disabled={busy} className="font-semibold underline">
                ניסיון חוזר
              </button>
            ) : null}
          </p>
        ) : null}
      </div>

      <form ref={formRef} onSubmit={save} className="grid grid-cols-1 scroll-mt-16 gap-3 rounded-md border border-forest-soft bg-paper p-3" noValidate>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h5 className="font-hebrew text-[16px]">
            {form.editing ? `עריכת ריצה ${editingIndex >= 0 ? editingIndex + 1 : ''}` : 'ריצה חדשה'}
          </h5>
          {!isBlank(form) ? (
            <button
              type="button"
              onClick={() => {
                if (window.confirm(form.editing ? 'לבטל את העריכה? השינויים שלא נשמרו יימחקו.' : 'לנקות את הטופס? הטיוטה תימחק.')) {
                  reset();
                  setMessage(null);
                }
              }}
              className="text-[13px] text-ink-3 underline"
            >
              {form.editing ? 'ביטול העריכה' : 'ניקוי הטופס'}
            </button>
          ) : null}
        </div>

        <TextArea
          id={`${id}-hypothesis`}
          label="השערה – מה לדעתך יקרה, ולמה?"
          hint="כותבים לפני הריצה. אפשר לשמור את ההשערה לבד ולהשלים את התוצאות אחר כך."
          value={form.hypothesis}
          error={fieldErrors.hypothesis}
          onChange={(v) => update({ hypothesis: v })}
          disabled={busy}
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <DepthSelect
            id={`${id}-depth`}
            value={form.depth}
            onChange={(v) => update({ depth: v })}
            error={fieldErrors.depth ?? fieldErrors.depth_kind}
            disabled={busy}
          />
          <NumberField
            id={`${id}-examples`}
            label={
              <>
                דוגמאות אימון <span className="text-[12px] font-normal text-ink-3">(<Ltr>training_examples</Ltr>)</span>
              </>
            }
            hint={
              <>
                מספר שלם בין <Ltr>{MIN_EXAMPLES}</Ltr> ל-<Ltr>{MAX_EXAMPLES}</Ltr>
              </>
            }
            integer
            value={form.training_examples}
            onChange={(v) => update({ training_examples: v })}
            error={fieldErrors.training_examples}
            disabled={busy}
          />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <NumberField
            id={`${id}-train`}
            label={
              <>
                דיוק אימון <span className="text-[12px] font-normal text-ink-3">(<Ltr>train_accuracy</Ltr>)</span>
              </>
            }
            suffix="%"
            value={form.train}
            onChange={(v) => update({ train: v })}
            error={fieldErrors.train_accuracy_pct}
            warning={fractionWarning(form.train)}
            disabled={busy}
          />
          <NumberField
            id={`${id}-validation`}
            label={
              <>
                דיוק אימות <span className="text-[12px] font-normal text-ink-3">(<Ltr>validation_accuracy</Ltr>)</span>
              </>
            }
            suffix="%"
            value={form.validation}
            onChange={(v) => update({ validation: v })}
            error={fieldErrors.validation_accuracy_pct}
            warning={fractionWarning(form.validation)}
            disabled={busy}
          />
          <NumberField
            id={`${id}-baseline`}
            label={
              <>
                קו בסיס <span className="text-[12px] font-normal text-ink-3">(<Ltr>baseline_validation</Ltr>)</span>
              </>
            }
            suffix="%"
            value={form.baseline}
            onChange={(v) => update({ baseline: v })}
            error={fieldErrors.baseline_validation_pct}
            warning={fractionWarning(form.baseline)}
            disabled={busy}
          />
        </div>
        <p className="text-[12px] text-ink-3">
          אחוזים בין <Ltr>0</Ltr> ל-<Ltr>100</Ltr>. בקולאב הדיוק מופיע כשבר: <Ltr>0.762</Ltr> → כאן <Ltr>76.2</Ltr>.
        </p>
        <BaselineHint validation={ok(validationPct)} baseline={ok(baselinePct)} train={ok(trainPct)} />
        <TextArea
          id={`${id}-observation`}
          label="תצפית – מה ראית (מספרים, העץ)"
          value={form.observation}
          error={fieldErrors.observation}
          onChange={(v) => update({ observation: v })}
          disabled={busy}
        />
        <TextArea
          id={`${id}-explanation`}
          label="פרשנות – למה לדעתך זה קרה?"
          value={form.explanation}
          error={fieldErrors.explanation}
          onChange={(v) => update({ explanation: v })}
          disabled={busy}
        />
        {fieldErrors.run_uuid || fieldErrors.expected_revision ? (
          <p className="text-[13px] text-bad">⚠ {fieldErrors.run_uuid ?? fieldErrors.expected_revision}</p>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span aria-live="polite" className="text-[12px]">
            {api.preview ? null : <FormDraftNote status={api.draftStatus(FORM_KEY)} />}
          </span>
          <button
            type="submit"
            disabled={busy || isBlank(form)}
            className="h-11 shrink-0 rounded-md bg-forest px-5 text-[15px] font-semibold text-paper disabled:opacity-50"
          >
            {busy ? 'שומר…' : form.editing ? 'שמירת השינויים' : hypothesisOnly ? 'שמירת ההשערה' : 'שמירת הריצה'}
          </button>
        </div>
      </form>
    </section>
  );
}

function FormDraftNote({ status }: { status: ReturnType<LessonApi['draftStatus']> }) {
  if (status === 'saving') return <span className="text-ink-3">הטיוטה נשמרת…</span>;
  if (status === 'saved') return <span className="text-ok">✓ הטיוטה נשמרה (הריצה עוד לא נשמרה ביומן)</span>;
  if (status === 'error') return <span className="text-bad">⚠ הטיוטה לא נשמרה בשרת – היא שמורה במכשיר הזה</span>;
  return null;
}

function TextRow({ label, text }: { label: string; text: string }) {
  return (
    <p className="mt-1.5 leading-relaxed">
      <span className="font-semibold">{label}: </span>
      <span dir="auto" className="whitespace-pre-wrap">
        {text}
      </span>
    </p>
  );
}

export function TextArea({
  id,
  label,
  hint,
  value,
  error,
  onChange,
  disabled,
  rows = 3
}: {
  id: string;
  label: React.ReactNode;
  hint?: React.ReactNode;
  value: string;
  error?: string | null;
  onChange: (v: string) => void;
  disabled?: boolean;
  rows?: number;
}) {
  const described = [hint ? `${id}-hint` : '', error ? `${id}-error` : ''].filter(Boolean).join(' ');
  return (
    <div className="grid grid-cols-1 gap-1 text-[14px]">
      <label htmlFor={id} className="font-semibold">
        {label}
      </label>
      {hint ? (
        <span id={`${id}-hint`} className="text-[12px] text-ink-3">
          {hint}
        </span>
      ) : null}
      <textarea
        id={id}
        dir="auto"
        rows={rows}
        maxLength={5000}
        value={value}
        disabled={disabled}
        aria-invalid={!!error}
        aria-describedby={described || undefined}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-white px-3 py-2 text-[15px] leading-relaxed outline-none focus:border-forest focus:ring-2 focus:ring-forest-tint"
      />
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}
