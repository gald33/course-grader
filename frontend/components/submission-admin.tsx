'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { apiDelete, apiGet, apiPut, errorMessage } from '@/lib/api';

type CourseStudent = { student_id: number; national_id: string; name: string };

/** Fix a submission's group (the filename parser can group students wrongly)
 * or delete the submission with its files. Scores follow group membership,
 * so a removed student stops getting this submission's grade. */
export function SubmissionAdmin({
  courseId,
  submissionId,
  memberStudentIds,
  onChanged,
  setToast
}: {
  courseId: number;
  submissionId: number;
  memberStudentIds: number[];
  onChanged: () => Promise<void> | void;
  setToast: (m: string) => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [students, setStudents] = useState<CourseStudent[]>([]);
  const [selected, setSelected] = useState<number[]>(memberStudentIds);
  const [adding, setAdding] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSelected(memberStudentIds);
    apiGet<{ rows: CourseStudent[] }>(`/api/courses/${courseId}/gradebook`)
      .then((gb) => setStudents(gb.rows))
      .catch((e) => setToast(`Couldn't load students: ${errorMessage(e)}`));
  }, [open, courseId]);

  const byId = useMemo(() => new Map(students.map((s) => [s.student_id, s])), [students]);
  const others = students.filter((s) => !selected.includes(s.student_id));
  const dirty =
    selected.length !== memberStudentIds.length || selected.some((id) => !memberStudentIds.includes(id));

  const saveGroup = async () => {
    setBusy(true);
    try {
      await apiPut(`/api/submissions/${submissionId}/members`, { student_ids: selected });
      setToast('Group updated');
      await onChanged();
      setOpen(false);
    } catch (e) {
      setToast(`Couldn't update group: ${errorMessage(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete submission #${submissionId} with all its files, runs and scores? This can't be undone.`)) {
      return;
    }
    setBusy(true);
    try {
      await apiDelete(`/api/submissions/${submissionId}`);
      router.push(`/course/${courseId}`);
    } catch (e) {
      setToast(`Couldn't delete submission: ${errorMessage(e)}`);
      setBusy(false);
    }
  };

  return (
    <div className="relative">
      <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)} title="Edit group or delete">
        Manage
      </Button>
      {open ? (
        <div className="absolute right-0 top-full z-50 mt-2 w-[340px] rounded-lg border border-border bg-card p-4 shadow-card">
          <div className="label-eyebrow mb-2">Group members</div>
          <ul className="mb-3 space-y-1.5">
            {selected.map((id) => (
              <li key={id} className="flex items-center justify-between gap-2 text-[13px]">
                <span>
                  {byId.get(id)?.name ?? `Student #${id}`}{' '}
                  <span className="text-ink-3">{byId.get(id)?.national_id}</span>
                </span>
                <button
                  className="text-ink-3 hover:text-bad disabled:opacity-30"
                  disabled={selected.length <= 1}
                  title={selected.length <= 1 ? 'A submission needs at least one student' : 'Remove from group'}
                  onClick={() => setSelected(selected.filter((x) => x !== id))}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <div className="mb-3 flex gap-2">
            <select
              className="min-w-0 flex-1 rounded-md border border-border bg-card px-2 py-1 text-[13px]"
              value={adding}
              onChange={(e) => setAdding(e.target.value)}
            >
              <option value="">Add an enrolled student…</option>
              {others.map((s) => (
                <option key={s.student_id} value={s.student_id}>
                  {s.name} · {s.national_id}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              disabled={!adding}
              onClick={() => {
                setSelected([...selected, Number(adding)]);
                setAdding('');
              }}
            >
              Add
            </Button>
          </div>
          <div className="flex items-center justify-between border-t border-border pt-3">
            <Button size="sm" variant="ghost" className="text-bad" disabled={busy} onClick={() => void remove()}>
              Delete submission
            </Button>
            <Button size="sm" disabled={busy || !dirty || selected.length === 0} onClick={() => void saveGroup()}>
              Save group
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
