'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import type { LessonSummary } from '@/components/lessons/instructor-lessons';
import { LessonPlayer } from '@/components/lessons/lesson-player';
import { previewLessonBackend } from '@/components/lessons/preview-backend';
import { apiGet, errorMessage } from '@/lib/api';
import { lessonsHref } from '@/lib/course-sections';

/* Lesson preview: the student player, on any version of the lesson, fed by
 * the instructor preview endpoints. Answers get the real feedback, but nothing
 * is saved — no student record, attempt, experiment or device draft — and a
 * reload starts over. ?version=<number> picks the version (default: latest).
 * Questions whose private answer key isn't loaded are named in a warning:
 * the preview (and students) can't check them, and publishing is blocked. */

export default function LessonPreviewPage({ params }: { params: { id: string; lessonId: string } }) {
  const courseId = Number(params.id);
  const lessonId = Number(params.lessonId);
  const [lesson, setLesson] = useState<LessonSummary | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missingKeys, setMissingKeys] = useState<string[]>([]);

  useEffect(() => {
    apiGet<LessonSummary[]>(`/api/courses/${courseId}/lessons`)
      .then((list) => {
        const found = list.find((l) => l.id === lessonId);
        if (!found) return setError('This lesson isn’t part of this course.');
        if (!found.versions.length) return setError('This lesson has no versions yet.');
        const wanted = Number(new URLSearchParams(window.location.search).get('version'));
        const version = found.versions.find((v) => v.number === wanted) ?? found.versions[found.versions.length - 1];
        setLesson(found);
        setVersionId(version.id);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [courseId, lessonId]);

  useEffect(() => {
    if (versionId == null) return;
    setMissingKeys([]);
    apiGet<{ missing_answer_keys?: string[] }>(`/api/courses/${courseId}/lessons/${lessonId}/preview?version_id=${versionId}`)
      .then((p) => setMissingKeys(p.missing_answer_keys ?? []))
      .catch(() => undefined);
  }, [courseId, lessonId, versionId]);

  // One backend per version: its in-memory state is the whole preview session.
  const backend = useMemo(
    () => (versionId == null ? null : previewLessonBackend(courseId, lessonId, versionId)),
    [courseId, lessonId, versionId]
  );

  const back = (
    <Link href={lessonsHref(courseId, lessonId)} className="text-forest hover:underline">
      ← Back to lesson
    </Link>
  );

  if (error) {
    return (
      <div className="p-10">
        <div className="text-bad">{error}</div>
        <div className="mt-3 text-[14px]">{back}</div>
      </div>
    );
  }
  if (!lesson || !backend) return <div className="p-10 text-ink-3">Loading…</div>;

  const liveId = lesson.status === 'published' ? lesson.active_version?.id : undefined;
  const banner = (
    <div dir="ltr" lang="en" className="sticky top-0 z-40 border-b border-terracotta-soft bg-terracotta-tint px-4 py-2.5 text-[13px]">
      <div className="mx-auto flex max-w-[1120px] flex-wrap items-center gap-x-4 gap-y-2">
        {back}
        <span className="font-semibold" title="Answers get the real feedback; answers, experiments and choices vanish on reload.">
          Lesson preview — nothing is saved
        </span>
        <span className="hidden text-ink-3 xl:inline">Real feedback; answers, experiments and choices vanish on reload.</span>
        <label className="ml-auto flex items-center gap-2">
          Version
          <select
            className="h-8 max-w-[260px] rounded-md border border-border bg-card px-2"
            value={versionId ?? ''}
            onChange={(e) => {
              const id = Number(e.target.value);
              const version = lesson.versions.find((v) => v.id === id);
              if (!version) return;
              setVersionId(id);
              window.history.replaceState(null, '', `?version=${version.number}${window.location.hash}`);
            }}
          >
            {[...lesson.versions].reverse().map((v) => (
              <option key={v.id} value={v.id}>
                v{v.number} · {v.status}
                {v.id === liveId ? ' · live to students' : ''}
              </option>
            ))}
          </select>
        </label>
      </div>
      {missingKeys.length ? (
        <div role="alert" className="mx-auto mt-2 max-w-[1120px] rounded-md bg-warn-soft px-3 py-2 text-ink">
          <span className="font-semibold">⚠ No answer key loaded (or the loaded one doesn’t fit) for {missingKeys.length} question(s):</span>{' '}
          <span className="font-mono text-[12px]">{missingKeys.join(', ')}</span>. Their answers can’t be checked here or by
          students, and this version can’t be published until the private answer keys are imported (Lessons tab).
        </div>
      ) : null}
    </div>
  );

  return <LessonPlayer key={versionId} backend={backend} token={null} banner={banner} />;
}
