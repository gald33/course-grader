'use client';

import { useCallback, useEffect, useState } from 'react';

import { InlineText, Ltr } from '@/components/lessons/inline';
import { listStudentLessons, type StudentLessonSummary } from '@/components/lessons/student-backend';
import { LessonApiError } from '@/components/lessons/types';

/* The student's published lessons for this course, addressed by the
 * student's personal link. Hebrew, RTL, phone-first. */

const STATUS: Record<StudentLessonSummary['status'], string> = {
  not_started: 'עוד לא התחלת',
  in_progress: 'בתהליך',
  completed: '✓ כל שלבי החובה הושלמו'
};

export default function StudentLessonsPage({ params }: { params: { token: string } }) {
  const { token } = params;
  const [lessons, setLessons] = useState<StudentLessonSummary[] | null>(null);
  const [error, setError] = useState<LessonApiError | null>(null);

  const load = useCallback(() => {
    setError(null);
    listStudentLessons(token)
      .then(setLessons)
      .catch((e) => setError(e instanceof LessonApiError ? e : new LessonApiError('error', String(e), 0)));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div dir="rtl" lang="he" className="min-h-screen">
      <main className="mx-auto w-full max-w-[640px] px-4 pb-24 pt-4">
        <a href={`/r/${token}`} className="text-[14px] text-forest hover:underline">
          → לעמוד הקורס
        </a>
        <h1 className="mt-2 font-hebrew text-[26px] leading-tight">למידה בשיעור</h1>
        <p className="mt-1 text-[14px] text-ink-2">
          שיעורים מודרכים: הסבר קצר, פעולה, ובדיקה קטנה בכל שלב. ההתקדמות נשמרת, ואפשר לחזור לכל שלב.
        </p>

        {error ? (
          <div className="mt-4 rounded-lg border border-bad-soft bg-card p-5 text-[15px]">
            <p role="alert">{error.message}</p>
            {error.code === 'not_signed_in' ? (
              <a
                href={`/login?next=${encodeURIComponent(`/r/${token}/lessons`)}`}
                className="mt-3 inline-flex h-11 items-center rounded-md bg-forest px-5 text-[15px] font-semibold text-paper"
              >
                כניסה לחשבון
              </a>
            ) : error.code === 'network' || error.code === 'error' ? (
              <button type="button" onClick={load} className="mt-3 text-[14px] text-forest underline">
                נסו שוב
              </button>
            ) : null}
          </div>
        ) : !lessons ? (
          <div className="py-16 text-center text-ink-3">טוען…</div>
        ) : lessons.length === 0 ? (
          <div className="mt-4 rounded-lg border border-border bg-card p-5 text-[15px] text-ink-2">
            אין כרגע שיעורים פתוחים. כשהמרצה יפרסם שיעור, הוא יופיע כאן.
          </div>
        ) : (
          <ul className="mt-4 grid gap-3">
            {lessons.map((l) => (
              <li key={l.slug}>
                <a
                  href={`/r/${token}/lessons/${encodeURIComponent(l.slug)}`}
                  className="block rounded-lg border border-border bg-card p-4 text-ink no-underline shadow-soft hover:border-forest"
                >
                  <span className="block font-hebrew text-[19px] leading-snug">{l.title}</span>
                  <span className="mt-1 block text-[14px] text-ink-2">
                    <InlineText text={l.guiding_question} />
                  </span>
                  <span className="mt-2 flex flex-wrap items-center gap-2 text-[13px]">
                    <span className={`pill ${l.status === 'completed' ? 'pill-ok' : l.status === 'in_progress' ? 'pill-forest' : ''}`}>
                      {STATUS[l.status]}
                    </span>
                    <span className="text-ink-3">
                      <Ltr>{l.required_done}</Ltr> מתוך <Ltr>{l.required_total}</Ltr> שלבי חובה
                    </span>
                    <span className="ms-auto font-semibold text-forest">
                      {l.status === 'not_started' ? 'להתחיל' : 'להמשיך'} ←
                    </span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
