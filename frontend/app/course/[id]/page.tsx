'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';

import { Avatar, AvatarStack } from '@/components/ui/avatar';
import { BilingualName, isHebrew } from '@/components/ui/bilingual-name';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { GradeReleaseCard } from '@/components/grade-release-card';
import { PeerReviewStep } from '@/components/peer-review/peer-review-step';
import { RosterCard } from '@/components/roster-card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ProgressBar, ProgressRing } from '@/components/ui/progress-ring';
import { apiBase, apiFetch, apiGet, apiPatch, apiPost, putToStorage, type UploadTarget } from '@/lib/api';

type Course = {
  id: number;
  code: string;
  name: string;
  year: number;
  semester: string;
  attendance_threshold: number;
};

type SubmissionRequirements = {
  needs_pdf: boolean;
  needs_colab: boolean;
  has_pdf: boolean;
  has_colab_url: boolean;
  has_fetched_colab: boolean;
  missing_report_flag: boolean;
  missing_data_flag: boolean;
  missing_code_flag: boolean;
  missing: string[];
  complete: boolean;
  overridden_by_manual_grade: boolean;
};

type Submission = {
  id: number;
  course_id: number;
  assignment_id: number;
  assignment_type: string;
  workcode: number;
  group_identifier: string;
  member_ids: string[];
  member_names: string[];
  originality_score_filename: number | null;
  originality_score_pdf: number | null;
  originality_mismatch: boolean;
  pinned_run_id: number | null;
  last_run_status: string | null;
  last_run_ratio: number | null;
  has_colab_url: boolean;
  rubric_filled: number;
  rubric_total: number;
  requirements: SubmissionRequirements | null;
};

type GradebookRow = {
  enrollment_id: number;
  student_id: number;
  national_id: string;
  name: string;
  attendance_exempt: boolean;
  attendance_percent: number | null;
  attendance_score: number;
  hw1: number;
  hw2: number;
  project_code: number;
  project_report: number;
  presentation: number;
  final_talk: number;
  project_base: number;
  bonus_points: number;
  project_with_bonus: number;
  final: number;
  final_uncurved: number;
  peer: Record<string, { rounds: number[]; peer: number; weight: number; auto: number }>;
};

/** Small "peer" tag on a gradebook cell whose tasks include applied peer-review rounds. */
function PeerTag({ row, tasks }: { row: GradebookRow; tasks: string[] }) {
  const parts = tasks.filter((t) => row.peer?.[t]);
  if (parts.length === 0) return null;
  const title = parts
    .map((t) => {
      const p = row.peer[t];
      const w = Math.round(p.weight * 100);
      return `${t}: ${100 - w}% own score ${p.auto} + ${w}% peer ${p.peer.toFixed(1)} (round ${p.rounds.join(', ')})`;
    })
    .join('\n');
  return (
    <span className="ml-1 text-[11px] text-forest" title={title}>
      peer
    </span>
  );
}

type CurvePoints = { points: number[]; tunable: boolean };
type ActiveCurve = {
  id: number;
  revision_number: number;
  note: string;
  mapping: Record<string, CurvePoints>;
  final_distribution: { mean: number; sigma: number } | null;
  shared_bonus: number;
  created_at: string;
};

type OverrideRow = {
  id: number;
  student_id: number;
  student_name: string | null;
  student_national_id: string | null;
  submission_id: number | null;
  component: string;
  delta: number;
  reason: string;
  created_at: string;
};

type Assignment = {
  id: number;
  workcode: number;
  name: string;
  assignment_type: string;
  submission_count: number;
};

type StepKey = 'queue' | 'imports' | 'peer' | 'curve' | 'overrides' | 'gradebook' | 'settings';

const STEPS: { key: StepKey; label: string; icon: string; title: string; sub: string }[] = [
  { key: 'queue', label: 'Grading queue', icon: '📥', title: 'Grading queue', sub: 'Submissions, snapshots, and runs.' },
  { key: 'imports', label: 'Imports', icon: '⤴', title: 'Imports', sub: 'Roster, assignment ZIPs, presentation sheets.' },
  { key: 'peer', label: 'Peer review', icon: '⇄', title: 'Peer review', sub: 'Presentation schedule, student reviews, and round scores.' },
  { key: 'curve', label: 'Curve & calibration', icon: '⚙', title: 'Curve & calibration', sub: 'Adjust dimension curves and attendance threshold.' },
  { key: 'overrides', label: 'Overrides', icon: '✎', title: 'Overrides', sub: 'Per-student deltas with reasons.' },
  { key: 'gradebook', label: 'Gradebook', icon: '▦', title: 'Gradebook', sub: 'Final scores by component.' },
  { key: 'settings', label: 'Course settings', icon: '◉', title: 'Course settings', sub: 'Course-level preferences.' }
];

/* =============== Page =============== */

export default function CoursePage({ params }: { params: { id: string } }) {
  const courseId = Number(params.id);
  const [course, setCourse] = useState<Course | null>(null);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [gradebook, setGradebook] = useState<GradebookRow[]>([]);
  const [activeCurve, setActiveCurve] = useState<ActiveCurve | null>(null);
  const [dimensionDistributions, setDimensionDistributions] = useState<Record<string, number[]>>({});
  const [overrides, setOverrides] = useState<OverrideRow[]>([]);
  const [step, setStep] = useState<StepKey>('queue');
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    const stored = typeof window !== 'undefined' ? (localStorage.getItem('cg-course-step') as StepKey | null) : null;
    if (stored && STEPS.some((s) => s.key === stored)) setStep(stored);
  }, []);
  useEffect(() => {
    if (typeof window !== 'undefined') localStorage.setItem('cg-course-step', step);
  }, [step]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  const loadAll = async () => {
    const [courseRes, assignmentsRes, submissionsRes, gradebookRes, curveRes, overridesRes, distRes] = await Promise.all([
      apiGet<Course>(`/api/courses/${courseId}`),
      apiGet<Assignment[]>(`/api/courses/${courseId}/assignments`),
      apiGet<Submission[]>(`/api/courses/${courseId}/submissions`),
      apiGet<{ rows: GradebookRow[] }>(`/api/courses/${courseId}/gradebook`),
      apiGet<ActiveCurve>(`/api/courses/${courseId}/curves/active`).catch(() => null),
      apiGet<OverrideRow[]>(`/api/courses/${courseId}/overrides`).catch(() => [] as OverrideRow[]),
      apiGet<Record<string, number[]>>(`/api/courses/${courseId}/curves/dimension-distributions`).catch(() => ({}))
    ]);
    setCourse(courseRes);
    setAssignments(assignmentsRes);
    setSubmissions(submissionsRes);
    setGradebook(gradebookRes.rows);
    setActiveCurve(curveRes);
    setOverrides(overridesRes);
    setDimensionDistributions(distRes);
  };

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  const counts: Record<StepKey, number | null> = {
    queue: submissions.length,
    imports: assignments.length,
    peer: null,
    curve: activeCurve?.revision_number ?? 0,
    overrides: overrides.length,
    gradebook: gradebook.length,
    settings: null
  };

  const graded = submissions.filter((s) => derivedState(s) === 'graded').length;
  const total = submissions.length;
  const remaining = total - graded;

  if (!course) {
    return <div className="p-10 text-ink-3">Loading…</div>;
  }

  const stepInfo = STEPS.find((s) => s.key === step) ?? STEPS[0];
  const stepIdx = STEPS.findIndex((s) => s.key === step);

  return (
    <div className="grid min-h-screen" style={{ gridTemplateColumns: '248px 1fr' }}>
      <Sidebar
        course={course}
        graded={graded}
        total={total}
        remaining={remaining}
        step={step}
        setStep={setStep}
        counts={counts}
      />

      <div className="min-w-0">
        {/* Step header */}
        <div className="mx-auto max-w-[1500px] px-10 pt-9">
          <div className="flex items-end justify-between gap-6">
            <div>
              <div className="label-eyebrow mb-1.5">
                Step {stepIdx + 1} of {STEPS.length}
              </div>
              <h1 className="font-display text-[34px] leading-tight tracking-tight">{stepInfo.title}</h1>
              <p className="mt-1 text-[15px] text-ink-3">{stepInfo.sub}</p>
            </div>
          </div>
          <div className="mt-5 h-px bg-border" />
        </div>

        <div className="mx-auto max-w-[1500px] px-10 pb-20">
          {step === 'queue' ? (
            <QueueStep
              submissions={submissions}
              assignments={assignments}
              courseId={courseId}
              setToast={setToast}
              refresh={loadAll}
            />
          ) : null}
          {step === 'imports' ? (
            <ImportsStep courseId={courseId} assignments={assignments} setToast={setToast} refresh={loadAll} />
          ) : null}
          {step === 'peer' ? <PeerReviewStep courseId={courseId} setToast={setToast} /> : null}
          {step === 'curve' ? (
            <CurveStep
              courseId={courseId}
              course={course}
              activeCurve={activeCurve}
              dimensionDistributions={dimensionDistributions}
              gradebook={gradebook}
              setToast={setToast}
              refresh={loadAll}
            />
          ) : null}
          {step === 'overrides' ? (
            <OverridesStep
              courseId={courseId}
              gradebook={gradebook}
              overrides={overrides}
              setToast={setToast}
              refresh={loadAll}
            />
          ) : null}
          {step === 'gradebook' ? (
            <GradebookStep
              gradebook={gradebook}
              activeCurve={activeCurve}
              courseId={courseId}
              setToast={setToast}
              refresh={loadAll}
            />
          ) : null}
          {step === 'settings' ? (
            <SettingsStep course={course} setToast={setToast} onSaved={loadAll} />
          ) : null}
        </div>
      </div>

      {toast ? (
        <div
          className="fixed bottom-6 right-6 z-50 rounded-full bg-ink px-4 py-2.5 text-[13px] text-paper shadow-lift"
          role="status"
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}

/* =============== Sidebar =============== */

function Sidebar({
  course,
  graded,
  total,
  remaining,
  step,
  setStep,
  counts
}: {
  course: Course;
  graded: number;
  total: number;
  remaining: number;
  step: StepKey;
  setStep: (s: StepKey) => void;
  counts: Record<StepKey, number | null>;
}) {
  return (
    <aside className="sticky top-0 flex h-screen flex-col gap-1 overflow-y-auto border-r border-border bg-paper-2 px-[18px] py-6">
      <Link href="/" className="mb-2 flex items-center gap-2.5 border-b border-border px-2 pb-4 pt-1 no-underline">
        <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-forest font-display text-[18px] tracking-tight text-paper">
          cg
        </span>
        <span className="font-display text-[18px] tracking-tight text-ink">course-grader</span>
      </Link>

      {/* Course progress block */}
      <div className="border-b border-border px-2 pb-4 pt-2.5">
        <div className="label-eyebrow mb-1">
          {course.code} · {course.year} / {course.semester}
        </div>
        <div className="mb-3 font-display text-[17px] leading-tight">{course.name}</div>
        <div className="mb-2 flex items-center gap-2.5">
          <ProgressRing value={graded} max={Math.max(total, 1)} size={42} stroke={4} />
          <div>
            <div className="font-display text-base leading-tight">
              {graded} <span className="text-ink-3">of {total}</span>
            </div>
            <div className="text-[11px] text-ink-3">graded</div>
          </div>
        </div>
        {total === 0 ? null : remaining > 0 ? (
          <div className="flex items-center gap-1.5 text-[12px] text-terracotta">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-terracotta" />
            {remaining} left to review
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-[12px] text-ok">
            ✓ All caught up
          </div>
        )}
      </div>

      {/* Steps */}
      {STEPS.map((s, i) => (
        <button
          key={s.key}
          className={`nav-step ${step === s.key ? 'active' : ''}`}
          onClick={() => setStep(s.key)}
        >
          <span className="nav-num">{i + 1}</span>
          <span className="text-[15px]" aria-hidden>
            {s.icon}
          </span>
          <span className="nav-label">{s.label}</span>
          {counts[s.key] != null && counts[s.key]! > 0 ? (
            <span className="nav-count tnum">{counts[s.key]}</span>
          ) : null}
        </button>
      ))}

      <div className="mt-auto border-t border-border px-2 pt-3 text-[11px] text-ink-4">
        Localhost · No auth needed
      </div>
    </aside>
  );
}

/* =============== Helpers =============== */

type RunState = 'unrun' | 'queued' | 'in_progress' | 'graded' | 'failed';

function derivedState(s: Submission): RunState {
  const status = (s.last_run_status || '').toLowerCase();
  if (status === 'queued' || status === 'pending') return 'queued';
  if (status === 'running' || status === 'in_progress') return 'in_progress';
  if (status === 'failed' || status === 'error') return 'failed';
  if (status === 'completed' || status === 'success') {
    return s.rubric_filled > 0 ? 'graded' : 'in_progress';
  }
  return 'unrun';
}

const STATE_PILL: Record<RunState, { tone: string; label: string }> = {
  unrun: { tone: '', label: 'Not run yet' },
  queued: { tone: 'pill-info', label: 'Queued' },
  in_progress: { tone: 'pill-forest', label: 'In progress' },
  graded: { tone: 'pill-ok', label: 'Graded' },
  failed: { tone: 'pill-bad', label: 'Failed' }
};

function StatePill({ state }: { state: RunState }) {
  const cfg = STATE_PILL[state];
  return <span className={`pill ${cfg.tone}`}>{cfg.label}</span>;
}

function splitName(raw: string): { he?: string; en?: string } {
  const parts = (raw || '').split(/\s*\/\s*|\s*\|\s*/);
  if (parts.length === 2) {
    const [a, b] = parts;
    return isHebrew(a) ? { he: a, en: b } : { he: b, en: a };
  }
  return isHebrew(raw) ? { he: raw } : { en: raw };
}

/* =============== Queue Step =============== */

function AssignmentRequirementsSummary({
  assignments,
  submissions,
  active,
  onSelect
}: {
  assignments: Assignment[];
  submissions: Submission[];
  active: string;
  onSelect: (id: string) => void;
}) {
  if (assignments.length === 0) return null;
  const stats = assignments.map((a) => {
    const rows = submissions.filter((s) => s.assignment_id === a.id);
    const reqs = rows.map((s) => s.requirements).filter((r): r is SubmissionRequirements => !!r);
    const complete = reqs.filter((r) => r.complete).length;
    const manuallyGraded = reqs.filter((r) => r.overridden_by_manual_grade).length;
    // Don't count files-missing for submissions the grader has overridden — they're done.
    const missingPdf = reqs.filter((r) => !r.overridden_by_manual_grade && r.needs_pdf && !r.has_pdf).length;
    const missingColab = reqs.filter((r) => !r.overridden_by_manual_grade && r.needs_colab && !r.has_colab_url).length;
    const needs = reqs[0]
      ? [reqs[0].needs_pdf ? 'PDF' : null, reqs[0].needs_colab ? 'Colab URL' : null].filter(Boolean).join(' + ')
      : '—';
    return {
      ...a,
      total: rows.length,
      complete,
      manuallyGraded,
      missingPdf,
      missingColab,
      needs
    };
  });

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {stats.map((s) => {
        const idStr = String(s.id);
        const isActive = active === idStr;
        const pct = s.total > 0 ? Math.round((s.complete / s.total) * 100) : 0;
        return (
          <button
            key={s.id}
            onClick={() => onSelect(isActive ? 'all' : idStr)}
            className={`rounded-lg border bg-card p-4 text-left transition shadow-soft ${
              isActive ? 'border-forest ring-1 ring-forest-soft' : 'border-border hover:border-ink-4'
            }`}
            title={isActive ? 'Click to clear filter' : `Filter to ${s.assignment_type}`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <div className="min-w-0">
                <div className="font-display text-[15px] text-ink truncate">
                  {s.assignment_type} <span className="text-ink-3">· {s.name}</span>
                </div>
                <div className="text-[12px] text-ink-3">requires {s.needs}</div>
              </div>
              <div className="tnum shrink-0 text-right">
                <div className="font-display text-lg leading-none">
                  {s.complete}
                  <span className="text-ink-3">/{s.total}</span>
                </div>
                <div className="text-[10px] uppercase tracking-wider text-ink-3">complete</div>
              </div>
            </div>
            <div className="mt-2.5 progress-bar">
              <span style={{ width: `${pct}%` }} />
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
              {s.missingPdf > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-px text-warn">
                  ⚠ {s.missingPdf} missing PDF
                </span>
              ) : null}
              {s.missingColab > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-px text-warn">
                  ⚠ {s.missingColab} missing Colab URL
                </span>
              ) : null}
              {s.manuallyGraded > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-forest-tint px-2 py-px text-forest">
                  ✓ {s.manuallyGraded} manually graded
                </span>
              ) : null}
              {s.missingPdf === 0 && s.missingColab === 0 && s.total > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2 py-px text-ok">
                  ✓ All required files in
                </span>
              ) : null}
            </div>
          </button>
        );
      })}
    </div>
  );
}

function QueueStep({
  submissions,
  assignments,
  courseId,
  setToast,
  refresh
}: {
  submissions: Submission[];
  assignments: Assignment[];
  courseId: number;
  setToast: (s: string) => void;
  refresh: () => Promise<void>;
}) {
  const [filter, setFilter] = useState<'all' | RunState | 'flagged' | 'incomplete'>('all');
  const [search, setSearch] = useState('');
  const [assignmentFilter, setAssignmentFilter] = useState<string>('all');
  const [pasteOpen, setPasteOpen] = useState<number | null>(null);
  const [pasteUrl, setPasteUrl] = useState('');

  const filtered = useMemo(() => {
    let rows = submissions;
    if (filter === 'flagged') rows = rows.filter((s) => s.originality_mismatch);
    else if (filter === 'incomplete') rows = rows.filter((s) => s.requirements && !s.requirements.complete);
    else if (filter !== 'all') rows = rows.filter((s) => derivedState(s) === filter);
    if (assignmentFilter !== 'all') rows = rows.filter((s) => String(s.assignment_id) === assignmentFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (s) =>
          s.member_names.some((n) => n.toLowerCase().includes(q) || n.includes(search)) ||
          s.member_ids.some((id) => id.includes(q)) ||
          String(s.id).includes(q)
      );
    }
    return rows;
  }, [submissions, filter, assignmentFilter, search]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {
      all: submissions.length,
      unrun: 0,
      queued: 0,
      in_progress: 0,
      graded: 0,
      flagged: 0,
      incomplete: 0
    };
    for (const s of submissions) {
      c[derivedState(s)] = (c[derivedState(s)] ?? 0) + 1;
      if (s.originality_mismatch) c.flagged += 1;
      if (s.requirements && !s.requirements.complete) c.incomplete += 1;
    }
    return c;
  }, [submissions]);

  const sortedAssignments = useMemo(
    () => [...assignments].sort((a, b) => a.assignment_type.localeCompare(b.assignment_type) || a.workcode - b.workcode),
    [assignments]
  );

  const FILTERS: { key: typeof filter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'incomplete', label: 'Missing files' },
    { key: 'unrun', label: 'Not run' },
    { key: 'queued', label: 'Queued' },
    { key: 'in_progress', label: 'In progress' },
    { key: 'graded', label: 'Done' },
    { key: 'flagged', label: 'Flagged' }
  ];

  const groupNumberOf = (s: Submission, list: Submission[]) =>
    list
      .filter((x) => x.assignment_id === s.assignment_id)
      .findIndex((x) => x.id === s.id) + 1;

  const submitColab = async (submissionId: number) => {
    if (!pasteUrl.trim()) return;
    await apiPost(`/api/submissions/${submissionId}/snapshot`, { url: pasteUrl.trim() });
    setPasteOpen(null);
    setPasteUrl('');
    setToast('Snapshot queued');
    await refresh();
  };

  const queueRun = async (submissionId: number, mode: 'snapshot' | 'latest') => {
    await apiPost(`/api/submissions/${submissionId}/runs`, { mode });
    setToast(`Run queued (${mode})`);
    await refresh();
  };

  return (
    <div className="pt-6 space-y-4">
      <div className="hint">
        <span className="hint-icon">i</span>
        <div>
          One row per group submission. <strong className="text-ink">Open</strong> takes you into the review workspace
          where the executed notebook + report live alongside the rubric. Use the filter chips to narrow down —{' '}
          <strong className="text-ink">Not run</strong> shows what's missing a Colab URL,{' '}
          <strong className="text-ink">Flagged</strong> shows originality mismatches.
        </div>
      </div>

      {/* Per-assignment requirements summary */}
      <AssignmentRequirementsSummary
        assignments={sortedAssignments}
        submissions={submissions}
        active={assignmentFilter}
        onSelect={(id) => setAssignmentFilter(id)}
      />

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => {
          const active = filter === f.key;
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[13px] transition ${
                active
                  ? 'bg-forest text-paper'
                  : 'border border-border bg-card text-ink-2 hover:border-ink-4 hover:text-ink'
              }`}
            >
              {f.label}
              <span className={`tnum text-[12px] ${active ? 'opacity-70' : 'text-ink-3'}`}>
                {counts[f.key] ?? 0}
              </span>
            </button>
          );
        })}
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3">⌕</span>
            <Input
              className="w-[260px] pl-8"
              placeholder="Search by name or ID"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            className="h-10 max-w-[260px] rounded-md border border-border bg-card px-3 text-[13px]"
            value={assignmentFilter}
            onChange={(e) => setAssignmentFilter(e.target.value)}
          >
            <option value="all">All assignments</option>
            {sortedAssignments.map((a) => (
              <option key={a.id} value={String(a.id)}>
                {a.assignment_type} · {a.name} ({a.submission_count})
              </option>
            ))}
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <Card>
          <div className="grid place-items-center gap-2 px-6 py-10 text-center">
            <div className="font-display text-lg">Nothing matches that view</div>
            <div className="max-w-sm text-sm text-ink-3">
              Try a different filter, or clear the search to see everything in the queue.
            </div>
          </div>
        </Card>
      ) : (
        <div className="grid gap-2.5">
          {filtered.map((s) => (
            <SubmissionCard
              key={s.id}
              submission={s}
              groupNumber={groupNumberOf(s, submissions)}
              courseId={courseId}
              onPasteOpen={() => {
                setPasteOpen(s.id);
                setPasteUrl('');
              }}
              onQueueRun={(mode) => queueRun(s.id, mode)}
              pasteOpen={pasteOpen === s.id}
              pasteUrl={pasteUrl}
              setPasteUrl={setPasteUrl}
              onPasteSubmit={() => submitColab(s.id)}
              onPasteCancel={() => setPasteOpen(null)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SubmissionCard({
  submission: s,
  groupNumber,
  courseId,
  onPasteOpen,
  onQueueRun,
  pasteOpen,
  pasteUrl,
  setPasteUrl,
  onPasteSubmit,
  onPasteCancel
}: {
  submission: Submission;
  groupNumber: number;
  courseId: number;
  onPasteOpen: () => void;
  onQueueRun: (mode: 'snapshot' | 'latest') => void;
  pasteOpen: boolean;
  pasteUrl: string;
  setPasteUrl: (v: string) => void;
  onPasteSubmit: () => void;
  onPasteCancel: () => void;
}) {
  const state = derivedState(s);
  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-soft">
      <div
        className="grid items-center gap-4"
        style={{ gridTemplateColumns: '160px minmax(0, 1fr) 200px 220px' }}
      >
        {/* Left */}
        <div>
          <div className="font-display text-[15px] leading-tight">
            {s.assignment_type} <span className="text-ink-3">· G{groupNumber}</span>
          </div>
          <div className="mt-0.5 text-xs text-ink-3">
            WC{s.workcode} · #{s.id}
          </div>
        </div>

        {/* Members */}
        <div className="flex min-w-0 items-center gap-3">
          <AvatarStack names={s.member_names} max={3} size={28} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap gap-x-2.5 gap-y-1">
              {s.member_names.slice(0, 4).map((n, i) => {
                const { he, en } = splitName(n);
                return (
                  <span key={i} className="inline-flex items-baseline gap-1.5 whitespace-nowrap text-[13px]">
                    {he ? <span className="he-name">{he}</span> : null}
                    {en ? <span className="text-ink-3" style={{ fontSize: 12 }}>{en}</span> : null}
                    {!he && !en ? <BilingualName name={n} /> : null}
                  </span>
                );
              })}
              {s.member_names.length > 4 ? (
                <span className="text-xs text-ink-3">+{s.member_names.length - 4}</span>
              ) : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {s.requirements?.overridden_by_manual_grade ? (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-forest-tint px-2 py-px text-[11px] text-forest"
                  title="Grader entered a manual grade — requirements bypassed"
                >
                  ✓ Manually graded
                </span>
              ) : s.requirements && !s.requirements.complete ? (
                s.requirements.missing.map((m) => (
                  <span
                    key={m}
                    className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-px text-[11px] text-warn"
                    title={`This ${s.assignment_type} submission is missing ${m}`}
                  >
                    ⚠ Missing {m}
                  </span>
                ))
              ) : null}
              {s.originality_mismatch ? (
                <span className="inline-flex items-center gap-1 text-[12px] text-bad">
                  ⚑ Originality mismatch
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {/* State */}
        <div>
          <StatePill state={state} />
          {s.last_run_ratio != null ? (
            <div className="mt-1.5 text-[12px] text-ink-3">
              ran <span className="tnum text-ink-2">{Math.round(s.last_run_ratio * 100)}%</span> of cells
            </div>
          ) : !s.has_colab_url ? (
            <div className="mt-1.5 text-[12px] text-ink-3">no Colab URL</div>
          ) : (
            <div className="mt-1.5 text-[12px] text-ink-3">ready to run</div>
          )}
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-1.5">
          {state === 'unrun' && !s.has_colab_url ? (
            <Button variant="soft" size="sm" onClick={onPasteOpen}>
              Add URL
            </Button>
          ) : state === 'unrun' ? (
            <Button variant="soft" size="sm" onClick={() => onQueueRun('snapshot')}>
              ▶ Run
            </Button>
          ) : null}
          <Link
            href={`/course/${courseId}/submission/${s.id}`}
            className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md bg-forest px-2.5 py-1 text-[13px] font-medium text-paper transition hover:bg-[#244c41]"
          >
            {state === 'graded' ? 'Review' : 'Open'} →
          </Link>
        </div>
      </div>

      {pasteOpen ? (
        <div className="mt-3 grid gap-2 border-t border-border pt-3" style={{ gridTemplateColumns: '1fr auto auto' }}>
          <Input
            placeholder="Paste Colab URL"
            value={pasteUrl}
            onChange={(e) => setPasteUrl(e.target.value)}
            autoFocus
          />
          <Button size="sm" onClick={onPasteSubmit}>
            Fetch snapshot
          </Button>
          <Button variant="ghost" size="sm" onClick={onPasteCancel}>
            Cancel
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/* =============== Imports Step =============== */

function ImportsStep({
  courseId,
  assignments,
  setToast,
  refresh
}: {
  courseId: number;
  assignments: Assignment[];
  setToast: (m: string) => void;
  refresh: () => Promise<void>;
}) {
  const [rosterFile, setRosterFile] = useState<File | null>(null);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [presFile, setPresFile] = useState<File | null>(null);
  const [zipForm, setZipForm] = useState({ assignment_type: 'PROJECT', workcode: 1, assignment_name: '' });

  const upload = async (
    e: FormEvent,
    file: File | null,
    path: string,
    extra?: Record<string, string>
  ) => {
    e.preventDefault();
    if (!file) return;
    const fd = new FormData();
    try {
      const target = await apiPost<UploadTarget>(`/api/courses/${courseId}/imports/upload-url`, { filename: file.name });
      if (target.direct) fd.append('storage_key', await putToStorage(target, file));
      else fd.append('file', file);
    } catch (err) {
      setToast(`Upload failed: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    if (extra) for (const [k, v] of Object.entries(extra)) fd.append(k, v);
    const res = await apiFetch(path, { method: 'POST', body: fd });
    if (!res.ok) {
      setToast(`Upload failed: ${await res.text()}`);
      return;
    }
    setToast('Uploaded');
    await refresh();
  };

  const startOAuth = async () => {
    try {
      const r = await apiGet<{ authorization_url: string }>(`/api/oauth/google/start`);
      window.open(r.authorization_url, '_blank');
      setToast('Google OAuth opened in new tab');
    } catch (e) {
      setToast(`OAuth failed: ${(e as Error).message}`);
    }
  };

  return (
    <div className="grid gap-3.5 pt-6">
      <div className="hint hint-warm">
        <span className="hint-icon">1</span>
        <div>
          Start here at the beginning of the term. Upload the <strong className="text-ink">roster</strong> first (so
          attendance and group membership work), then assignment <strong className="text-ink">ZIPs</strong> as students
          submit. The presentation sheet comes last, after talks. Re-uploading replaces the previous import.
        </div>
      </div>

      {/* Roster */}
      <ImportTile icon="👥" title="Roster" sub="XLSX with תעודת זהות + שם columns. Attendance is computed per session.">
        <form onSubmit={(e) => upload(e, rosterFile, `/api/courses/${courseId}/imports/roster`)} className="flex items-center gap-2">
          <input type="file" accept=".xlsx" onChange={(e) => setRosterFile(e.target.files?.[0] ?? null)} className="text-xs" />
          <Button type="submit" size="sm">Upload roster</Button>
        </form>
      </ImportTile>
      <RosterCard courseId={courseId} setToast={setToast} refresh={refresh} />

      {/* ZIP */}
      <ImportTile
        icon="⤴"
        title="Assignment ZIP"
        sub={`Filenames like ID_<id1>+ID_<id2>+..._WorkCode_<n>.<ext> are parsed automatically. ${assignments.length} assignment${assignments.length === 1 ? '' : 's'} loaded.`}
      >
        <form
          onSubmit={(e) =>
            upload(e, zipFile, `/api/courses/${courseId}/imports/submissions-zip`, {
              assignment_type: zipForm.assignment_type,
              workcode: String(zipForm.workcode),
              assignment_name: zipForm.assignment_name
            })
          }
          className="grid gap-2"
        >
          <input type="file" accept=".zip" onChange={(e) => setZipFile(e.target.files?.[0] ?? null)} className="text-xs" />
          <div className="grid grid-cols-3 gap-2">
            <select
              className="h-9 rounded-md border border-border bg-card px-2 text-[13px]"
              value={zipForm.assignment_type}
              onChange={(e) => setZipForm({ ...zipForm, assignment_type: e.target.value })}
            >
              <option>HW1</option>
              <option>HW2</option>
              <option>PROJECT</option>
            </select>
            <Input
              type="number"
              value={zipForm.workcode}
              onChange={(e) => setZipForm({ ...zipForm, workcode: Number(e.target.value) })}
              placeholder="WorkCode"
              className="h-9"
            />
            <Input
              value={zipForm.assignment_name}
              onChange={(e) => setZipForm({ ...zipForm, assignment_name: e.target.value })}
              placeholder="Assignment name"
              className="h-9"
            />
          </div>
          <div className="flex justify-end">
            <Button type="submit" size="sm">Upload ZIP</Button>
          </div>
        </form>
      </ImportTile>

      {/* Presentations */}
      <ImportTile icon="🎤" title="Presentations sheet" sub="Two-sheet XLSX with presentation + final talk scores per group, in Hebrew.">
        <form onSubmit={(e) => upload(e, presFile, `/api/courses/${courseId}/imports/presentations`)} className="flex items-center gap-2">
          <input type="file" accept=".xlsx" onChange={(e) => setPresFile(e.target.files?.[0] ?? null)} className="text-xs" />
          <Button type="submit" size="sm">Upload presentations</Button>
        </form>
      </ImportTile>

      {/* Google */}
      <Card className="bg-paper-2">
        <div className="flex items-center gap-3">
          <span className="text-lg">🌐</span>
          <div className="flex-1">
            <div className="font-display text-base">Google Drive (for private Colabs)</div>
            <div className="text-[13px] text-ink-3">
              Connect once to fetch private notebook snapshots automatically.
            </div>
          </div>
          <Button variant="soft" size="sm" onClick={startOAuth}>
            Connect Google
          </Button>
        </div>
      </Card>
    </div>
  );
}

function ImportTile({
  icon,
  title,
  sub,
  children
}: {
  icon: string;
  title: string;
  sub: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <div className="grid items-center gap-4" style={{ gridTemplateColumns: '52px 1fr 280px' }}>
        <div className="grid h-11 w-11 place-items-center rounded-xl bg-terracotta-tint text-xl text-terracotta">
          {icon}
        </div>
        <div>
          <div className="font-display text-lg">{title}</div>
          <div className="text-[13px] leading-relaxed text-ink-3">{sub}</div>
        </div>
        <div>{children}</div>
      </div>
    </Card>
  );
}

/* =============== Curve Step =============== */

function CurveStep({
  courseId,
  course,
  activeCurve,
  dimensionDistributions,
  gradebook,
  setToast,
  refresh
}: {
  courseId: number;
  course: Course;
  activeCurve: ActiveCurve | null;
  dimensionDistributions: Record<string, number[]>;
  gradebook: GradebookRow[];
  setToast: (m: string) => void;
  refresh: () => Promise<void>;
}) {
  const [threshold, setThreshold] = useState(course.attendance_threshold);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [targetMean, setTargetMean] = useState(83);
  const [targetSigma, setTargetSigma] = useState(12);

  useEffect(() => {
    if (!activeCurve) return;
    const d: Record<string, string> = {};
    for (const [k, v] of Object.entries(activeCurve.mapping))
      d[k] = v.points.map((p) => Number(p.toFixed(2)).toString()).join(', ');
    setDraft(d);
  }, [activeCurve]);

  const updateThreshold = async () => {
    await apiPatch(`/api/courses/${courseId}/attendance-threshold`, { threshold });
    setToast('Attendance threshold updated');
    await refresh();
  };
  const autoThreshold = async () => {
    await apiPost(`/api/courses/${courseId}/attendance/threshold-for-25-fail`);
    setToast('Threshold set so ≤25% fail');
    await refresh();
  };
  const calibrate = async () => {
    const res = await apiPost<{ note: string }>(
      `/api/courses/${courseId}/curves/calibrate-mean-83?target_mean=${targetMean}&target_sigma=${targetSigma}`
    );
    setToast(res?.note ?? `Calibrated to mean ${targetMean}`);
    await refresh();
  };
  const undoCurve = async () => {
    try {
      await apiPost(`/api/courses/${courseId}/curves/undo`);
      setToast('Reverted to previous revision');
      await refresh();
    } catch (e) {
      setToast(`Undo failed: ${(e as Error).message}`);
    }
  };
  const saveCurve = async () => {
    if (!activeCurve) return;
    const mapping: Record<string, CurvePoints> = {};
    for (const [k, raw] of Object.entries(draft)) {
      const points = raw.split(',').map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n));
      if (points.length !== 6) {
        setToast(`${k} needs exactly 6 points`);
        return;
      }
      mapping[k] = { points, tunable: activeCurve.mapping[k]?.tunable ?? true };
    }
    await apiPost(`/api/courses/${courseId}/curves/revision`, {
      mapping,
      note: `Manual edit · ${new Date().toISOString()}`
    });
    setToast('Curve revision saved');
    await refresh();
  };

  return (
    <div className="grid gap-4 pt-6">
      <DistributionPanel rows={gradebook} activeCurve={activeCurve} />

      <div className="hint">
        <span className="hint-icon">i</span>
        <div>
          Tune two things here: the <strong className="text-ink">attendance threshold</strong> (one number per course)
          and the <strong className="text-ink">rubric curve</strong> (six points per dimension that map raw 0–5 scores
          to 0–5 adjusted). <em>Fit grades to N(μ,σ)</em> binary-searches a single-parameter constant-Δslope curve
          (shared across tunable dimensions, fixed at f(0)=0 and f(5)=5) and adds a uniform bonus only when the curves
          alone can't reach the target. Every save creates a new revision; <em>Undo</em> reverts.
        </div>
      </div>

      {/* Attendance */}
      <Card>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <div>
            <div className="font-display text-[19px]">Attendance threshold</div>
            <div className="text-[13px] text-ink-3">Students below this fail attendance unless exempt.</div>
          </div>
          <Button variant="ghost" size="sm" onClick={autoThreshold}>
            ✦ Auto: keep ≤25% failing
          </Button>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="number"
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="h-12 w-[100px] rounded-md border border-border bg-card text-center font-display text-2xl"
          />
          <span className="font-display text-lg text-ink-3">%</span>
          <div className="flex-1" />
          <Button size="sm" onClick={updateThreshold}>
            Save threshold
          </Button>
        </div>
      </Card>

      {/* Curve */}
      <Card>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <div>
            <div className="font-display text-[19px]">Rubric curve</div>
            {activeCurve ? (
              <div className="text-[13px] text-ink-3">
                Active revision <span className="tnum">#{activeCurve.revision_number}</span> · {activeCurve.note}
              </div>
            ) : (
              <div className="text-[13px] text-ink-3">No curve loaded.</div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={undoCurve}>Undo</Button>
            <span className="text-[12px] text-ink-3">μ</span>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={targetMean}
              onChange={(e) => setTargetMean(Number(e.target.value))}
              className="h-8 w-[64px] rounded-md border border-border bg-card px-2 text-center font-mono text-[13px]"
              aria-label="Target mean"
            />
            <span className="text-[12px] text-ink-3">σ</span>
            <input
              type="number"
              min={1}
              max={40}
              step={1}
              value={targetSigma}
              onChange={(e) => setTargetSigma(Number(e.target.value))}
              className="h-8 w-[56px] rounded-md border border-border bg-card px-2 text-center font-mono text-[13px]"
              aria-label="Target sigma"
            />
            <Button variant="soft" size="sm" onClick={calibrate}>✦ Fit grades to N(μ,σ)</Button>
          </div>
        </div>

        {activeCurve ? (
          <>
            <div className="grid gap-2.5">
              {Object.entries(activeCurve.mapping).map(([k, v]) => (
                <div
                  key={k}
                  className="grid items-center gap-3.5"
                  style={{ gridTemplateColumns: '180px 1fr 240px' }}
                >
                  <div>
                    <div className="text-[13px] text-ink">{k.split(':')[0].replace(/_/g, ' ')}</div>
                    <div className="text-[11px] text-ink-3">{v.tunable ? 'Tunable' : 'Locked'}</div>
                  </div>
                  <Sparkline points={v.points} distribution={dimensionDistributions[k]} />
                  <Input
                    className="font-mono text-[12px]"
                    disabled={!v.tunable}
                    value={draft[k] ?? ''}
                    onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                  />
                </div>
              ))}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button onClick={saveCurve}>Save curve revision</Button>
            </div>
          </>
        ) : null}
      </Card>
    </div>
  );
}

function Sparkline({ points, distribution }: { points: number[]; distribution?: number[] }) {
  const w = 220;
  const h = 48;
  const pad = 4;
  const innerW = w - 2 * pad;
  const innerH = h - 2 * pad;
  const xAt = (i: number) => pad + (i / (points.length - 1)) * innerW;
  const yAt = (score: number) => pad + innerH - (Math.max(0, Math.min(5, score)) / 5) * innerH;
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xAt(i).toFixed(1)} ${yAt(p).toFixed(1)}`).join(' ');

  const counts = [0, 0, 0, 0, 0, 0];
  if (distribution && distribution.length > 0) {
    for (const v of distribution) {
      const idx = Math.max(0, Math.min(5, Math.round(v)));
      counts[idx]++;
    }
  }
  const maxCount = Math.max(...counts, 1);
  const barWidth = Math.min(22, (innerW / 6) * 0.75);

  return (
    <svg width={w} height={h} className="block">
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="var(--line)" />
      {distribution && distribution.length > 0
        ? counts.map((c, i) => {
            const cx = pad + (i / 5) * innerW;
            const barH = (c / maxCount) * innerH;
            return (
              <rect
                key={`b${i}`}
                x={cx - barWidth / 2}
                y={pad + innerH - barH}
                width={barWidth}
                height={barH}
                fill="var(--forest)"
                opacity={0.18}
              />
            );
          })
        : null}
      <path d={path} stroke="var(--forest)" strokeWidth="2" fill="none" strokeLinecap="round" />
      {points.map((p, i) => (
        <circle key={i} cx={xAt(i)} cy={yAt(p)} r="2.2" fill="var(--forest)" />
      ))}
    </svg>
  );
}

/* =============== Overrides Step =============== */

function OverridesStep({
  courseId,
  gradebook,
  overrides,
  setToast,
  refresh
}: {
  courseId: number;
  gradebook: GradebookRow[];
  overrides: OverrideRow[];
  setToast: (m: string) => void;
  refresh: () => Promise<void>;
}) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ student_id: '', component: 'bonus', delta: '0', reason: '' });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const delta = Number(form.delta);
    if (!form.student_id || !form.reason.trim() || Number.isNaN(delta)) {
      setToast('Need student, delta, and reason');
      return;
    }
    await apiPost(`/api/courses/${courseId}/overrides`, {
      student_id: Number(form.student_id),
      component: form.component,
      delta,
      reason: form.reason
    });
    setShowForm(false);
    setForm({ student_id: '', component: 'bonus', delta: '0', reason: '' });
    setToast('Override added');
    await refresh();
  };
  const remove = async (id: number) => {
    const res = await apiFetch(`/api/courses/${courseId}/overrides/${id}`, { method: 'DELETE' });
    if (!res.ok) {
      setToast('Delete failed');
      return;
    }
    setToast('Override removed');
    await refresh();
  };

  return (
    <div className="grid gap-3.5 pt-6">
      <div className="hint">
        <span className="hint-icon">i</span>
        <div>
          Use overrides for one-off adjustments that don't fit the rubric — bonus for studio help, late penalties, IDF
          reserve exemption, etc. The <strong className="text-ink">delta</strong> is added to the chosen component{' '}
          <em>after</em> the curve. The <strong className="text-ink">reason</strong> is required and appears in your
          audit log; it's never shown to the student. The gradebook's <strong className="text-ink">Bonus</strong> column
          is the sum of all <code>bonus</code> overrides — this is the only way to give a project bonus.
        </div>
      </div>
      <div className="flex items-baseline justify-between">
        <div className="text-[13px] text-ink-3">
          Per-student deltas applied after the curve. Reason is required.
        </div>
        <Button variant="soft" size="sm" onClick={() => setShowForm(true)}>
          + Add override
        </Button>
      </div>

      {showForm ? (
        <form onSubmit={submit} className="rounded-lg border border-forest bg-card p-[22px] shadow-card">
          <div className="grid grid-cols-[1fr_160px_100px_1fr] gap-2.5">
            <div>
              <Label>Student</Label>
              <select
                className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm"
                required
                value={form.student_id}
                onChange={(e) => setForm({ ...form, student_id: e.target.value })}
              >
                <option value="">Choose student…</option>
                {gradebook.map((g) => (
                  <option key={g.student_id} value={g.student_id}>
                    {g.name} · {g.national_id}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>Component</Label>
              <select
                className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm"
                value={form.component}
                onChange={(e) => setForm({ ...form, component: e.target.value })}
              >
                {['hw1', 'hw2', 'project_code', 'project_report', 'presentation', 'final_talk', 'attendance', 'bonus'].map(
                  (c) => (
                    <option key={c}>{c}</option>
                  )
                )}
              </select>
            </div>
            <div>
              <Label>Delta</Label>
              <Input
                type="number"
                step="0.5"
                value={form.delta}
                onChange={(e) => setForm({ ...form, delta: e.target.value })}
              />
            </div>
            <div>
              <Label>Reason</Label>
              <Input
                required
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                placeholder="e.g. helped peer debug pipeline"
              />
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setShowForm(false)}>
              Cancel
            </Button>
            <Button size="sm" type="submit">
              Save override
            </Button>
          </div>
        </form>
      ) : null}

      {overrides.length === 0 ? (
        <Card>
          <div className="grid place-items-center gap-2 py-8 text-center">
            <div className="font-display text-lg">No overrides yet</div>
            <div className="max-w-sm text-sm text-ink-3">
              Add an override when a student needs a per-component adjustment with a reason on file.
            </div>
          </div>
        </Card>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-card shadow-soft">
          {overrides.map((o, i) => (
            <div
              key={o.id}
              className="grid items-center gap-4 px-5 py-3.5"
              style={{
                gridTemplateColumns: '1fr 130px 100px 2fr auto',
                borderBottom: i < overrides.length - 1 ? '1px solid var(--line-soft)' : 'none'
              }}
            >
              <div className="flex items-center gap-2.5">
                <Avatar name={o.student_name ?? '—'} size={28} />
                <div>
                  <BilingualName name={o.student_name ?? '—'} />
                  <div className="text-[11px] text-ink-3">{o.student_national_id}</div>
                </div>
              </div>
              <span className="pill pill-forest">{o.component}</span>
              <div
                className="font-display tnum text-lg"
                style={{ color: o.delta > 0 ? 'var(--ok)' : o.delta < 0 ? 'var(--bad)' : 'var(--ink-3)' }}
              >
                {o.delta > 0 ? '+' : ''}
                {o.delta}
              </div>
              <div className="text-[13px] leading-snug text-ink-2">
                <span className="italic">"{o.reason}"</span>
                <div className="mt-0.5 text-[11px] text-ink-3">{new Date(o.created_at).toLocaleDateString()}</div>
              </div>
              <button onClick={() => remove(o.id)} className="text-[13px] text-forest hover:underline">
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* =============== Gradebook Step =============== */

type TaskStatus = { task_id: string; state: string; payload: Record<string, unknown> };
type ReportsExport =
  | { taskId: string; state: 'running' }
  | { taskId: string; state: 'done'; count: number }
  | { taskId: string; state: 'failed'; error: string };

function GradebookStep({
  gradebook,
  activeCurve,
  courseId,
  setToast,
  refresh
}: {
  gradebook: GradebookRow[];
  activeCurve: ActiveCurve | null;
  courseId: number;
  setToast: (m: string) => void;
  refresh: () => Promise<void>;
}) {
  const [sort, setSort] = useState<'name' | 'final' | 'attendance'>('name');
  const [reportsExport, setReportsExport] = useState<ReportsExport | null>(null);

  // Poll the queued Hebrew-PDF export until the worker finishes or fails.
  useEffect(() => {
    if (reportsExport?.state !== 'running') return;
    const taskId = reportsExport.taskId;
    const timer = setInterval(async () => {
      try {
        const task = await apiGet<TaskStatus>(`/api/tasks/${taskId}`);
        if (task.state === 'SUCCESS') {
          setReportsExport({ taskId, state: 'done', count: Number(task.payload.report_count ?? 0) });
        } else if (task.state === 'FAILURE') {
          setReportsExport({ taskId, state: 'failed', error: String(task.payload.error ?? 'failed') });
        }
      } catch {
        /* transient; keep polling */
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [reportsExport?.state, reportsExport?.taskId]);

  const sorted = useMemo(() => {
    const arr = [...gradebook];
    if (sort === 'final') arr.sort((a, b) => b.final - a.final);
    else if (sort === 'attendance')
      arr.sort((a, b) => (b.attendance_percent ?? 0) - (a.attendance_percent ?? 0));
    else arr.sort((a, b) => a.name.localeCompare(b.name));
    return arr;
  }, [gradebook, sort]);

  const finals = gradebook.map((g) => g.final).filter((v): v is number => Number.isFinite(v));
  const mean = finals.length ? (finals.reduce((a, b) => a + b, 0) / finals.length).toFixed(1) : '—';
  const median = finals.length ? finals.slice().sort((a, b) => a - b)[Math.floor(finals.length / 2)] : '—';
  const std = stdDev(finals);
  const stdLabel = std !== null ? std.toFixed(1) : '—';
  const passing = gradebook.filter((g) => Number.isFinite(g.final) && g.final >= 60).length;

  const finalsRaw = gradebook
    .map((g) => g.final_uncurved)
    .filter((v): v is number => Number.isFinite(v));
  const meanRaw = finalsRaw.length
    ? (finalsRaw.reduce((a, b) => a + b, 0) / finalsRaw.length).toFixed(1)
    : '—';
  const medianRaw = finalsRaw.length
    ? finalsRaw.slice().sort((a, b) => a - b)[Math.floor(finalsRaw.length / 2)]
    : '—';
  const stdRaw = stdDev(finalsRaw);
  const stdRawLabel = stdRaw !== null ? stdRaw.toFixed(1) : '—';
  const passingRaw = gradebook.filter(
    (g) => Number.isFinite(g.final_uncurved) && g.final_uncurved >= 60
  ).length;

  const toggleExempt = async (enrollmentId: number, current: boolean) => {
    await apiPatch(`/api/courses/${courseId}/enrollments/${enrollmentId}/attendance-exempt`, {
      attendance_exempt: !current
    });
    await refresh();
  };

  const triggerExport = async () => {
    const res = await apiPost<{ task_id: string }>(`/api/courses/${courseId}/exports/student-reports?async_job=true`);
    setReportsExport({ taskId: res.task_id, state: 'running' });
    setToast('Student reports queued');
  };

  return (
    <div className="grid gap-3.5 pt-6">
      <div className="hint">
        <span className="hint-icon">i</span>
        <div>
          Read-only summary of what students will see. <strong className="text-ink">Final</strong> = 0.10·HW1 + 0.10·HW2
          + 0.70·(Project + Bonus) + 0.10·Attendance. To change a score, go back to the rubric in the submission, the
          curve in step 3, or add an override in step 4. Export the CSV when you're ready to submit grades.
        </div>
      </div>

      <GradeReleaseCard courseId={courseId} setToast={setToast} />

      <DistributionPanel rows={gradebook} activeCurve={activeCurve} />

      <div className="grid gap-2">
        <div className="label-eyebrow text-ink-3">With curve</div>
        <div className="grid grid-cols-5 gap-3">
          <StatCard num={gradebook.length} lbl="Students" />
          <StatCard num={mean} lbl="Mean final" />
          <StatCard num={median} lbl="Median final" />
          <StatCard num={stdLabel} lbl="Std" />
          <StatCard num={passing} lbl="Passing" />
        </div>
        <div className="label-eyebrow mt-2 text-ink-3">Without curve</div>
        <div className="grid grid-cols-5 gap-3">
          <StatCard num={gradebook.length} lbl="Students" />
          <StatCard num={meanRaw} lbl="Mean final" />
          <StatCard num={medianRaw} lbl="Median final" />
          <StatCard num={stdRawLabel} lbl="Std" />
          <StatCard num={passingRaw} lbl="Passing" />
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-card shadow-soft">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div className="flex gap-1.5">
            {[
              { key: 'name', label: 'A→Z' },
              { key: 'final', label: 'Final ▾' },
              { key: 'attendance', label: 'Attendance ▾' }
            ].map((s) => (
              <button
                key={s.key}
                onClick={() => setSort(s.key as typeof sort)}
                className={`rounded-md px-2.5 py-1 text-[13px] transition ${
                  sort === s.key ? 'bg-forest-tint text-forest' : 'text-ink-2 hover:bg-paper-2'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <a
              className="text-[13px] text-forest hover:underline"
              href={`${apiBase()}/api/courses/${courseId}/gradebook/csv`}
            >
              ⬇ Export CSV
            </a>
            <a
              className="text-[13px] text-forest hover:underline"
              href={`${apiBase()}/api/courses/${courseId}/gradebook/grades-report.xlsx`}
            >
              ⬇ Grades report (xlsx)
            </a>
            <button
              onClick={triggerExport}
              disabled={reportsExport?.state === 'running'}
              className="text-[13px] text-forest hover:underline disabled:opacity-50"
            >
              Queue Hebrew PDFs
            </button>
            {reportsExport?.state === 'running' ? (
              <span className="text-[13px] text-ink-3">Generating PDFs…</span>
            ) : null}
            {reportsExport?.state === 'done' ? (
              <a
                className="text-[13px] text-forest hover:underline"
                href={`${apiBase()}/api/courses/${courseId}/exports/student-reports/${reportsExport.taskId}/download`}
              >
                ⬇ Hebrew PDFs ({reportsExport.count}, zip)
              </a>
            ) : null}
            {reportsExport?.state === 'failed' ? (
              <span className="text-[13px] text-terracotta" title={reportsExport.error}>
                PDF export failed: {reportsExport.error}
              </span>
            ) : null}
          </div>
        </div>
        <div className="overflow-auto">
          <table className="w-full border-collapse text-[14px]">
            <thead>
              <tr>
                {[
                  { label: 'Student', cls: 'text-left' },
                  { label: 'ID', cls: 'text-left' },
                  { label: 'Att.', cls: 'text-right' },
                  { label: 'Exempt', cls: 'text-center' },
                  { label: 'HW1', cls: 'text-right' },
                  { label: 'HW2', cls: 'text-right' },
                  { label: 'Project', cls: 'text-right' },
                  { label: 'Bonus', cls: 'text-right' },
                  { label: 'Final', cls: 'text-right pr-5' }
                ].map((c, i) => (
                  <th
                    key={c.label}
                    className={`label-eyebrow border-b border-border px-3 py-2.5 font-semibold ${c.cls} ${
                      i === 0 ? 'pl-5' : ''
                    }`}
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => (
                <tr key={s.student_id} className="border-b border-line-soft last:border-b-0 hover:bg-forest/[0.02]">
                  <td className="px-3 py-3 pl-5">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={s.name} size={26} />
                      <BilingualName name={s.name} />
                    </div>
                  </td>
                  <td className="px-3 py-3 font-mono text-[12px] text-ink-3">{s.national_id}</td>
                  <td className="px-3 py-3 text-right tnum">
                    {s.attendance_exempt ? (
                      <span className="pill pill-info">exempt</span>
                    ) : (
                      <span style={{ color: (s.attendance_percent ?? 0) >= 80 ? 'var(--ink)' : 'var(--bad)' }}>
                        {s.attendance_percent ?? '—'}%
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-center">
                    <input
                      type="checkbox"
                      checked={s.attendance_exempt}
                      onChange={() => toggleExempt(s.enrollment_id, s.attendance_exempt)}
                    />
                  </td>
                  <td className="px-3 py-3 text-right tnum">
                    {s.hw1}
                    <PeerTag row={s} tasks={['hw1']} />
                  </td>
                  <td className="px-3 py-3 text-right tnum">
                    {s.hw2}
                    <PeerTag row={s} tasks={['hw2']} />
                  </td>
                  <td className="px-3 py-3 text-right tnum">
                    {s.project_with_bonus}
                    <PeerTag row={s} tasks={['project_code', 'presentation']} />
                  </td>
                  <td
                    className="px-3 py-3 text-right tnum"
                    style={{ color: s.bonus_points > 0 ? 'var(--ok)' : 'var(--ink-3)' }}
                  >
                    {s.bonus_points > 0 ? `+${s.bonus_points}` : s.bonus_points}
                  </td>
                  <td className="px-3 py-3 pr-5 text-right">
                    <span
                      className="font-display tnum text-[17px]"
                      style={{ color: s.final >= 60 ? 'var(--ink)' : 'var(--bad)' }}
                    >
                      {s.final}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function stdDev(values: number[]): number | null {
  if (values.length < 2) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((a, v) => a + (v - mean) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

function StatCard({ num, lbl }: { num: number | string; lbl: string }) {
  return (
    <Card className="p-4">
      <div className="font-display text-[28px] leading-none tnum">{num}</div>
      <div className="mt-1 text-[12px] uppercase tracking-wider text-ink-3">{lbl}</div>
    </Card>
  );
}

function Histogram({
  values,
  targetMean,
  targetSigma,
  caption,
  bucket = 5,
  min = 0,
  max = 100,
  height: pxHeight = 120
}: {
  values: number[];
  targetMean?: number;
  targetSigma?: number;
  caption?: string;
  bucket?: number;
  min?: number;
  max?: number;
  height?: number;
}) {
  if (!values.length) return null;
  const numBuckets = Math.ceil((max - min) / bucket);
  const counts = new Array<number>(numBuckets).fill(0);
  for (const v of values) {
    const idx = Math.max(0, Math.min(numBuckets - 1, Math.floor((v - min) / bucket)));
    counts[idx]++;
  }
  const maxCount = Math.max(...counts, 1);

  const W = 800;
  const H = 100;
  const PAD_X = 8;
  const PAD_TOP = 6;
  const PAD_BOTTOM = 14;
  const innerW = W - PAD_X * 2;
  const innerH = H - PAD_TOP - PAD_BOTTOM;
  const barW = innerW / numBuckets;

  let densityPath: string | null = null;
  if (targetMean !== undefined && targetSigma !== undefined && targetSigma > 0) {
    const density = (x: number) =>
      Math.exp(-((x - targetMean) ** 2) / (2 * targetSigma * targetSigma)) /
      (targetSigma * Math.sqrt(2 * Math.PI));
    // Expected count per bucket = density(center) * bucketWidth * N — same units as bars.
    const expectedPerBucket = (centerX: number) => density(centerX) * bucket * values.length;
    const peak = expectedPerBucket(targetMean);
    const scaleY = peak > 0 ? Math.min(1, maxCount / peak) : 1;
    const samples = 120;
    const pts: string[] = [];
    for (let i = 0; i <= samples; i++) {
      const x = min + ((max - min) * i) / samples;
      const y = expectedPerBucket(x) * scaleY;
      const px = PAD_X + (innerW * (x - min)) / (max - min);
      const py = PAD_TOP + innerH - (innerH * Math.min(y, maxCount)) / maxCount;
      pts.push(`${px.toFixed(1)},${py.toFixed(1)}`);
    }
    densityPath = `M ${pts.join(' L ')}`;
  }

  const meanX = targetMean !== undefined ? PAD_X + (innerW * (targetMean - min)) / (max - min) : null;

  return (
    <Card className="p-3">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block w-full"
        style={{ height: pxHeight }}
        preserveAspectRatio="none"
      >
        {counts.map((c, i) => {
          const h = (c / maxCount) * innerH;
          return (
            <rect
              key={i}
              x={PAD_X + i * barW + 1}
              y={PAD_TOP + innerH - h}
              width={Math.max(0, barW - 2)}
              height={h}
              className="fill-forest-tint"
            />
          );
        })}
        {densityPath && <path d={densityPath} fill="none" className="stroke-forest" strokeWidth={1.5} />}
        {meanX !== null && (
          <line
            x1={meanX}
            x2={meanX}
            y1={PAD_TOP}
            y2={PAD_TOP + innerH}
            className="stroke-forest"
            strokeWidth={1}
            strokeDasharray="3 3"
            opacity={0.5}
          />
        )}
        {[0, 25, 50, 60, 75, 100].map((v) => {
          const x = PAD_X + (innerW * (v - min)) / (max - min);
          return (
            <g key={v}>
              <line
                x1={x}
                x2={x}
                y1={PAD_TOP + innerH}
                y2={PAD_TOP + innerH + 2}
                className="stroke-line-soft"
                strokeWidth={0.5}
              />
              <text x={x} y={H - 2} textAnchor="middle" className="fill-ink-3" style={{ fontSize: 9 }}>
                {v}
              </text>
            </g>
          );
        })}
      </svg>
      {caption && <div className="mt-1 text-center text-[11px] text-ink-3">{caption}</div>}
    </Card>
  );
}

function DistributionPanel({
  rows,
  activeCurve,
  height = 90
}: {
  rows: GradebookRow[];
  activeCurve: ActiveCurve | null;
  height?: number;
}) {
  if (!rows.length) return null;
  const finals = rows.map((r) => r.final).filter((v): v is number => Number.isFinite(v));
  const finalsRaw = rows.map((r) => r.final_uncurved).filter((v): v is number => Number.isFinite(v));
  if (!finals.length && !finalsRaw.length) return null;
  const dist = activeCurve?.final_distribution ?? null;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Histogram
        values={finals}
        targetMean={dist?.mean}
        targetSigma={dist?.sigma}
        caption={
          dist
            ? `With curve · target N(${dist.mean}, ${dist.sigma})`
            : 'With curve · no calibration active'
        }
        height={height}
      />
      <Histogram values={finalsRaw} caption="Without curve · raw distribution" height={height} />
    </div>
  );
}

/* =============== Settings Step =============== */

function SettingsStep({
  course,
  setToast,
  onSaved
}: {
  course: Course;
  setToast: (m: string) => void;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState({ name: course.name, code: course.code, year: String(course.year), semester: course.semester });
  const save = async () => {
    try {
      await apiPatch(`/api/courses/${course.id}`, { ...form, year: Number(form.year) });
      setToast('Course details saved');
      await onSaved();
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setToast(raw.includes('409') || raw.includes('already') ? 'Another course has this code, year and semester' : 'Save failed');
    }
  };
  return (
    <div className="grid gap-3.5 pt-6">
      <Card>
        <div className="mb-3">
          <div className="font-display text-[19px]">Course details</div>
          <div className="text-[13px] text-ink-3">Editing these doesn't affect any imported data.</div>
        </div>
        <div className="grid gap-2.5" style={{ gridTemplateColumns: '2fr 1fr 100px 100px' }}>
          <div>
            <Label>Name</Label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <Label>Code</Label>
            <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </div>
          <div>
            <Label>Year</Label>
            <Input type="number" value={form.year} onChange={(e) => setForm({ ...form, year: e.target.value })} />
          </div>
          <div>
            <Label>Sem</Label>
            <Input value={form.semester} onChange={(e) => setForm({ ...form, semester: e.target.value })} />
          </div>
        </div>
        <div className="mt-3 flex justify-end">
          <Button size="sm" onClick={save}>
            Save changes
          </Button>
        </div>
      </Card>

      <Card className="border-bad-soft">
        <div className="mb-2">
          <div className="font-display text-[19px] text-bad">Archive course</div>
          <div className="text-[13px] text-ink-3">Hides it from the active list. Data is preserved.</div>
        </div>
        <Button variant="ghost" size="sm" className="border border-bad-soft text-bad">
          Archive {course.code}
        </Button>
      </Card>
    </div>
  );
}
