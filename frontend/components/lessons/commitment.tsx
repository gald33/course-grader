'use client';

/* Choosing the final settings before the final test, then recording its
 * result. Commitments are never edited: a change of mind adds a new one, and
 * one made after a final result was recorded is flagged by the server
 * (after_final_seen). The website can't see or control Colab; the panel says
 * so. Both forms are drafts (progress drafts commitment_form / final_form)
 * until sent; each send keeps one request_id across retries. */

import { useId, useState } from 'react';

import {
  DepthSelect,
  FieldError,
  NumberField,
  TextArea,
  confirmFractions,
  depthFromValue,
  depthLabel,
  depthValue,
  fieldsOf,
  fractionWarning,
  parseNumber,
  pctText
} from '@/components/lessons/experiments';
import { Ltr } from '@/components/lessons/inline';
import type { LessonApi } from '@/components/lessons/lesson-player';
import { useRequestId } from '@/components/lessons/questions';
import { LessonApiError, type Commitment, type CommitmentInput, type FinalInput } from '@/components/lessons/types';

const CHOICE_KEY = 'commitment_form';
const FINAL_KEY = 'final_form';
const MIN_JUSTIFICATION = 10;

type ChoiceForm = { run_uuid: string; depth: string; training_examples: string; justification: string };
type FinalForm = { commitment_id: number; accuracy: string; precision: string; recall: string; note: string };

function readJson<T>(raw: string | undefined, ok: (v: Record<string, unknown>) => boolean): T | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw);
    return v && typeof v === 'object' && ok(v) ? (v as T) : null;
  } catch {
    return null;
  }
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('he-IL', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' });
}

type Problem = { tone: 'ok' | 'warn' | 'bad'; text: string; retry?: boolean } | null;

export function CommitmentPanel({ api }: { api: LessonApi }) {
  const commitments = api.commitments;
  const latest = commitments.length ? commitments[commitments.length - 1] : null;
  const finalSeen = commitments.some((c) => c.final);
  const [changing, setChanging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const id = useId();

  const showChoiceForm = !latest || changing || !!readJson<ChoiceForm>(api.draft(CHOICE_KEY), () => true);

  return (
    <section aria-labelledby={`${id}-title`} className="grid grid-cols-1 gap-4 rounded-lg border border-border bg-card p-4">
      <div className="grid grid-cols-1 gap-1">
        <h4 id={`${id}-title`} className="font-hebrew text-[18px]">
          הבחירה שלי לפני המבחן הסופי
        </h4>
        <p className="rounded-md bg-warn-soft/50 px-3 py-2 text-[13px] leading-relaxed text-ink">
          האתר לא רואה את קולאב ולא יכול לאכוף מה קורה שם. הסדר תלוי בך: שומרים כאן בחירה ונימוק, ורק אחר כך מריצים את סעיף 8.
          כל בחירה נשמרת לצד הקודמות; בחירה שנעשתה אחרי שנרשמה תוצאת מבחן מסומנת ככזו.
        </p>
      </div>

      {commitments.length ? (
        <ol className="grid grid-cols-1 gap-3" aria-label="הבחירות ששמרת, לפי הסדר">
          {commitments.map((c, i) => (
            <CommitmentRow key={c.id} c={c} n={i + 1} api={api} />
          ))}
        </ol>
      ) : null}

      <p aria-live="polite" className={notice ? 'rounded-md bg-ok-soft px-3 py-2 text-[14px] text-ok' : 'sr-only'}>
        {notice}
      </p>

      {latest && !latest.final ? (
        <FinalForm commitment={latest} n={commitments.length} api={api} onDone={() => setNotice('✓ תוצאת המבחן נשמרה.')} />
      ) : null}

      {showChoiceForm ? (
        <ChoiceFormView
          api={api}
          finalSeen={finalSeen}
          first={!latest}
          onDone={() => {
            setChanging(false);
            setNotice('✓ הבחירה נשמרה. עכשיו מזינים אותה בסעיף 8 בקולאב ומריצים אותו פעם אחת – ואז רושמים כאן את התוצאה.');
          }}
          onCancel={() => setChanging(false)}
        />
      ) : (
        <button
          type="button"
          onClick={() => {
            setNotice(null);
            setChanging(true);
          }}
          className="h-11 justify-self-start rounded-md border border-border px-4 text-[14px]"
        >
          שינוי הבחירה (הבחירה הקודמת תישמר)
        </button>
      )}
    </section>
  );
}

function CommitmentRow({ c, n, api }: { c: Commitment; n: number; api: LessonApi }) {
  const run = c.run_uuid ? api.experiments.findIndex((e) => e.run_uuid === c.run_uuid) : -1;
  return (
    <li className="rounded-md border border-border bg-paper p-3 text-[14px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">
          בחירה {n} · {formatTime(c.committed_at)}
        </span>
        {c.final ? <span className="pill pill-info">נרשמה תוצאת מבחן</span> : <span className="pill">ממתינה לתוצאת המבחן</span>}
      </div>
      {c.after_final_seen ? (
        <p className="mt-2 rounded-md border border-warn bg-warn-soft px-3 py-1.5 text-[13px] font-semibold">
          <span aria-hidden>⚠ </span>נבחר אחרי שנחשפת לתוצאת המבחן — המבחן כבר אינו בדיקה עצמאית
        </p>
      ) : null}
      <p className="mt-2">
        עומק: {depthLabel(c.depth_kind, c.depth)} · דוגמאות אימון: <Ltr>{c.training_examples}</Ltr>
        {run >= 0 ? <span className="text-ink-3"> · לפי ריצה {run + 1} ביומן</span> : null}
      </p>
      <p className="mt-1 leading-relaxed">
        <span className="font-semibold">נימוק: </span>
        <span dir="auto" className="whitespace-pre-wrap">
          {c.justification}
        </span>
      </p>
      {c.final ? (
        <div className="mt-2 rounded-md bg-info-soft/40 px-3 py-2 text-[13px]">
          <span className="font-semibold">המבחן הסופי ({formatTime(c.final.recorded_at)}): </span>
          דיוק <Ltr>{pctText(c.final.accuracy)}</Ltr>
          {c.final.precision != null ? (
            <>
              {' '}
              · <Ltr>precision</Ltr> <Ltr>{pctText(c.final.precision)}</Ltr>
            </>
          ) : null}
          {c.final.recall != null ? (
            <>
              {' '}
              · <Ltr>recall</Ltr> <Ltr>{pctText(c.final.recall)}</Ltr>
            </>
          ) : null}
          {c.final.note ? (
            <p className="mt-1">
              <span dir="auto" className="whitespace-pre-wrap">
                {c.final.note}
              </span>
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function ChoiceFormView({
  api,
  finalSeen,
  first,
  onDone,
  onCancel
}: {
  api: LessonApi;
  finalSeen: boolean;
  first: boolean;
  onDone: () => void;
  onCancel: () => void;
}) {
  const id = useId();
  const stored = readJson<ChoiceForm>(api.draft(CHOICE_KEY), (v) => typeof v.justification === 'string');
  const form: ChoiceForm = stored ?? { run_uuid: '', depth: '', training_examples: '', justification: '' };
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<Problem>(null);
  const requestId = useRequestId(api, 'commitment');
  const runs = api.experiments.filter((e) => e.depth_kind && e.training_examples != null);

  const setForm = (next: ChoiceForm | null) => {
    const blank = !next || (!next.run_uuid && !next.depth && !next.training_examples.trim() && !next.justification.trim());
    api.setDraft(CHOICE_KEY, blank ? null : JSON.stringify(next));
  };
  const update = (patch: Partial<ChoiceForm>) => {
    const next = { ...form, ...patch };
    // A run reference only stays while the settings still match that run.
    if (next.run_uuid && ('depth' in patch || 'training_examples' in patch)) {
      const run = api.experiments.find((e) => e.run_uuid === next.run_uuid);
      if (!run || depthValue(run.depth_kind, run.depth) !== next.depth || String(run.training_examples) !== next.training_examples) {
        next.run_uuid = '';
      }
    }
    setForm(next);
    setFieldErrors({});
    setProblem(null); // an edit makes an earlier "try again" stale
  };

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setProblem(null);
    const errors: Record<string, string> = {};
    const settings = depthFromValue(form.depth);
    const examples = parseNumber(form.training_examples);
    if (!settings.depth_kind) errors.depth_kind = 'בחרו עומק';
    if (examples == null) errors.training_examples = 'הזינו את מספר דוגמאות האימון';
    else if (Number.isNaN(examples)) errors.training_examples = 'הזינו מספר';
    if (form.justification.trim().length < MIN_JUSTIFICATION) errors.justification = `כתבו נימוק של ${MIN_JUSTIFICATION} תווים לפחות`;
    if (Object.keys(errors).length || !settings.depth_kind || examples == null) {
      setFieldErrors(errors);
      return;
    }
    const body: Omit<CommitmentInput, 'request_id'> = {
      run_uuid: form.run_uuid || null,
      depth_kind: settings.depth_kind,
      depth: settings.depth,
      training_examples: examples,
      justification: form.justification
    };
    setBusy(true);
    try {
      await api.commit({ ...body, request_id: requestId.take(JSON.stringify(body)) });
      requestId.done();
      setForm(null);
      onDone();
    } catch (err) {
      const retry = err instanceof LessonApiError && err.code === 'network';
      if (!retry) requestId.done();
      setFieldErrors(fieldsOf(err));
      setProblem({ tone: 'bad', text: `לא נשמר: ${err instanceof Error ? err.message : String(err)}`, retry });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="grid grid-cols-1 gap-3 rounded-md border border-forest-soft bg-paper p-3">
      <h5 className="font-hebrew text-[16px]">{first ? 'שמירת הבחירה' : 'בחירה חדשה'}</h5>
      {finalSeen ? (
        <p className="rounded-md border border-warn bg-warn-soft px-3 py-2 text-[13px] leading-relaxed">
          <span aria-hidden>⚠ </span>כבר רשמת תוצאה של המבחן הסופי. בחירה חדשה תישמר לצד הקודמת ותסומן כבחירה שנעשתה אחרי חשיפה
          למבחן – כי המבחן כבר השפיע עליה.
        </p>
      ) : null}
      {runs.length ? (
        <div className="grid grid-cols-1 gap-1 text-[14px]">
          <label htmlFor={`${id}-run`} className="font-semibold">
            בחירה מריצה שמורה <span className="text-[12px] font-normal text-ink-3">(רשות)</span>
          </label>
          <select
            id={`${id}-run`}
            value={form.run_uuid}
            disabled={busy}
            aria-invalid={!!fieldErrors.run_uuid}
            aria-describedby={fieldErrors.run_uuid ? `${id}-run-error` : undefined}
            onChange={(e) => {
              const run = api.experiments.find((x) => x.run_uuid === e.target.value);
              setFieldErrors({});
              setProblem(null);
              setForm(
                run
                  ? {
                      ...form,
                      run_uuid: run.run_uuid,
                      depth: depthValue(run.depth_kind, run.depth),
                      training_examples: String(run.training_examples ?? '')
                    }
                  : { ...form, run_uuid: '' }
              );
            }}
            className="h-11 w-full rounded-md border border-border bg-white px-2"
          >
            <option value="">בלי ריצה מסוימת – אמלא בעצמי</option>
            {api.experiments.map((e, i) =>
              e.depth_kind && e.training_examples != null ? (
                <option key={e.run_uuid} value={e.run_uuid}>
                  {`ריצה ${i + 1}: עומק ${depthLabel(e.depth_kind, e.depth)}, ${e.training_examples} דוגמאות, אימות ${pctText(e.validation_accuracy)}`}
                </option>
              ) : null
            )}
          </select>
          <FieldError id={`${id}-run-error`} message={fieldErrors.run_uuid} />
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <DepthSelect
          id={`${id}-depth`}
          code="chosen_depth"
          value={form.depth}
          onChange={(v) => update({ depth: v })}
          error={fieldErrors.depth_kind ?? fieldErrors.depth}
          disabled={busy}
        />
        <NumberField
          id={`${id}-examples`}
          label={
            <>
              דוגמאות אימון <span className="text-[12px] font-normal text-ink-3">(<Ltr>chosen_training_examples</Ltr>)</span>
            </>
          }
          integer
          value={form.training_examples}
          onChange={(v) => update({ training_examples: v })}
          error={fieldErrors.training_examples}
          disabled={busy}
        />
      </div>
      <TextArea
        id={`${id}-why`}
        label="נימוק – למה דווקא ההגדרות האלה?"
        hint={
          <>
            לפי מה ביומן (דיוק האימות, הפער מהאימון, קו הבסיס). את אותו נימוק מעתיקים ל-<Ltr>choice_reason</Ltr> בסעיף 8.
          </>
        }
        value={form.justification}
        error={fieldErrors.justification}
        onChange={(v) => update({ justification: v })}
        disabled={busy}
      />
      <Message problem={problem} busy={busy} onRetry={() => void submit()} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span aria-live="polite" className="text-[12px]">
          {api.preview ? null : <DraftNote status={api.draftStatus(CHOICE_KEY)} />}
        </span>
        <span className="flex gap-2">
          {!first ? (
            <button
              type="button"
              onClick={() => {
                setForm(null);
                onCancel();
              }}
              className="h-11 rounded-md border border-border px-4 text-[14px]"
            >
              ביטול
            </button>
          ) : null}
          <button type="submit" disabled={busy} className="h-11 rounded-md bg-forest px-5 text-[15px] font-semibold text-paper disabled:opacity-50">
            {busy ? 'שומר…' : 'שמירת הבחירה'}
          </button>
        </span>
      </div>
    </form>
  );
}

function FinalForm({ commitment, n, api, onDone }: { commitment: Commitment; n: number; api: LessonApi; onDone: () => void }) {
  const id = useId();
  const stored = readJson<FinalForm>(api.draft(FINAL_KEY), (v) => v.commitment_id === commitment.id);
  const form: FinalForm = stored ?? { commitment_id: commitment.id, accuracy: '', precision: '', recall: '', note: '' };
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<Problem>(null);

  const update = (patch: Partial<FinalForm>) => {
    const next = { ...form, ...patch };
    const blank = !next.accuracy.trim() && !next.precision.trim() && !next.recall.trim() && !next.note.trim();
    api.setDraft(FINAL_KEY, blank ? null : JSON.stringify(next));
    setFieldErrors({});
    setProblem(null); // an edit makes an earlier "try again" stale
  };

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setProblem(null);
    const errors: Record<string, string> = {};
    const value = (field: string, raw: string, required: boolean) => {
      const v = parseNumber(raw);
      if (v == null) {
        if (required) errors[field] = 'הזינו את הדיוק באחוזים (0–100)';
        return null;
      }
      if (Number.isNaN(v)) {
        errors[field] = 'הזינו מספר';
        return null;
      }
      return v;
    };
    const accuracy = value('final_accuracy_pct', form.accuracy, true);
    const body: FinalInput = {
      final_accuracy_pct: accuracy ?? 0,
      final_precision_pct: value('final_precision_pct', form.precision, false),
      final_recall_pct: value('final_recall_pct', form.recall, false),
      final_note: form.note
    };
    if (Object.keys(errors).length || accuracy == null) {
      setFieldErrors(errors);
      return;
    }
    // The result can be recorded only once, so a value that looks like Colab's
    // fraction is always confirmed (OK converts it to a percentage).
    const fixed = confirmFractions({
      accuracy: body.final_accuracy_pct,
      precision: body.final_precision_pct,
      recall: body.final_recall_pct
    });
    if (!fixed) return;
    if (fixed.changed) {
      const { accuracy: a, precision: p, recall: r } = fixed.values;
      body.final_accuracy_pct = a ?? 0;
      body.final_precision_pct = p;
      body.final_recall_pct = r;
      const text = (v: number | null) => (v == null ? '' : String(v));
      update({ accuracy: text(a), precision: text(p), recall: text(r) });
    }
    setBusy(true);
    try {
      // Recording a final result is once per commitment, so a retry is safe:
      // a repeat after a lost answer gets final_already_recorded.
      await api.recordFinal(commitment.id, body);
      api.setDraft(FINAL_KEY, null);
      onDone();
    } catch (err) {
      const code = err instanceof LessonApiError ? err.code : '';
      setFieldErrors(fieldsOf(err));
      if (code === 'final_already_recorded') {
        setProblem({ tone: 'warn', text: 'תוצאת המבחן לבחירה הזו כבר נשמרה (אולי בלשונית אחרת). רעננו את הדף כדי לראות אותה.' });
      } else {
        setProblem({
          tone: 'bad',
          text: `לא נשמר: ${err instanceof Error ? err.message : String(err)}`,
          retry: code === 'network'
        });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="grid grid-cols-1 gap-3 rounded-md border border-info-soft bg-paper p-3">
      <h5 className="font-hebrew text-[16px]">תוצאת המבחן הסופי – לבחירה {n}</h5>
      <p className="text-[13px] leading-relaxed text-ink-2">
        אחרי שהרצתם את סעיף 8 פעם אחת, רשמו כאן מה יצא. הדיוק חובה; <Ltr>precision</Ltr> ו-<Ltr>recall</Ltr> הם הרחבה (רשות).
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <NumberField
          id={`${id}-acc`}
          label={
            <>
              דיוק <span className="text-[12px] font-normal text-ink-3">(<Ltr>final_test_accuracy</Ltr>)</span>
            </>
          }
          suffix="%"
          value={form.accuracy}
          onChange={(v) => update({ accuracy: v })}
          error={fieldErrors.final_accuracy_pct}
          warning={fractionWarning(form.accuracy)}
          disabled={busy}
        />
        <NumberField
          id={`${id}-precision`}
          label={
            <>
              <Ltr>precision</Ltr> <span className="text-[12px] font-normal text-ink-3">(רשות)</span>
            </>
          }
          suffix="%"
          value={form.precision}
          onChange={(v) => update({ precision: v })}
          error={fieldErrors.final_precision_pct}
          warning={fractionWarning(form.precision)}
          disabled={busy}
        />
        <NumberField
          id={`${id}-recall`}
          label={
            <>
              <Ltr>recall</Ltr> <span className="text-[12px] font-normal text-ink-3">(רשות)</span>
            </>
          }
          suffix="%"
          value={form.recall}
          onChange={(v) => update({ recall: v })}
          error={fieldErrors.final_recall_pct}
          warning={fractionWarning(form.recall)}
          disabled={busy}
        />
      </div>
      <TextArea
        id={`${id}-note`}
        label="הערה (רשות) – איך התוצאה משתווה לאימות?"
        value={form.note}
        error={fieldErrors.final_note}
        onChange={(v) => update({ note: v })}
        disabled={busy}
        rows={2}
      />
      <Message problem={problem} busy={busy} onRetry={() => void submit()} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span aria-live="polite" className="text-[12px]">
          {api.preview ? null : <DraftNote status={api.draftStatus(FINAL_KEY)} />}
        </span>
        <button type="submit" disabled={busy} className="h-11 rounded-md bg-forest px-5 text-[15px] font-semibold text-paper disabled:opacity-50">
          {busy ? 'שומר…' : 'שמירת התוצאה'}
        </button>
      </div>
    </form>
  );
}

function Message({ problem, busy, onRetry }: { problem: Problem; busy: boolean; onRetry: () => void }) {
  return (
    <div aria-live="polite">
      {problem ? (
        <p
          role={problem.tone === 'bad' ? 'alert' : undefined}
          className={`flex flex-wrap items-center gap-2 rounded-md px-3 py-2 text-[14px] ${
            problem.tone === 'ok' ? 'bg-ok-soft text-ok' : problem.tone === 'warn' ? 'bg-warn-soft text-ink' : 'bg-bad-soft text-bad'
          }`}
        >
          <span>{problem.text}</span>
          {problem.retry ? (
            <button type="button" onClick={onRetry} disabled={busy} className="font-semibold underline">
              ניסיון חוזר
            </button>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

function DraftNote({ status }: { status: ReturnType<LessonApi['draftStatus']> }) {
  if (status === 'saving') return <span className="text-ink-3">הטיוטה נשמרת…</span>;
  if (status === 'saved') return <span className="text-ok">✓ הטיוטה נשמרה (עוד לא נשלחה)</span>;
  if (status === 'error') return <span className="text-bad">⚠ הטיוטה לא נשמרה בשרת – היא שמורה במכשיר הזה</span>;
  return null;
}
