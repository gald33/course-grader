'use client';

import Link from 'next/link';
import { Plus } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ProgressRing } from '@/components/ui/progress-ring';
import { apiGet, apiPost, errorMessage } from '@/lib/api';

type Course = {
  id: number;
  code: string;
  name: string;
  year: number;
  semester: string;
  attendance_threshold: number;
  archived_at: string | null;
};

type CourseStats = Course & {
  student_count: number;
  submissions_total: number;
  submissions_graded: number;
  last_touched?: string;
};

function greeting() {
  const h = new Date().getHours();
  if (h < 5) return 'Late night';
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

export default function HomePage() {
  const [courses, setCourses] = useState<CourseStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [archived, setArchived] = useState<Course[]>([]);
  const [showArchived, setShowArchived] = useState(false);

  const [form, setForm] = useState({
    code: '',
    name: '',
    year: new Date().getFullYear(),
    semester: 'A',
    attendance_threshold: 80
  });

  const refresh = async () => {
    setLoading(true);
    try {
      const all = await apiGet<Course[]>('/api/courses?include_archived=true');
      const data = all.filter((c) => !c.archived_at);
      setArchived(all.filter((c) => c.archived_at));
      // Hydrate per-course stats best-effort; falls back to zeros if endpoints unreachable.
      const enriched: CourseStats[] = await Promise.all(
        data.map(async (c) => {
          try {
            const subs = await apiGet<unknown[]>(`/api/courses/${c.id}/submissions`);
            const gb = await apiGet<{ rows: unknown[] }>(`/api/courses/${c.id}/gradebook`);
            return {
              ...c,
              student_count: gb.rows.length,
              submissions_total: subs.length,
              submissions_graded: 0
            };
          } catch {
            return { ...c, student_count: 0, submissions_total: 0, submissions_graded: 0 };
          }
        })
      );
      setCourses(enriched);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const remaining = useMemo(
    () => courses.reduce((n, c) => n + (c.submissions_total - c.submissions_graded), 0),
    [courses]
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await apiPost('/api/courses', form);
    setForm({ ...form, code: '', name: '' });
    setShowNew(false);
    await refresh();
  };

  const setArchivedState = async (course: Course, archive: boolean) => {
    if (archive && !window.confirm(`Archive ${course.code} · ${course.name}? It leaves the home page; you can restore it below.`)) {
      return;
    }
    try {
      await apiPost(`/api/courses/${course.id}/${archive ? 'archive' : 'restore'}`);
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <>
    <div className="flex h-[52px] items-center gap-3 border-b border-line-soft px-5">
      <div className="grid h-6 w-6 place-items-center rounded-[7px] bg-forest text-[11px] font-semibold tracking-tight text-paper">
        cg
      </div>
      <span className="text-[13px] font-medium tracking-tight">course-grader</span>
      <span className="text-ink-4">/</span>
      <span className="text-[13px] text-ink-2">Courses</span>
    </div>
    <main className="mx-auto max-w-[1120px] px-6 pb-20 pt-12">
      {/* Hero */}
      <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
        <div>
        <h1 className="text-[36px] font-medium leading-[1.1] tracking-[-0.035em]">
          {greeting()}
        </h1>
        <p className="mt-2 max-w-xl text-[15px] leading-relaxed text-ink-2">
          {courses.length === 0
            ? "No active courses yet — start one when you're ready."
            : remaining > 0
              ? `You have ${remaining} submissions left to grade across ${courses.length} ${courses.length === 1 ? 'course' : 'courses'}.`
              : `${courses.length} ${courses.length === 1 ? 'course' : 'courses'} on file. All caught up.`}
        </p>
        </div>
        <button
          onClick={() => setShowNew(true)}
          className="inline-flex h-9 items-center gap-2 rounded-[8px] bg-ink px-3.5 text-[13px] font-medium text-paper transition hover:bg-ink/90"
        >
          <Plus className="h-3.5 w-3.5" strokeWidth={2.2} aria-hidden />
          New course
        </button>
      </header>

      {/* Welcome hint */}
      <div className="hint mb-6">
        <span className="hint-icon">i</span>
        <div>
          <strong className="font-semibold text-ink">Working through a course?</strong> Pick it below. The course
          sidebar groups its pages by job: <em>Students</em> (roster, accounts, teams), <em>Teaching</em> (lessons,
          peer review) and <em>Grading</em> (queue → rubrics → curve → overrides → gradebook). A new course opens on Students,
          since the roster comes first.
        </div>
      </div>

      {/* Active courses */}
      <div className="mb-3.5 flex items-center gap-2.5">
        <h2 className="text-[14px] font-medium tracking-normal">Active courses</h2>
        <span className="tnum rounded-[6px] bg-paper-2 px-1.5 text-[12px] text-ink-2">{courses.length}</span>
      </div>

      {loading ? (
        <p className="text-sm text-ink-3">Loading courses…</p>
      ) : null}
      {error ? <p className="text-sm text-bad">{error}</p> : null}

      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))' }}>
        {courses.map((course) => (
          <CourseCard key={course.id} course={course} onArchive={() => void setArchivedState(course, true)} />
        ))}
        {showNew ? (
          <NewCourseCard form={form} setForm={setForm} onSubmit={submit} onCancel={() => setShowNew(false)} />
        ) : null}
        {!showNew && courses.length < 6 ? (
          <button
            onClick={() => setShowNew(true)}
            className="grid min-h-[200px] place-content-center justify-items-center gap-2.5 rounded-lg border border-dashed border-border p-8 text-[13px] text-ink-2 transition-colors hover:border-ink-4 hover:text-ink"
          >
            <span className="grid h-9 w-9 place-items-center rounded-[10px] border border-border bg-card">
              <Plus className="h-4 w-4" aria-hidden />
            </span>
            <span>Start a new course</span>
          </button>
        ) : null}
      </div>

      {archived.length > 0 ? (
        <section className="mt-10">
          <button onClick={() => setShowArchived((v) => !v)} className="label-eyebrow hover:text-ink">
            {showArchived ? '▾' : '▸'} Archived ({archived.length})
          </button>
          {showArchived ? (
            <ul className="mt-3 divide-y divide-border rounded-lg border border-border bg-card">
              {archived.map((course) => (
                <li key={course.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <Link href={`/course/${course.id}`} className="min-w-0 text-ink no-underline hover:underline">
                    <span className="text-[12px] uppercase tracking-wider text-ink-3">
                      {course.code} · {course.year} · Sem {course.semester}
                    </span>{' '}
                    <span className="font-display">{course.name}</span>
                  </Link>
                  <Button size="sm" variant="soft" onClick={() => void setArchivedState(course, false)}>
                    Restore
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </main>
    </>
  );
}

function CourseCard({ course, onArchive }: { course: CourseStats; onArchive: () => void }) {
  const remaining = course.submissions_total - course.submissions_graded;
  const pct = course.submissions_total > 0 ? Math.round((course.submissions_graded / course.submissions_total) * 100) : 0;
  return (
    <Link
      href={`/course/${course.id}`}
      className="flex flex-col gap-5 rounded-lg border border-line-soft bg-card p-5 text-ink no-underline shadow-card transition hover:-translate-y-0.5 hover:border-border hover:shadow-lift"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[11px] uppercase tracking-[0.02em] text-ink-3">
            {course.code} · {course.year} · Sem {course.semester}
          </div>
          <div className="mt-1 text-[17px] font-medium leading-tight tracking-[-0.02em]">{course.name}</div>
        </div>
        <div className="relative shrink-0">
          <ProgressRing
            value={course.submissions_graded}
            max={Math.max(course.submissions_total, 1)}
            size={48}
            stroke={4}
          />
          <span className="tnum absolute inset-0 grid place-items-center text-[11px] font-medium">{pct}%</span>
        </div>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="tnum text-[24px] font-medium tracking-[-0.03em]">{course.submissions_graded}</span>
        <span className="text-[13px] text-ink-3">/ {course.submissions_total} graded</span>
        {remaining > 0 ? (
          <span className="pill pill-terra ml-auto">{remaining} to grade</span>
        ) : (
          <span className="pill pill-ok ml-auto">All graded</span>
        )}
      </div>
      <div className="flex items-center gap-3 border-t border-line-soft pt-3.5 text-[12px] text-ink-2">
        <span>{course.student_count} students</span>
        {course.last_touched ? <span>{course.last_touched}</span> : null}
        <button
          onClick={(e) => {
            // The card is a link; keep the click from navigating.
            e.preventDefault();
            e.stopPropagation();
            onArchive();
          }}
          className="ml-auto text-ink-3 hover:text-ink"
        >
          Archive
        </button>
      </div>
    </Link>
  );
}

function NewCourseCard({
  form,
  setForm,
  onSubmit,
  onCancel
}: {
  form: { code: string; name: string; year: number; semester: string; attendance_threshold: number };
  setForm: (v: typeof form) => void;
  onSubmit: (e: FormEvent) => void;
  onCancel: () => void;
}) {
  return (
    <form
      onSubmit={onSubmit}
      className="rounded-lg border border-forest bg-card p-[22px] shadow-card"
    >
      <div className="mb-3.5 flex items-baseline justify-between">
        <div className="font-display text-xl">New course</div>
        <button type="button" onClick={onCancel} className="text-sm text-forest hover:underline">
          Cancel
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        <div className="col-span-2">
          <Label>Course name</Label>
          <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Applied Machine Learning" />
        </div>
        <div>
          <Label>Code</Label>
          <Input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="CS-7920" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label>Year</Label>
            <Input
              type="number"
              value={form.year}
              onChange={(e) => setForm({ ...form, year: Number(e.target.value) })}
            />
          </div>
          <div>
            <Label>Sem</Label>
            <Input value={form.semester} onChange={(e) => setForm({ ...form, semester: e.target.value })} />
          </div>
        </div>
      </div>
      <div className="mt-4 flex justify-end">
        <Button type="submit">Create course</Button>
      </div>
    </form>
  );
}
