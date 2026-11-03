'use client';

import { useEffect, useRef, useState } from 'react';

import { Ltr } from '@/components/lessons/inline';

/* The "lesson complete" moment: a short dialog shown the first time a student
 * finishes every required step of a lesson during a visit (completed_at goes
 * from unset to set) — never on opening an already-completed lesson. Purely
 * visual: it adds no points or grade and doesn't change what "completed" means.
 * A CSS-only confetti burst (≤ 2 s, no sound, no library), replaced by a static
 * badge under prefers-reduced-motion. Focus moves into the dialog and stays
 * there; Esc or × closes it and leaves the student on the lesson. */

/** Where the player's return links lead, and what comes next. */
export type LessonNav = {
  lessons: string; // the list of lessons
  home: string; // the course's main page
  next: { href: string; title: string } | null; // the next lesson, when there is one
  number: number | null; // the lesson's number in the course, when known
};

export type CelebrationSummary = {
  stepsDone: number;
  stepsTotal: number;
  answered: number;
  questionsTotal: number;
};

/** The lesson's number: lesson-06 → 6, otherwise its place in the course's list (1-based). */
export function lessonNumber(slug: string, orderedSlugs: string[]): number | null {
  const m = /^lesson-0*(\d+)(?:$|-)/.exec(slug);
  if (m) return Number(m[1]);
  const i = orderedSlugs.indexOf(slug);
  return i >= 0 ? i + 1 : null;
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  );
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setReduced(mq.matches);
    on();
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return reduced;
}

// Confetti pieces: fixed, so every burst looks the same (and renders the same on the server).
const COLORS = ['var(--forest)', 'var(--terracotta)', '#fcd34d', 'var(--info)', '#fda4af', 'var(--ok)'];
const PIECES = Array.from({ length: 28 }, (_, i) => {
  const angle = (i / 28) * Math.PI * 2;
  const dist = 90 + ((i * 37) % 70);
  return {
    x: Math.round(Math.cos(angle) * dist),
    y: Math.round(Math.sin(angle) * dist * 0.75 - 30),
    r: (i * 53) % 360,
    delay: (i % 5) * 40,
    color: COLORS[i % COLORS.length],
    round: i % 3 === 0
  };
});

export function LessonCelebration({
  title,
  nav,
  summary,
  preview,
  onClose
}: {
  title: string;
  nav: LessonNav;
  summary: CelebrationSummary;
  preview: boolean;
  onClose: () => void;
}) {
  const reduced = usePrefersReducedMotion();
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstRef = useRef<HTMLAnchorElement>(null);

  // Focus in on open, back where it was on close.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    firstRef.current?.focus();
    return () => {
      if (before && document.contains(before)) before.focus({ preventScroll: true });
    };
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key !== 'Tab') return;
    const items = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])') ?? []
    );
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !dialogRef.current?.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !dialogRef.current?.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  };

  const heading = `כל הכבוד! סיימתם את ${nav.number != null ? `שיעור ${nav.number}` : 'השיעור'} – ${title}`;
  const primary =
    'inline-flex min-h-[48px] w-full items-center justify-center rounded-md bg-forest px-4 text-[15px] font-semibold text-paper';
  const secondary =
    'inline-flex min-h-[48px] w-full items-center justify-center rounded-md border border-forest px-4 text-[15px] font-semibold text-forest';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="lesson-celebration-title"
        aria-describedby="lesson-celebration-summary"
        dir="rtl"
        lang="he"
        onKeyDown={onKeyDown}
        className="relative w-full max-w-[420px] rounded-xl border border-forest-soft bg-card p-5 pt-6 text-center shadow-card"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="סגירה וחזרה לשיעור"
          className="absolute end-2 top-2 grid h-10 w-10 place-items-center rounded-md text-[22px] leading-none text-ink-2 hover:text-ink"
        >
          ×
        </button>

        <div className="relative mx-auto grid h-24 w-24 place-items-center" aria-hidden>
          {reduced ? null : (
            <div data-testid="celebration-confetti" className="cg-confetti pointer-events-none absolute inset-0">
              {PIECES.map((p, i) => (
                <span
                  key={i}
                  style={
                    {
                      '--x': `${p.x}px`,
                      '--y': `${p.y}px`,
                      '--r': `${p.r}deg`,
                      animationDelay: `${p.delay}ms`,
                      background: p.color,
                      borderRadius: p.round ? '9999px' : '2px'
                    } as React.CSSProperties
                  }
                />
              ))}
            </div>
          )}
          <div
            data-testid="celebration-badge"
            className={`grid h-20 w-20 place-items-center rounded-full border-4 border-forest bg-forest-tint ${reduced ? '' : 'cg-badge-pop'}`}
          >
            <span className="block text-[13px] font-semibold leading-none text-forest">✓</span>
            {nav.number != null ? (
              <span className="-mt-2 block font-sans text-[26px] font-semibold leading-none text-ink">
                <Ltr>{nav.number}</Ltr>
              </span>
            ) : null}
          </div>
        </div>

        <h2 id="lesson-celebration-title" className="mt-3 font-hebrew text-[21px] leading-snug">
          {heading}
        </h2>
        <p id="lesson-celebration-summary" className="mt-2 text-[14px] leading-relaxed text-ink-2">
          השלמתם <Ltr>{summary.stepsDone}</Ltr> מתוך <Ltr>{summary.stepsTotal}</Ltr> שלבי חובה
          {summary.questionsTotal > 0 ? (
            <>
              {' '}
              · עניתם על <Ltr>{summary.answered}</Ltr> מתוך <Ltr>{summary.questionsTotal}</Ltr> שאלות
            </>
          ) : null}
          .
        </p>
        {preview ? <p className="mt-1 text-[12px] text-ink-3">(תצוגה מקדימה – שום דבר לא נשמר)</p> : null}

        <div className="mt-4 grid gap-2">
          {nav.next ? (
            <a ref={firstRef} href={nav.next.href} className={primary}>
              <span className="min-w-0 truncate">לשיעור הבא: {nav.next.title}</span>
              <span aria-hidden className="ms-2">
                ←
              </span>
            </a>
          ) : null}
          <a ref={nav.next ? undefined : firstRef} href={nav.lessons} className={nav.next ? secondary : primary}>
            לרשימת השיעורים
          </a>
          <a href={nav.home} className={secondary}>
            לדף הבית של הקורס
          </a>
        </div>
      </div>
    </div>
  );
}
