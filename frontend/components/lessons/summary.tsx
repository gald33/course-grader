'use client';

/* The student's own summary: which steps are done and which remain, their
 * experiment records and choice, and questions worth another look (a wrong
 * first answer, or a revealed explanation). Completion is evidence of actions,
 * not a grade or a claim of mastery — the summary says so. */

import { depthLabel, pctText } from '@/components/lessons/experiments';
import { InlineText, Ltr, plainInline } from '@/components/lessons/inline';
import type { LessonApi } from '@/components/lessons/lesson-player';
import type { LessonStep, Question } from '@/components/lessons/types';

function shorten(text: string, max = 110) {
  const t = text.replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

export function LessonSummary({ api }: { api: LessonApi }) {
  const steps = api.content.steps;
  const required = steps.filter((s) => !s.optional);
  const optional = steps.filter((s) => s.optional);
  const done = required.filter((s) => api.steps[s.key]?.completed);
  const remaining = required.filter((s) => !api.steps[s.key]?.completed);
  const stepIndex = new Map(steps.map((s, i) => [s.key, i]));
  const questions = Object.values(api.content.questions).sort(
    (a, b) => (stepIndex.get(a.step) ?? 99) - (stepIndex.get(b.step) ?? 99)
  );
  const revisit = questions
    .map((q) => ({ q, state: api.questions[q.key] }))
    .filter(({ state }) => state && (state.first?.correct === false || state.revealed));
  const latest = api.commitments.length ? api.commitments[api.commitments.length - 1] : null;
  const stepOf = (q: Question) => steps.find((s) => s.key === q.step);

  return (
    <div className="grid grid-cols-1 gap-4 text-[14px]">
      <p className="rounded-md border border-border bg-paper px-3 py-2 font-semibold">
        השלמה אינה ציון ואינה הוכחת שליטה. היא מראה אילו פעולות עשית; ההבנה נבדקת במה שאפשר להסביר לבד.
      </p>

      <div>
        <h4 className="font-hebrew text-[16px]">
          שלבי החובה: {done.length} מתוך {required.length} הושלמו
        </h4>
        {api.completedAt ? <p className="mt-1 text-ok">✓ כל שלבי החובה הושלמו.</p> : null}
        <ul className="mt-2 grid grid-cols-1 gap-1.5">
          {required.map((s) => (
            <StepRow key={s.key} step={s} done={!!api.steps[s.key]?.completed} api={api} />
          ))}
        </ul>
        {remaining.length ? (
          <p className="mt-2 text-ink-2">
            נשארו:{' '}
            {/* Each letter isolated, so the list reads right to left like the sentence. */}
            {remaining.map((s, i) => (
              <span key={s.key}>
                {i ? ', ' : ''}
                <Ltr>{s.letter}</Ltr>
              </span>
            ))}
            . אפשר לחזור לכל שלב דרך מפת השיעור.
          </p>
        ) : null}
        {optional.length ? (
          <>
            <h5 className="mt-3 font-semibold">הרחבה לבחירה (לא נספרת)</h5>
            <ul className="mt-1 grid grid-cols-1 gap-1.5">
              {optional.map((s) => (
                <StepRow key={s.key} step={s} done={!!api.steps[s.key]?.completed} api={api} />
              ))}
            </ul>
          </>
        ) : null}
      </div>

      <div>
        <h4 className="font-hebrew text-[16px]">הניסויים שלי</h4>
        {api.experiments.length ? (
          <div className="mt-2 overflow-x-auto rounded-md border border-border" role="region" tabIndex={0} aria-label="הניסויים שלי">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="bg-paper-2">
                  <th scope="col" className="px-2 py-1.5 text-start font-semibold">
                    ריצה
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-semibold">
                    עומק
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-semibold">
                    דוגמאות
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-semibold">
                    אימון
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-semibold">
                    אימות
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-semibold">
                    קו בסיס
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-start font-semibold">
                    מלאה?
                  </th>
                </tr>
              </thead>
              <tbody>
                {api.experiments.map((e, i) => (
                  <tr key={e.run_uuid} className="border-t border-line-soft">
                    <td className="px-2 py-1.5">{i + 1}</td>
                    <td className="whitespace-nowrap px-2 py-1.5">{depthLabel(e.depth_kind, e.depth)}</td>
                    <td className="px-2 py-1.5">
                      <Ltr>{e.training_examples ?? '—'}</Ltr>
                    </td>
                    <td className="px-2 py-1.5">
                      <Ltr>{pctText(e.train_accuracy)}</Ltr>
                    </td>
                    <td className="px-2 py-1.5">
                      <Ltr>{pctText(e.validation_accuracy)}</Ltr>
                    </td>
                    <td className="px-2 py-1.5">
                      <Ltr>{pctText(e.baseline_validation)}</Ltr>
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5">{e.complete ? '✓ כן' : 'חלקית'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-1 text-ink-2">עוד לא שמרת ניסויים ביומן (שלב E).</p>
        )}
        <p className="mt-1 text-[12px] text-ink-3">נתונים שהוזנו ידנית — לא נבדקו מול קולאב.</p>
      </div>

      <div>
        <h4 className="font-hebrew text-[16px]">הבחירה שלי</h4>
        {latest ? (
          <div className="mt-1 grid grid-cols-1 gap-1">
            <p>
              עומק {depthLabel(latest.depth_kind, latest.depth)}, <Ltr>{latest.training_examples}</Ltr> דוגמאות אימון
              {latest.final ? (
                <>
                  {' '}
                  · מבחן סופי: דיוק <Ltr>{pctText(latest.final.accuracy)}</Ltr>
                </>
              ) : (
                ' · תוצאת המבחן הסופי עוד לא נרשמה'
              )}
            </p>
            {api.commitments.length > 1 ? <p className="text-ink-2">שמרת {api.commitments.length} בחירות; כולן נשמרות.</p> : null}
            {api.commitments.some((c) => c.after_final_seen) ? (
              <p className="text-[13px] font-semibold">
                <span aria-hidden>⚠ </span>אחת הבחירות נעשתה אחרי שנחשפת לתוצאת המבחן — המבחן כבר אינו בדיקה עצמאית שלה.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="mt-1 text-ink-2">עוד לא שמרת בחירה לפני המבחן הסופי (שלב F).</p>
        )}
      </div>

      <div>
        <h4 className="font-hebrew text-[16px]">נקודות שכדאי לחזור אליהן</h4>
        {revisit.length ? (
          <ul className="mt-2 grid grid-cols-1 gap-2">
            {revisit.map(({ q, state }) => {
              const step = stepOf(q);
              return (
                <li key={q.key} className="rounded-md border border-border bg-paper px-3 py-2">
                  <p className="font-semibold">{shorten(plainInline(q.prompt))}</p>
                  <p className="mt-0.5 text-[12px] text-ink-2">
                    {state?.first?.correct === false ? 'התשובה הראשונה לא הייתה נכונה' : null}
                    {state?.first?.correct === false && state?.revealed ? ' · ' : null}
                    {state?.revealed ? 'ביקשת לראות הסבר' : null}
                    {state?.latest?.correct === true ? ' · בניסיון האחרון ענית נכון' : null}
                  </p>
                  {step ? (
                    <button type="button" onClick={() => api.goToStep(step.key)} className="mt-1 text-[13px] text-forest underline">
                      לשלב <Ltr>{step.letter}</Ltr>: {plainInline(step.title)}
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-1 text-ink-2">אין כרגע שאלות שסומנו לחזרה. נסו להסביר לחבר/ה בצוות את עיקרי השיעור בלי להציץ.</p>
        )}
      </div>
    </div>
  );
}

function StepRow({ step, done, api }: { step: LessonStep; done: boolean; api: LessonApi }) {
  return (
    <li className="flex items-center gap-2">
      <span aria-hidden className={done ? 'text-ok' : 'text-ink-4'}>
        {done ? '✓' : '○'}
      </span>
      <button type="button" onClick={() => api.goToStep(step.key)} className="min-w-0 flex-1 text-right hover:underline">
        <Ltr className="font-semibold">{step.letter}</Ltr> · <InlineText text={step.title} />
      </button>
      <span className={`shrink-0 text-[12px] ${done ? 'text-ok' : 'text-ink-3'}`}>{done ? 'הושלם' : 'עוד לא'}</span>
    </li>
  );
}
