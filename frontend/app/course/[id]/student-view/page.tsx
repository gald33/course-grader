'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { StudentView, type Home } from '@/components/student-view';
import { apiGet, errorMessage } from '@/lib/api';

/* "View as student": the exact page a student sees, rendered read-only for
 * the instructor. Data comes from the instructor API, so no student link or
 * password is used, and nothing can be submitted from here. */

type Roster = {
  teams: { id: number; name: string }[];
  students: { student_id: number; name: string; national_id: string; team_id: number | null }[];
};

export default function StudentViewPreview({ params }: { params: { id: string } }) {
  const courseId = Number(params.id);
  const [roster, setRoster] = useState<Roster | null>(null);
  const [studentId, setStudentId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Roster>(`/api/courses/${courseId}/peer/teams`)
      .then((r) => {
        setRoster(r);
        const wanted = Number(new URLSearchParams(window.location.search).get('student'));
        const first = r.students.find((s) => s.student_id === wanted) ?? r.students[0];
        setStudentId(first ? first.student_id : null);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [courseId]);

  const teamName = useMemo(() => Object.fromEntries((roster?.teams ?? []).map((t) => [t.id, t.name])), [roster]);
  const sorted = useMemo(
    () =>
      [...(roster?.students ?? [])].sort(
        (a, b) => (teamName[a.team_id ?? -1] ?? '~').localeCompare(teamName[b.team_id ?? -1] ?? '~') || a.name.localeCompare(b.name)
      ),
    [roster, teamName]
  );
  const current = sorted.find((s) => s.student_id === studentId);

  const banner = (
    <div dir="ltr" className="sticky top-0 z-40 border-b border-terracotta-soft bg-terracotta-tint px-4 py-2.5 text-[13px]">
      <div className="mx-auto flex max-w-[960px] flex-wrap items-center gap-x-4 gap-y-2">
        <Link href={`/course/${courseId}`} className="text-forest hover:underline">
          ← Back to course
        </Link>
        <span className="font-semibold">Student view · preview only — nothing you do here is saved</span>
        <label className="ml-auto flex items-center gap-2">
          Viewing as
          <select
            className="h-8 max-w-[260px] rounded-md border border-border bg-card px-2"
            value={studentId ?? ''}
            onChange={(e) => {
              const id = Number(e.target.value);
              setStudentId(id);
              window.history.replaceState(null, '', `?student=${id}`);
            }}
          >
            {sorted.map((s) => (
              <option key={s.student_id} value={s.student_id}>
                {s.name} {s.team_id ? `· ${teamName[s.team_id]}` : '· no team'}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );

  if (error) return <div className="p-10 text-bad">{error}</div>;
  if (!roster) return <div className="p-10 text-ink-3">Loading…</div>;
  if (!current) {
    return (
      <div className="p-10 text-ink-3">
        No students in this course yet. <Link href={`/course/${courseId}`} className="text-forest underline">Back</Link>
      </div>
    );
  }

  return (
    <StudentView
      key={current.student_id}
      token={`preview-${current.student_id}`}
      loader={() => apiGet<Home>(`/api/courses/${courseId}/peer/student-view/${current.student_id}`)}
      preview
      banner={banner}
    />
  );
}
