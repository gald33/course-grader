'use client';

import { useMemo } from 'react';

import { LessonPlayer } from '@/components/lessons/lesson-player';
import { studentLessonBackend } from '@/components/lessons/student-backend';

/* One guided lesson for the student behind this personal link. The player
 * links back to the course page (/r/<token>) and the lesson list. */
export default function StudentLessonPage({ params }: { params: { token: string; slug: string } }) {
  const { token } = params;
  const slug = safeDecode(params.slug);
  const backend = useMemo(() => studentLessonBackend(token, slug), [token, slug]);
  // Keyed: the player takes its backend once, so another lesson is a fresh player.
  return <LessonPlayer key={`${token}/${slug}`} backend={backend} token={token} />;
}

function safeDecode(segment: string) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
