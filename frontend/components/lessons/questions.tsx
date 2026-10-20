'use client';

/* One lesson question. Practice questions: unlimited tries, specific feedback
 * right away, and "הצג הסבר" to reveal the reasoning (recorded). Check
 * questions (individual understanding checks): answer alone first; the first
 * answer is kept and every correction is a new attempt. Free text is never
 * graded: after sending, a sample reasoning and rubric are shown. Typed text is
 * a draft (progress drafts, key q:<key>) until it is sent; a sent answer is an
 * attempt. Feedback appears only from the server's answer, and each send keeps
 * one request_id across retries so a lost answer is never recorded twice. */

import { useId, useState } from 'react';

import { InlineText, Ltr } from '@/components/lessons/inline';
import type { DraftStatus, LessonApi } from '@/components/lessons/lesson-player';
import { newUuid } from '@/components/lessons/student-backend';
import {
  LessonApiError,
  type Answer,
  type FreeTextQuestion,
  type Question,
  type QuestionState,
  type SingleChoiceQuestion
} from '@/components/lessons/types';

const EMPTY_STATE: QuestionState = { attempts: 0, revealed: false, first: null, latest: null, feedback: null };
const MIN_EXPLANATION = 10;

function formatTime(iso: string | null | undefined) {
  if (!iso) return '';
  return new Date(iso).toLocaleString('he-IL', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function errorOf(e: unknown): { message: string; fields: Record<string, string>; retry: boolean } {
  if (e instanceof LessonApiError) {
    const fields = (e.detail.fields && typeof e.detail.fields === 'object' ? e.detail.fields : {}) as Record<string, string>;
    return { message: e.message, fields, retry: e.code === 'network' };
  }
  return { message: e instanceof Error ? e.message : String(e), fields: {}, retry: false };
}

/** One request id per submission, reused when the same submission is retried.
 * Kept by the player under `key` (not in this component), so a retry after
 * leaving the step and coming back still reuses it: an answer whose reply got
 * lost is never recorded twice. */
export function useRequestId(api: Pick<LessonApi, 'pending'>, key: string) {
  return {
    take(sig: string) {
      const entry = api.pending(key);
      if (!entry.request || entry.request.sig !== sig) entry.request = { id: newUuid(), sig };
      return entry.request.id;
    },
    done() {
      delete api.pending(key).request;
    }
  };
}

export function QuestionCard({ question, api }: { question: Question; api: LessonApi }) {
  const state = api.questions[question.key] ?? EMPTY_STATE;
  const check = question.mode === 'check';
  return (
    <article
      aria-labelledby={`q-${question.key}-prompt`}
      className={`grid grid-cols-1 gap-3 rounded-lg border p-4 ${check ? 'border-info-soft bg-card' : 'border-border bg-paper'}`}
    >
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <span className={`pill ${check ? 'pill-info' : 'pill-forest'} font-semibold`}>
          {check ? 'בדיקת הבנה אישית' : 'שאלת תרגול'}
        </span>
        {question.type === 'free_text' ? <span className="pill">תשובה פתוחה – לא נבדקת אוטומטית</span> : null}
        {state.attempts > 0 ? (
          <span className="text-ink-3">
            ניסיונות ששלחת: <Ltr>{state.attempts}</Ltr>
          </span>
        ) : null}
      </div>
      {check && state.attempts === 0 ? (
        <p className="text-[13px] leading-relaxed text-ink-2">
          ענו לבד, לפני שמתייעצים עם הצוות או עם הצ׳טבוט. המשוב יופיע אחרי השליחה. זה לא ציון.
        </p>
      ) : null}
      {question.type === 'single_choice' ? (
        <SingleChoice question={question} state={state} api={api} />
      ) : (
        <FreeText question={question} state={state} api={api} />
      )}
    </article>
  );
}

function Prompt({ question }: { question: Question }) {
  return (
    <>
      <span id={`q-${question.key}-prompt`} className="block text-[16px] font-semibold leading-relaxed">
        <InlineText text={question.prompt} />
      </span>
      {question.context ? (
        <span className="mt-1 block text-[14px] leading-relaxed text-ink-2">
          <InlineText text={question.context} />
        </span>
      ) : null}
    </>
  );
}

function DraftNote({ status }: { status: DraftStatus }) {
  if (status === 'saving') return <span className="text-ink-3">הטיוטה נשמרת…</span>;
  if (status === 'saved') return <span className="text-ok">✓ הטיוטה נשמרה (עדיין לא נשלחה כתשובה)</span>;
  if (status === 'error') return <span className="text-bad">⚠ הטיוטה לא נשמרה בשרת – היא שמורה במכשיר הזה</span>;
  return null;
}

function CheckModeNote({ question, state }: { question: SingleChoiceQuestion | FreeTextQuestion; state: QuestionState }) {
  if (question.mode !== 'check' || !state.first) return null;
  const first = state.first;
  const firstText =
    question.type === 'single_choice'
      ? question.options.find((o) => o.id === first.answer.choice)?.text ?? first.answer.choice ?? ''
      : first.answer.text ?? '';
  return (
    <div className="rounded-md border border-info-soft bg-info-soft/40 px-3 py-2 text-[13px] leading-relaxed">
      <p className="font-semibold">התשובה הראשונה שלך נשמרה; אפשר לתקן – כל תיקון נשמר כניסיון נוסף.</p>
      {state.attempts > 1 ? (
        <p className="mt-1 text-ink-2">
          התשובה הראשונה ({formatTime(first.submitted_at)}):{' '}
          {question.type === 'single_choice' ? <InlineText text={firstText} /> : <span dir="auto">״{firstText}״</span>}
          {first.correct === true ? ' – ✓ נכונה' : first.correct === false ? ' – ✗ לא נכונה' : ''}
        </p>
      ) : null}
    </div>
  );
}

/* ---------------- Single choice ---------------- */

function SingleChoice({ question, state, api }: { question: SingleChoiceQuestion; state: QuestionState; api: LessonApi }) {
  const key = question.key;
  const draftKey = `q:${key}`;
  const explain = question.explain ?? 'none';
  // An unsent pick survives a step change (the player keeps it, nothing is saved).
  const [choice, setChoice] = useState<string | null>(api.pending(draftKey).choice ?? state.latest?.answer.choice ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; retry: boolean } | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [confirmReveal, setConfirmReveal] = useState(false);
  const submission = useRequestId(api, draftKey);
  const revealId = useRequestId(api, `reveal:${key}`);
  const textId = useId();

  const text = explain === 'none' ? '' : api.draft(draftKey) ?? state.latest?.answer.text ?? '';
  const fb = state.feedback;
  const correctIds = new Set(fb?.correct_options ?? []);
  const latestChoice = state.latest?.answer.choice ?? null;
  const answer: Answer = { choice: choice ?? undefined };
  if (explain !== 'none' && text.trim()) answer.text = text.trim();
  const unchanged =
    !!state.latest && latestChoice === choice && (state.latest.answer.text ?? '') === (answer.text ?? '');
  const explanationShown = !!fb?.explanation;

  const submit = async () => {
    setError(null);
    setFieldErrors({});
    if (!choice) {
      setFieldErrors({ choice: 'בחרו אחת מהאפשרויות' });
      return;
    }
    if (explain === 'required' && text.trim().length < MIN_EXPLANATION) {
      setFieldErrors({ text: 'כתבו הסבר קצר במילים שלכם (10 תווים לפחות)' });
      return;
    }
    setBusy(true);
    try {
      const requestId = submission.take(JSON.stringify(answer));
      await api.submitAttempt({ request_id: requestId, question_key: key, answer });
      submission.done();
      delete api.pending(draftKey).choice;
      if (api.draft(draftKey) !== undefined) api.setDraft(draftKey, null);
      setConfirmReveal(false);
    } catch (e) {
      const err = errorOf(e);
      if (!err.retry) submission.done();
      setFieldErrors(err.fields);
      setError({ message: err.message, retry: err.retry });
    } finally {
      setBusy(false);
    }
  };

  const reveal = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.reveal(key, revealId.take('reveal'));
      revealId.done();
      setConfirmReveal(false);
    } catch (e) {
      const err = errorOf(e);
      if (!err.retry) revealId.done();
      setError({ message: err.message, retry: err.retry });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-3">
      <fieldset disabled={busy} aria-describedby={fieldErrors.choice ? `${textId}-choice` : undefined}>
        <legend className="mb-2">
          <Prompt question={question} />
        </legend>
        <div className="grid grid-cols-1 gap-2">
          {question.options.map((o) => {
            const selected = choice === o.id;
            const isCorrect = correctIds.has(o.id);
            const wasLatest = latestChoice === o.id;
            const wrongPick = selected && wasLatest && state.latest?.correct === false;
            return (
              <label
                key={o.id}
                className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 text-[15px] leading-relaxed ${
                  wrongPick ? 'border-bad bg-bad-soft/40' : selected ? 'border-forest bg-forest-tint' : 'border-border bg-card'
                }`}
              >
                <input
                  type="radio"
                  name={`q-${key}`}
                  value={o.id}
                  checked={selected}
                  onChange={() => {
                    setChoice(o.id);
                    api.pending(draftKey).choice = o.id;
                    setFieldErrors({});
                  }}
                  className="mt-1 h-4 w-4 shrink-0 accent-forest"
                />
                <span className="min-w-0 flex-1">
                  <InlineText text={o.text} />
                  {isCorrect || (wasLatest && state.latest?.correct != null) ? (
                    <span className="mt-1 flex flex-wrap gap-1.5 text-[12px]">
                      {isCorrect ? <span className="pill pill-ok">✓ התשובה הנכונה</span> : null}
                      {wasLatest && state.latest?.correct === false ? (
                        <span className="pill pill-bad">✗ הבחירה האחרונה שלך</span>
                      ) : wasLatest && state.latest?.correct === true ? (
                        <span className="pill pill-ok">הבחירה האחרונה שלך</span>
                      ) : null}
                    </span>
                  ) : null}
                </span>
              </label>
            );
          })}
        </div>
        {fieldErrors.choice ? (
          <p id={`${textId}-choice`} className="mt-1 text-[13px] text-bad">
            ⚠ {fieldErrors.choice}
          </p>
        ) : null}
      </fieldset>

      {explain !== 'none' ? (
        <div className="grid grid-cols-1 gap-1">
          <label htmlFor={textId} className="text-[14px] font-semibold">
            {question.explain_prompt ? <InlineText text={question.explain_prompt} /> : 'נימוק קצר במילים שלכם'}{' '}
            <span className="text-[12px] font-normal text-ink-3">
              {explain === 'required' ? `(חובה, לפחות ${MIN_EXPLANATION} תווים)` : '(רשות)'}
            </span>
          </label>
          <textarea
            id={textId}
            dir="auto"
            rows={3}
            maxLength={5000}
            value={text}
            disabled={busy}
            aria-invalid={!!fieldErrors.text}
            aria-describedby={`${textId}-status${fieldErrors.text ? ` ${textId}-error` : ''}`}
            onChange={(e) => {
              api.setDraft(draftKey, e.target.value);
              setFieldErrors((f) => ({ ...f, text: '' }));
            }}
            className="w-full rounded-md border border-border bg-white px-3 py-2 text-[15px] outline-none focus:border-forest focus:ring-2 focus:ring-forest-tint"
          />
          {fieldErrors.text ? (
            <p id={`${textId}-error`} className="text-[13px] text-bad">
              ⚠ {fieldErrors.text}
            </p>
          ) : null}
          <p id={`${textId}-status`} aria-live="polite" className="min-h-[1.25em] text-[12px]">
            {api.preview ? null : <DraftNote status={api.draftStatus(draftKey)} />}
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={submit}
          disabled={busy || !choice || unchanged}
          className="h-11 rounded-md bg-forest px-5 text-[15px] font-semibold text-paper disabled:opacity-50"
        >
          {busy ? 'שולח…' : state.attempts > 0 ? 'שליחה מחדש' : 'שליחת תשובה'}
        </button>
        {question.mode === 'practice' && !explanationShown ? (
          confirmReveal ? (
            <span className="flex flex-wrap items-center gap-2 text-[13px] text-ink-2">
              כדאי לנסות קודם לבד – גם תשובה שגויה עוזרת ללמוד.
              <button type="button" onClick={reveal} disabled={busy} className="text-forest underline">
                להציג בכל זאת
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => (state.attempts > 0 ? void reveal() : setConfirmReveal(true))}
              disabled={busy}
              className="h-11 rounded-md border border-border px-4 text-[14px] text-ink-2 hover:bg-paper-2"
            >
              הצג הסבר
            </button>
          )
        ) : null}
        {unchanged && !busy ? <span className="text-[12px] text-ink-3">שנו את התשובה כדי לשלוח שוב.</span> : null}
      </div>

      {error ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md bg-bad-soft px-3 py-2 text-[14px] text-bad">
          <span>⚠ לא נשלח: {error.message}</span>
          {error.retry ? (
            <button type="button" onClick={submit} disabled={busy} className="font-semibold underline">
              ניסיון חוזר
            </button>
          ) : null}
        </div>
      ) : null}

      <div aria-live="polite">
        {fb ? <ChoiceFeedback question={question} state={state} /> : null}
      </div>
      <CheckModeNote question={question} state={state} />
    </div>
  );
}

function ChoiceFeedback({ question, state }: { question: SingleChoiceQuestion; state: QuestionState }) {
  const fb = state.feedback!;
  const optionText = (id: string) => question.options.find((o) => o.id === id)?.text ?? id;
  const tone =
    fb.correct === true
      ? 'border-ok bg-ok-soft'
      : fb.correct === false
        ? 'border-warn bg-warn-soft/60'
        : 'border-info-soft bg-info-soft/40';
  const heading = fb.correct === true ? '✓ נכון' : fb.correct === false ? '✗ לא בדיוק' : 'ההסבר';
  return (
    <section className={`grid grid-cols-1 gap-2 rounded-md border-s-4 px-3 py-2.5 text-[15px] leading-relaxed ${tone}`}>
      <p className="font-semibold">
        {heading}
        {state.latest ? (
          <span className="ms-2 text-[12px] font-normal text-ink-3">
            ניסיון <Ltr>{state.latest.attempt_number}</Ltr> · {formatTime(state.latest.submitted_at)}
          </span>
        ) : null}
      </p>
      {fb.message ? (
        <p>
          <InlineText text={fb.message} />
        </p>
      ) : null}
      {fb.correct === false && !fb.explanation && question.mode === 'practice' ? (
        <p className="text-[13px] text-ink-2">אפשר לבחור תשובה אחרת ולשלוח שוב, או ללחוץ ״הצג הסבר״.</p>
      ) : null}
      {fb.correct_options?.length && fb.correct !== true ? (
        <p>
          <span className="font-semibold">התשובה הנכונה: </span>
          {fb.correct_options.map((id, i) => (
            <span key={id}>
              {i ? ' · ' : ''}
              <InlineText text={optionText(id)} />
            </span>
          ))}
        </p>
      ) : null}
      {fb.explanation ? (
        <p>
          <span className="font-semibold">הסבר: </span>
          <InlineText text={fb.explanation} />
        </p>
      ) : null}
      {state.revealed ? (
        <p className="text-[12px] text-ink-3">
          {state.attempts === 0 ? 'ההסבר הוצג לפני שעניתם.' : 'ביקשתם לראות את ההסבר.'} מה שחשוב הוא שתוכלו להסביר את זה במילים שלכם.
        </p>
      ) : null}
    </section>
  );
}

/* ---------------- Free text ---------------- */

function FreeText({ question, state, api }: { question: FreeTextQuestion; state: QuestionState; api: LessonApi }) {
  const key = question.key;
  const draftKey = `q:${key}`;
  const min = Math.max(1, question.min_chars ?? 1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; retry: boolean } | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const submission = useRequestId(api, draftKey);
  const id = useId();

  const text = api.draft(draftKey) ?? state.latest?.answer.text ?? '';
  const trimmed = text.trim();
  const unchanged = !!state.latest && (state.latest.answer.text ?? '') === trimmed;
  const fb = state.feedback;

  const submit = async () => {
    setError(null);
    setFieldError(null);
    if (trimmed.length < min) {
      setFieldError(min > 1 ? `כתבו לפחות ${min} תווים (כרגע ${trimmed.length})` : 'כתבו תשובה לפני השליחה');
      return;
    }
    setBusy(true);
    try {
      const requestId = submission.take(trimmed);
      await api.submitAttempt({ request_id: requestId, question_key: key, answer: { text: trimmed } });
      submission.done();
      if (api.draft(draftKey) !== undefined) api.setDraft(draftKey, null);
    } catch (e) {
      const err = errorOf(e);
      if (!err.retry) submission.done();
      setFieldError(err.fields.text ?? null);
      setError({ message: err.message, retry: err.retry });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-3">
      <label htmlFor={id} className="block">
        <Prompt question={question} />
      </label>
      <textarea
        id={id}
        dir="auto"
        rows={5}
        maxLength={5000}
        value={text}
        disabled={busy}
        placeholder={question.placeholder ?? ''}
        aria-invalid={!!fieldError}
        aria-describedby={`${id}-status${fieldError ? ` ${id}-error` : ''}`}
        onChange={(e) => {
          api.setDraft(draftKey, e.target.value);
          setFieldError(null);
        }}
        className="w-full rounded-md border border-border bg-white px-3 py-2 text-[15px] leading-relaxed outline-none focus:border-forest focus:ring-2 focus:ring-forest-tint"
      />
      <div className="flex flex-wrap items-center justify-between gap-2 text-[12px]">
        <span id={`${id}-status`} aria-live="polite">
          {api.preview ? null : <DraftNote status={api.draftStatus(draftKey)} />}
        </span>
        <span className={trimmed.length < min ? 'text-ink-3' : 'text-ok'}>
          <Ltr>{trimmed.length}</Ltr> תווים{min > 1 ? <> (לפחות <Ltr>{min}</Ltr>)</> : null}
        </span>
      </div>
      {fieldError ? (
        <p id={`${id}-error`} className="text-[13px] text-bad">
          ⚠ {fieldError}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={submit}
          disabled={busy || !trimmed || unchanged}
          className="h-11 rounded-md bg-forest px-5 text-[15px] font-semibold text-paper disabled:opacity-50"
        >
          {busy ? 'שולח…' : state.attempts > 0 ? 'שליחת הגרסה המתוקנת' : 'שליחת תשובה'}
        </button>
        {state.latest ? (
          <span className="text-[12px] text-ink-3">
            {unchanged ? '✓ זו התשובה ששלחת' : 'יש שינויים שעוד לא נשלחו'} · נשלחה לאחרונה {formatTime(state.latest.submitted_at)}
          </span>
        ) : null}
      </div>
      {error ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md bg-bad-soft px-3 py-2 text-[14px] text-bad">
          <span>⚠ לא נשלח: {error.message}</span>
          {error.retry ? (
            <button type="button" onClick={submit} disabled={busy} className="font-semibold underline">
              ניסיון חוזר
            </button>
          ) : null}
        </div>
      ) : null}
      <div aria-live="polite">
        {fb && state.attempts > 0 ? (
          <section className="grid grid-cols-1 gap-2 rounded-md border-s-4 border-info-soft bg-info-soft/40 px-3 py-2.5 text-[15px] leading-relaxed">
            <p className="font-semibold">
              ✓ התשובה נשלחה ונשמרה. היא לא נבדקת אוטומטית ולא מקבלת ציון.
            </p>
            {fb.sample_reasoning?.length ? (
              <div>
                <p className="font-semibold">דוגמה לנימוק — לא ציון</p>
                <p className="mt-1">
                  <InlineText text={fb.sample_reasoning[0]} />
                </p>
                {fb.sample_reasoning.length > 1 ? (
                  <details className="mt-2 rounded-md border border-line-soft bg-card/60">
                    <summary className="cursor-pointer px-3 py-2.5 text-[14px] font-semibold text-forest">
                      עוד דוגמאות (<Ltr>{fb.sample_reasoning.length - 1}</Ltr>)
                    </summary>
                    <ul className="grid grid-cols-1 list-disc gap-1 px-3 pb-2.5 ps-8">
                      {fb.sample_reasoning.slice(1).map((s, i) => (
                        <li key={i}>
                          <InlineText text={s} />
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            ) : null}
            {fb.rubric?.length ? (
              <div>
                <p className="font-semibold">מה כדאי שיופיע בתשובה טובה</p>
                <ul className="mt-1 grid grid-cols-1 list-disc gap-1 ps-6">
                  {fb.rubric.map((s, i) => (
                    <li key={i}>
                      <InlineText text={s} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className="text-[13px] text-ink-2">השוו לתשובה שלכם. רוצים לתקן? ערכו את הטקסט ושלחו שוב – כל שליחה נשמרת כניסיון נוסף.</p>
          </section>
        ) : null}
      </div>
      <CheckModeNote question={question} state={state} />
    </div>
  );
}
