'use client';

import { MessageSquarePlus, X } from 'lucide-react';
import { usePathname } from 'next/navigation';
import { FormEvent, useCallback, useEffect, useId, useRef, useState } from 'react';

import { apiFetch } from '@/lib/api';

/* The Feedback button, on every page: a student's own pages (Hebrew, RTL,
 * under their course link /r/<token>) and every instructor page. It files a
 * ticket in the app's tickets-core store (backend app/services/feedback.py),
 * which org-core's roles triage.
 *
 * What the page attaches is gathered when the dialog opens and shown in full
 * before Send: where in the site it was sent from (the route with the link
 * token cut out, the lesson, step, assignment, section and tab) and what it
 * ran on (screen, browser, language, time zone, build). Nothing else is read;
 * in particular no heading text, which on a student's home page is their
 * name. A student can send without their name. */

type Category = 'broken' | 'confusing' | 'idea';
type Mode = { kind: 'student'; token: string } | { kind: 'instructor'; courseId: number | null };
type Facts = Record<string, string>;

const STUDENT_PATH = /^\/r\/([A-Za-z0-9_-]{16,})(\/.*)?$/;
// Pages that put their own Feedback control in their toolbar, where a floating one would sit over dense
// controls (the submission page's rubric dots). The dialog is the same; it opens on OPEN_FEEDBACK_EVENT.
const OWN_TRIGGER = /^\/course\/\d+\/submission\//;
export const OPEN_FEEDBACK_EVENT = 'cg:open-feedback';

/** Open the Feedback dialog from a page's own control. */
export function openFeedback() {
  window.dispatchEvent(new Event(OPEN_FEEDBACK_EVENT));
}
// Pages with no way to file: a student's sign-in pages carry no course link yet.
const NO_BUTTON = /^\/(login|auth)(\/|$)/;

const TEXT = {
  he: {
    button: 'משוב',
    title: 'משוב על האתר',
    intro: 'מה כדאי שנדע? כל משוב נקרא.',
    categories: {
      broken: 'משהו לא עובד',
      confusing: 'משהו מבלבל',
      idea: 'יש לי רעיון'
    } as Record<Category, string>,
    label: 'ספרו לנו במה מדובר',
    placeholder: 'מה ניסיתם לעשות, ומה קרה?',
    anonymous: 'לשלוח בלי השם שלי',
    anonymousHint: 'יצורפו רק העמוד, השיעור והתאריך — בלי השם שלכם, בלי השעה, בלי השלב ובלי פרטי המכשיר.',
    attached: 'מה מצורף אוטומטית',
    name: 'השם שלך',
    nameYes: 'מצורף',
    nameNo: 'לא מצורף',
    when: 'מתי',
    whenFull: 'התאריך והשעה',
    whenDay: 'התאריך בלבד',
    send: 'שליחה',
    sending: 'שולח…',
    cancel: 'ביטול',
    close: 'סגירה',
    sent: 'תודה! המשוב נשלח.',
    sentNext: 'אפשר לשלוח עוד משוב בכל עת מהכפתור הזה.',
    tooShort: 'כתבו כמה מילים',
    failed: 'השליחה נכשלה. נסו שוב בעוד רגע.',
    facts: {
      page: 'עמוד',
      lesson: 'שיעור',
      step: 'שלב',
      assignment: 'מטלה',
      tab: 'לשונית',
      section: 'אזור',
      viewport: 'גודל מסך',
      browser: 'דפדפן',
      language: 'שפה',
      timezone: 'אזור זמן',
      build: 'גרסה'
    } as Record<string, string>
  },
  en: {
    button: 'Feedback',
    title: 'Feedback about the site',
    intro: 'Tell us what went wrong or what could be better.',
    categories: {
      broken: "Something's broken",
      confusing: 'This is confusing',
      idea: 'I have an idea'
    } as Record<Category, string>,
    label: 'What happened, or what should change?',
    placeholder: 'What were you trying to do, and what happened?',
    anonymous: '',
    anonymousHint: '',
    attached: 'Attached automatically',
    name: 'Your name',
    nameYes: 'attached',
    nameNo: 'not attached',
    when: 'When',
    whenFull: 'the date and time',
    whenDay: 'the date only',
    send: 'Send',
    sending: 'Sending…',
    cancel: 'Cancel',
    close: 'Close',
    sent: "Thanks — it's in the ticket queue.",
    sentNext: 'You can send more any time from this button.',
    tooShort: 'Write a few words',
    failed: "Couldn't send it. Try again in a moment.",
    facts: {
      page: 'Page',
      lesson: 'Lesson',
      step: 'Step',
      assignment: 'Assignment',
      tab: 'Tab',
      section: 'Section',
      viewport: 'Screen',
      browser: 'Browser',
      language: 'Language',
      timezone: 'Time zone',
      build: 'Build'
    } as Record<string, string>
  }
};

export function modeFor(pathname: string): Mode | null {
  if (NO_BUTTON.test(pathname)) return null;
  const student = STUDENT_PATH.exec(pathname);
  if (student) return { kind: 'student', token: student[1] };
  if (pathname.startsWith('/r/')) return null;
  const course = /^\/course\/(\d+)(\/|$)/.exec(pathname);
  return { kind: 'instructor', courseId: course ? Number(course[1]) : null };
}

/** The route with the student's link token cut out: the token is their credential. */
export function safePath(pathname: string, search: string, hash: string): string {
  const path = pathname.replace(STUDENT_PATH, (_m, _t, rest) => `/r/…${rest ?? ''}`);
  return `${path}${search}${hash}`.slice(0, 400);
}

// What an anonymous report keeps (the backend enforces the same, app/services/feedback.py ANONYMOUS_FACTS): where in
// the site, never the step, and nothing about the device. The operator's ruling on Reed's N2 (#52): "Coarsen it".
const ANONYMOUS_FACTS = ['path', 'section', 'tab', 'lesson', 'assignment'];

export function anonymousFacts(facts: Facts): Facts {
  const kept: Facts = {};
  for (const k of ANONYMOUS_FACTS) if (facts[k]) kept[k] = facts[k];
  if (kept.path) {
    const [base, query] = kept.path.split('#')[0].split('?');
    const params = (query ?? '').split('&').filter((p) => p && !p.startsWith('step='));
    kept.path = params.length ? `${base}?${params.join('&')}` : base;
  }
  return kept;
}

function gatherFacts(mode: Mode): Facts {
  const { pathname, search, hash } = window.location;
  const params = new URLSearchParams(search);
  const facts: Facts = { path: safePath(pathname, search, hash) };
  const lesson = /^\/r\/[^/]+\/lessons\/([^/]+)/.exec(pathname)?.[1] ?? /^\/course\/\d+\/lessons\/([^/]+)/.exec(pathname)?.[1];
  if (lesson) facts.lesson = decodeURIComponent(lesson);
  const step = /(?:^#|&)step=([^&]+)/.exec(hash)?.[1];
  if (step) facts.step = decodeURIComponent(step);
  const assignment = /\/assignments\/([^/]+)/.exec(pathname)?.[1];
  if (assignment) facts.assignment = decodeURIComponent(assignment);
  if (mode.kind === 'instructor' && params.get('section')) facts.section = params.get('section')!;
  if (params.get('tab')) facts.tab = params.get('tab')!;
  facts.viewport = `${window.innerWidth}x${window.innerHeight}`;
  facts.browser = navigator.userAgent;
  facts.language = navigator.language;
  try {
    facts.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    /* no Intl time zone */
  }
  const build = process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA;
  if (build) facts.build = build.slice(0, 12);
  return facts;
}

export function FeedbackButton() {
  const pathname = usePathname() ?? '/';
  const mode = modeFor(pathname);
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onOpen = () => {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setOpen(true);
    };
    window.addEventListener(OPEN_FEEDBACK_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_FEEDBACK_EVENT, onOpen);
  }, []);

  if (!mode) return null;
  const lang = mode.kind === 'student' ? 'he' : 'en';
  const t = TEXT[lang];
  // A student's pages are RTL with nothing in the bottom-left corner; the instructor pages keep their
  // sidebar's last links there, so on theirs the button sits bottom-right.
  const corner = mode.kind === 'student' ? 'bottom-4 left-4' : 'bottom-4 right-4';
  const floating = !OWN_TRIGGER.test(pathname);

  return (
    <>
      {floating ? (
        <button
          ref={buttonRef}
          type="button"
          onClick={() => setOpen(true)}
          dir={lang === 'he' ? 'rtl' : 'ltr'}
          lang={lang}
          aria-haspopup="dialog"
          className={`fixed ${corner} z-30 inline-flex h-10 items-center gap-1.5 rounded-full border border-border bg-card px-3.5 text-[13px] font-medium text-ink-2 shadow-lift transition hover:border-ink-4 hover:text-ink print:hidden`}
        >
          <MessageSquarePlus className="h-4 w-4" aria-hidden />
          <span className={lang === 'he' ? 'font-hebrew' : ''}>{t.button}</span>
        </button>
      ) : null}
      {open ? (
        <FeedbackDialog
          mode={mode}
          lang={lang}
          onClose={() => {
            setOpen(false);
            (returnFocus.current ?? buttonRef.current)?.focus();
            returnFocus.current = null;
          }}
        />
      ) : null}
    </>
  );
}

function FeedbackDialog({ mode, lang, onClose }: { mode: Mode; lang: 'he' | 'en'; onClose: () => void }) {
  const t = TEXT[lang];
  const titleId = useId();
  const [facts] = useState<Facts>(() => gatherFacts(mode));
  const [category, setCategory] = useState<Category>('broken');
  const [text, setText] = useState('');
  const [anonymous, setAnonymous] = useState(false);
  const [state, setState] = useState<'idle' | 'sending' | 'sent'>('idle');
  const [error, setError] = useState<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    textRef.current?.focus();
  }, []);

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key !== 'Tab' || !dialogRef.current) return;
      // Keep focus inside the dialog.
      const items = dialogRef.current.querySelectorAll<HTMLElement>('button, textarea, input, summary, [href]');
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [onClose]
  );
  useEffect(() => {
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onKey]);

  // Exactly what this send attaches, and what the list below shows: everything for a named report, the coarse set
  // for an anonymous one.
  const coarse = mode.kind === 'student' && anonymous;
  const sent = coarse ? anonymousFacts(facts) : facts;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (text.trim().length < 3) {
      setError(t.tooShort);
      textRef.current?.focus();
      return;
    }
    setState('sending');
    setError(null);
    const body = { category, text: text.trim(), context: sent };
    try {
      const res =
        mode.kind === 'student'
          ? await apiFetch(`/api/r/${mode.token}/feedback`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CG-Student': '1'
              },
              body: JSON.stringify({ ...body, anonymous })
            })
          : await apiFetch('/api/feedback', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ...body, course_id: mode.courseId })
            });
      if (!res.ok) throw new Error(String(res.status));
      setState('sent');
    } catch {
      setState('idle');
      setError(t.failed);
    }
  }

  const shown: [string, string][] = Object.entries(sent).map(([k, v]) => [t.facts[k === 'path' ? 'page' : k] ?? k, v]);
  shown.unshift([t.when, coarse ? t.whenDay : t.whenFull]);
  if (mode.kind === 'student') shown.unshift([t.name, anonymous ? t.nameNo : t.nameYes]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end justify-center bg-black/60 p-3 sm:items-center print:hidden"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        dir={lang === 'he' ? 'rtl' : 'ltr'}
        lang={lang}
        onClick={(e) => e.stopPropagation()}
        className={`max-h-[calc(100vh-1.5rem)] w-full max-w-[460px] overflow-y-auto rounded-xl border border-border bg-card p-5 shadow-lift ${lang === 'he' ? 'font-hebrew' : ''}`}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id={titleId} className="text-[18px] font-semibold leading-tight text-ink">
              {t.title}
            </h2>
            {state !== 'sent' ? <p className="mt-1 text-[13px] text-ink-3">{t.intro}</p> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.close}
            className="-m-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-ink-3 hover:bg-paper-2 hover:text-ink"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        {state === 'sent' ? (
          <div className="mt-4" role="status">
            <p className="text-[15px] font-medium text-forest">{t.sent}</p>
            <p className="mt-1 text-[13px] text-ink-3">{t.sentNext}</p>
            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="h-9 rounded-[8px] bg-forest px-4 text-[13px] font-semibold text-paper hover:bg-forest/90"
              >
                {t.close}
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-4 space-y-4">
            <fieldset>
              <legend className="sr-only">{t.title}</legend>
              <div className="flex flex-wrap gap-2">
                {(Object.keys(t.categories) as Category[]).map((c) => (
                  <button
                    key={c}
                    type="button"
                    aria-pressed={category === c}
                    onClick={() => setCategory(c)}
                    className={`h-9 rounded-full border px-3.5 text-[13px] transition ${
                      category === c
                        ? 'border-forest bg-forest-tint font-semibold text-forest'
                        : 'border-border bg-card text-ink-2 hover:border-ink-4'
                    }`}
                  >
                    {t.categories[c]}
                  </button>
                ))}
              </div>
            </fieldset>

            <label className="block">
              <span className="text-[13px] font-medium text-ink-2">{t.label}</span>
              <textarea
                ref={textRef}
                dir="auto"
                rows={4}
                maxLength={4000}
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  if (error) setError(null);
                }}
                placeholder={t.placeholder}
                className="mt-1.5 w-full rounded-md border border-border bg-card px-3 py-2 text-[14px] text-ink focus:border-forest focus:outline-none"
              />
            </label>

            {mode.kind === 'student' ? (
              <div>
                <label className="flex items-center gap-2 text-[13px] text-ink-2">
                  <input
                    type="checkbox"
                    checked={anonymous}
                    onChange={(e) => setAnonymous(e.target.checked)}
                    className="h-4 w-4 accent-forest"
                  />
                  {t.anonymous}
                </label>
                {anonymous ? <p className="mt-1 text-[12px] text-ink-3">{t.anonymousHint}</p> : null}
              </div>
            ) : null}

            <details className="rounded-md border border-line-soft bg-paper-2/50 px-3 py-2 text-[12px] text-ink-3">
              <summary className="cursor-pointer select-none text-ink-2">{t.attached}</summary>
              <dl className="mt-2 space-y-1" aria-label={t.attached}>
                {shown.map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <dt className="shrink-0 text-ink-2">{k}:</dt>
                    <dd dir="ltr" className="min-w-0 break-all text-start">
                      {v}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>

            {error ? (
              <p role="alert" className="text-[13px] text-bad">
                {error}
              </p>
            ) : null}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="h-9 rounded-[8px] px-3.5 text-[13px] text-ink-2 hover:bg-paper-2 hover:text-ink"
              >
                {t.cancel}
              </button>
              <button
                type="submit"
                disabled={state === 'sending'}
                className="h-9 rounded-[8px] bg-forest px-4 text-[13px] font-semibold text-paper hover:bg-forest/90 disabled:opacity-50"
              >
                {state === 'sending' ? t.sending : t.send}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
