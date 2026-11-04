'use client';

import { useCallback, useMemo } from 'react';

import { lessonNumber, type LessonNav } from '@/components/lessons/celebration';
import { LessonPlayer } from '@/components/lessons/lesson-player';
import { listStudentLessons, studentLessonBackend } from '@/components/lessons/student-backend';

/* One guided lesson for the student behind this personal link. The player
 * links back to the course page (/r/<token>) and the lesson list. */
export default function StudentLessonPage({ params }: { params: { token: string; slug: string } }) {
  const { token } = params;
  const slug = safeDecode(params.slug);
  const backend = useMemo(() => studentLessonBackend(token, slug), [token, slug]);
  // The published lessons, in course order: the next one, asked for when the
  // lesson has just been completed.
  const loadNav = useCallback(async (): Promise<LessonNav> => {
    const list = await listStudentLessons(token);
    const slugs = list.map((l) => l.slug);
    const i = slugs.indexOf(slug);
    const next = i >= 0 ? list[i + 1] : undefined;
    return {
      lessons: `/r/${token}/lessons`,
      home: `/r/${token}`,
      next: next ? { href: `/r/${token}/lessons/${encodeURIComponent(next.slug)}`, title: next.title } : null,
      number: lessonNumber(slug)
    };
  }, [token, slug]);
  // Keyed: the player takes its backend once, so another lesson is a fresh player.
  return <LessonPlayer key={`${token}/${slug}`} backend={backend} token={token} loadNav={loadNav} />;
}

function safeDecode(segment: string) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
