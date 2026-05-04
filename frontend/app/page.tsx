'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ProgressBar, ProgressRing } from '@/components/ui/progress-ring';
import { apiGet, apiPost } from '@/lib/api';

type Course = {
  id: number;
  code: string;
  name: string;
  year: number;
  semester: string;
  attendance_threshold: number;
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
      const data = await apiGet<Course[]>('/api/courses');
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

  return (
    <main className="mx-auto max-w-[1200px] px-10 pb-20 pt-14">
      {/* Hero */}
      <header className="mb-10">
        <div className="mb-4 flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-forest font-display text-xl tracking-tight text-paper">
            cg
          </div>
          <span className="font-display text-lg text-ink-2">course-grader</span>
        </div>
        <h1 className="font-display text-[44px] leading-tight tracking-tight">
          {greeting()}.
        </h1>
        <p className="mt-3 max-w-xl text-[17px] leading-relaxed text-ink-2">
          {courses.length === 0
            ? "No active courses yet — start one when you're ready."
            : remaining > 0
              ? `You have ${remaining} submissions left to grade across ${courses.length} ${courses.length === 1 ? 'course' : 'courses'}.`
              : `${courses.length} ${courses.length === 1 ? 'course' : 'courses'} on file. All caught up.`}
        </p>
      </header>

      {/* Welcome hint */}
      <div className="hint mb-6">
        <span className="hint-icon">i</span>
        <div>
          <strong className="font-semibold text-ink">Working through a course?</strong> Pick it below — you'll
          land on the grading dashboard. Each course flows through six steps in the sidebar:{' '}
          <em>Imports → Queue → Curve → Overrides → Gradebook → Settings</em>. Jump around freely.
        </div>
      </div>

      {/* Active courses */}
      <div className="mb-3.5 flex items-baseline justify-between">
        <div className="label-eyebrow">Active</div>
        <Button variant="soft" size="sm" onClick={() => setShowNew(true)}>
          + New course
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-ink-3">Loading courses…</p>
      ) : null}
      {error ? <p className="text-sm text-bad">{error}</p> : null}

      <div className="grid gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))' }}>
        {courses.map((course) => (
          <CourseCard key={course.id} course={course} />
        ))}
        {showNew ? (
          <NewCourseCard form={form} setForm={setForm} onSubmit={submit} onCancel={() => setShowNew(false)} />
        ) : null}
        {!showNew && courses.length < 6 ? (
          <button
            onClick={() => setShowNew(true)}
            className="grid place-items-center gap-2 rounded-lg border-[1.5px] border-dashed border-border p-8 text-ink-3 transition-colors hover:border-ink-4 hover:text-ink"
          >
            <span className="text-2xl leading-none">+</span>
            <span className="text-sm">Start a new course</span>
          </button>
        ) : null}
      </div>
    </main>
  );
}

function CourseCard({ course }: { course: CourseStats }) {
  const remaining = course.submissions_total - course.submissions_graded;
  return (
    <Link
      href={`/course/${course.id}`}
      className="block rounded-lg border border-border bg-card p-[22px] text-ink shadow-soft transition hover:-translate-y-0.5 hover:border-ink-4 hover:shadow-card"
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="mb-1 text-[12px] uppercase tracking-wider text-ink-3">
            {course.code} · {course.year} · Sem {course.semester}
          </div>
          <div className="font-display text-[22px] leading-tight">{course.name}</div>
        </div>
        <ProgressRing
          value={course.submissions_graded}
          max={Math.max(course.submissions_total, 1)}
          size={56}
          stroke={5}
        />
      </div>

      <div className="mb-2.5 flex items-baseline justify-between">
        <div className="text-[13px] text-ink-2">
          <span className="font-display tnum text-base text-ink">{course.submissions_graded}</span>
          <span className="text-ink-3"> / {course.submissions_total} graded</span>
        </div>
        {course.last_touched ? <div className="text-xs text-ink-3">{course.last_touched}</div> : null}
      </div>
      <ProgressBar
        value={course.submissions_total > 0 ? (course.submissions_graded / course.submissions_total) * 100 : 0}
      />

      <div className="mt-4 flex flex-wrap gap-2">
        <span className="pill">{course.student_count} students</span>
        {remaining > 0 ? (
          <span className="pill pill-terra">{remaining} to grade</span>
        ) : (
          <span className="pill pill-ok">All graded</span>
        )}
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
