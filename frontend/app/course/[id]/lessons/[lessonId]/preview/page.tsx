'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import type { LessonSummary } from '@/components/lessons/instructor-lessons';
import { LessonPlayer } from '@/components/lessons/lesson-player';
import { previewLessonBackend } from '@/components/lessons/preview-backend';
import { apiGet, errorMessage } from '@/lib/api';

/* Lesson preview: the student player, on any version of the lesson, fed by
 * the instructor preview endpoints. Answers get the real feedback, but nothing
 * is saved — no student record, attempt, experiment or device draft — and a
 * reload starts over. ?version=<number> picks the version (default: latest). */

export default function LessonPreviewPage({ params }: { params: { id: string; lessonId: string } }) {
  const courseId = Number(params.id);
  const lessonId = Number(params.lessonId);
  const [lesson, setLesson] = useState<LessonSummary | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  // One backend per version: its in-memory state is the whole preview session.
  const backend = useMemo(
    () => (versionId == null ? null : previewLessonBackend(courseId, lessonId, versionId)),
    [courseId, lessonId, versionId]
  );

  const back = (
    <Link href={`/course/${courseId}`} className="text-forest hover:underline">
      ← Back to course
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
    </div>
  );

  return <LessonPlayer key={versionId} backend={backend} token={null} banner={banner} />;
}
