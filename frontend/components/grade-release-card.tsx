'use client';

import { useEffect, useState } from 'react';

import { apiGet, apiPut, errorMessage } from '@/lib/api';

/* Instructor control: which gradebook components students see on their page. */

type Release = { key: string; released: boolean; released_at: string | null };

const LABELS: Record<string, string> = {
  hw1: 'HW1 + feedback',
  hw2: 'HW2 + feedback',
  project: 'Project + feedback',
  talks: 'Talks',
  attendance: 'Attendance',
  final: 'Final score'
};

export function GradeReleaseCard({ courseId, setToast }: { courseId: number; setToast: (m: string) => void }) {
  const [components, setComponents] = useState<Release[]>([]);

  useEffect(() => {
    apiGet<{ components: Release[] }>(`/api/courses/${courseId}/grade-releases`)
      .then((r) => setComponents(r.components))
      .catch((e) => setToast(errorMessage(e)));
  }, [courseId, setToast]);

  const toggle = async (c: Release) => {
    try {
      const r = await apiPut<{ components: Release[] }>(`/api/courses/${courseId}/grade-releases/${c.key}`, {
        released: !c.released
      });
      setComponents(r.components);
      setToast(`${LABELS[c.key] ?? c.key} ${c.released ? 'hidden from' : 'released to'} students`);
    } catch (e) {
      setToast(errorMessage(e));
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card px-5 py-4 shadow-soft">
      <div className="label-eyebrow text-ink-3">Released to students</div>
      <p className="mt-1 text-[13px] text-ink-2">
        Students (and “view as student”) see a component under “My grades” only once it is released here.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {components.map((c) => (
          <label key={c.key} className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-[13px]">
            <input type="checkbox" checked={c.released} onChange={() => void toggle(c)} />
            {LABELS[c.key] ?? c.key}
          </label>
        ))}
      </div>
    </div>
  );
}
