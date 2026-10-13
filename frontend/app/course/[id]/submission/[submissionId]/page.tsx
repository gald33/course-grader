'use client';

import DOMPurify from 'dompurify';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { DotScale } from '@/components/ui/dot-scale';
import { AUXILIARY_KINDS, FileViewer, fileIcon, formatBytes, pickPrimary, PRIMARY_KINDS } from '@/components/ui/file-viewer';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ProgressRing } from '@/components/ui/progress-ring';
import { Textarea } from '@/components/ui/textarea';
import { TweakRadio, TweaksPanel } from '@/components/ui/tweaks-panel';
import { apiBase, apiFetch, apiGet, apiPatch, apiPost, apiPut } from '@/lib/api';

type RubricRow = {
  component: string;
  dimension_key: string;
  raw_score: number;
  adjusted_score: number;
  approved: boolean;
};

type Run = {
  id: number;
  snapshot_id: number;
  status: string;
  mode: string;
  ok_cells: number;
  failed_cells: number;
  run_ratio: number;
  penalty_multiplier: number;
  executed_notebook_artifact_id: number | null;
  executed_html_artifact_id: number | null;
  log_artifact_id: number | null;
  is_pinned: boolean;
  error_summary: string;
  started_at: string | null;
  ended_at: string | null;
};

const RUN_INFLIGHT = new Set(['QUEUED', 'RUNNING', 'queued', 'running']);
const RUN_TERMINAL = new Set(['SUCCESS', 'TIMEOUT', 'FAILED', 'completed', 'failed', 'timeout']);
const SNAP_INFLIGHT = new Set(['PENDING', 'FETCHING']);

function isRunInFlight(status: string): boolean {
  return RUN_INFLIGHT.has(status);
}

function isRunTerminal(status: string): boolean {
  return RUN_TERMINAL.has(status);
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function parseServerTime(s: string): number {
  // Backend emits naive UTC datetimes (datetime.utcnow().isoformat() with no
  // 'Z' or offset). Treat them as UTC so client elapsed math is correct.
  const hasTZ = /[zZ]|[+-]\d{2}:?\d{2}$/.test(s);
  return Date.parse(hasTZ ? s : s + 'Z');
}

function elapsedFrom(start: string | null, endMs: number): string {
  if (!start) return '0:00';
  const startMs = parseServerTime(start);
  if (Number.isNaN(startMs)) return '0:00';
  return formatElapsed(endMs - startMs);
}

type Snapshot = {
  id: number;
  url: string;
  status: string;
  fetched_at: string | null;
  artifact_id: number | null;
  error_message: string;
};

type ArtifactRef = {
  id: number;
  kind: string;
  filename: string;
  mime_type: string | null;
  size_bytes: number;
};

type Requirements = {
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

type LLMReview = {
  model: string;
  dimensions: Record<string, { score: number; rationale: string }>;
  feedback_he: string;
  usage?: Record<string, number>;
};

type DimExplanation = { score: number; rationale: string; source?: 'auto' | 'claude' };

type CodeReview = {
  component: string; // 'hw2_code' | 'project_code'
  dimensions: Record<string, DimExplanation>;
};

type SubmissionDetail = {
  submission: {
    id: number;
    assignment_type: string;
    workcode: number;
    member_student_ids: number[];
    member_ids: string[];
    member_names: string[];
    requirements: Requirements | null;
    manual_grade: number | null;
  };
  snapshots: Snapshot[];
  runs: Run[];
  rubric: RubricRow[];
  private_notes: string;
  student_feedback: string;
  consistency_summary: string;
  consistency_flags: string[];
  report_pdf_artifact_id: number | null;
  executed_html_artifact_id: number | null;
  artifacts: ArtifactRef[];
  llm_review: LLMReview | null;
  code_review: CodeReview | null;
};

type CourseSubmission = {
  id: number;
  assignment_type: string;
  assignment_id: number;
};

type Layout = 'split' | 'tabs' | 'focus';
type ArtifactTab = 'notebook' | 'pdf' | 'files';

const RUBRIC_COMPONENTS_BY_TYPE: Record<string, string[]> = {
  HW1: [],
  HW2: ['hw2_code'],
  PROJECT: ['project_code', 'project_report', 'presentation', 'final_talk']
};

const DIMENSIONS: Record<string, string[]> = {
  hw2_code: [
    'data_scope_adequacy',
    'processing_description',
    'processing_implementation',
    'num_models_baseline',
    'models_quality',
    'experiments_comparison',
    'variable_plots',
    'results_plots',
    'order',
    'clarity',
    'code_quality',
    'english_comments_compliance'
  ],
  project_code: [
    'data_scope_adequacy',
    'processing_description',
    'processing_implementation',
    'num_models_baseline',
    'models_quality',
    'experiments_comparison',
    'variable_plots',
    'results_plots',
    'order',
    'clarity',
    'code_quality',
    'english_comments_compliance'
  ],
  project_report: [
    'research_question_hypothesis',
    'data_description',
    'data_processing',
    'models_comparison',
    'results_analysis',
    'consistency_with_code'
  ],
  presentation: ['clarity', 'complexity', 'qa_answers', 'elegance', 'subjective_impression'],
  final_talk: ['clarity', 'complexity', 'qa_answers', 'elegance', 'subjective_impression']
};

const LLM_SCORED_BY_COMPONENT: Record<string, Set<string>> = {
  hw2_code: new Set(['processing_description', 'models_quality']),
  project_code: new Set(['processing_description', 'models_quality']),
  project_report: new Set([
    'research_question_hypothesis',
    'data_description',
    'data_processing',
    'models_comparison',
    'results_analysis',
    'consistency_with_code'
  ])
};

function isLlmScored(component: string, dim: string): boolean {
  return LLM_SCORED_BY_COMPONENT[component]?.has(dim) ?? false;
}

const LABELS: Record<string, string> = {
  data_scope_adequacy: 'Data scope',
  processing_description: 'Processing description',
  processing_implementation: 'Processing impl.',
  num_models_baseline: 'Models / baseline',
  models_quality: 'Model quality',
  experiments_comparison: 'Experiments',
  variable_plots: 'Variable plots',
  results_plots: 'Results plots',
  order: 'Order',
  clarity: 'Clarity',
  code_quality: 'Code quality',
  english_comments_compliance: 'English comments',
  research_question_hypothesis: 'Research question',
  data_description: 'Data description',
  data_processing: 'Data processing',
  models_comparison: 'Models comparison',
  results_analysis: 'Results analysis',
  consistency_with_code: 'Consistency w/ code',
  complexity: 'Complexity',
  qa_answers: 'Q&A answers',
  elegance: 'Elegance',
  subjective_impression: 'Subjective impression'
};

export default function SubmissionReviewPage({
  params
}: {
  params: { id: string; submissionId: string };
}) {
  const courseId = Number(params.id);
  const submissionId = Number(params.submissionId);

  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [queue, setQueue] = useState<CourseSubmission[]>([]);
  const [htmlDoc, setHtmlDoc] = useState('');
  const [rubricValues, setRubricValues] = useState<Record<string, number>>({});
  const [rubricApproved, setRubricApproved] = useState<Record<string, boolean>>({});
  const [notes, setNotes] = useState('');
  const [feedback, setFeedback] = useState('');
  const [toast, setToast] = useState<string | null>(null);
  const [layout, setLayout] = useState<Layout>('split');
  const [activeArtifact, setActiveArtifact] = useState<ArtifactTab>('notebook');

  // Save status — tracked separately for rubric and notes
  const [rubricSavedAt, setRubricSavedAt] = useState<Date | null>(null);
  const [notesSavedAt, setNotesSavedAt] = useState<Date | null>(null);
  const [rubricSaving, setRubricSaving] = useState(false);
  const [notesSaving, setNotesSaving] = useState(false);

  // Dirty refs hold the latest values for save-on-unload / save-on-nav
  const rubricRef = useRef<Record<string, number>>({});
  const rubricApprovedRef = useRef<Record<string, boolean>>({});
  const notesRef = useRef({ notes: '', feedback: '' });
  const rubricDirty = useRef(false);
  const notesDirty = useRef(false);
  // Mirror the dirty refs as state so SaveStatus re-renders on changes.
  const [rubricDirtyState, setRubricDirtyState] = useState(false);
  const [notesDirtyState, setNotesDirtyState] = useState(false);
  const submissionIdRef = useRef(submissionId);
  useEffect(() => {
    submissionIdRef.current = submissionId;
    // Reset save indicators when navigating between submissions so the
    // "Saved · HH:MM" pill from a prior submission doesn't carry over.
    setRubricSavedAt(null);
    setNotesSavedAt(null);
  }, [submissionId]);
  useEffect(() => {
    rubricRef.current = rubricValues;
  }, [rubricValues]);
  useEffect(() => {
    rubricApprovedRef.current = rubricApproved;
  }, [rubricApproved]);
  useEffect(() => {
    notesRef.current = { notes, feedback };
  }, [notes, feedback]);

  // Initial layout from localStorage (avoids SSR mismatch)
  useEffect(() => {
    const saved = (typeof window !== 'undefined' && localStorage.getItem('cg-review-layout')) as Layout | null;
    if (saved === 'split' || saved === 'tabs' || saved === 'focus') setLayout(saved);
  }, []);
  useEffect(() => {
    if (typeof window !== 'undefined') localStorage.setItem('cg-review-layout', layout);
  }, [layout]);

  // Toast auto-dismiss
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  const load = useCallback(async () => {
    const data = await apiGet<SubmissionDetail>(`/api/submissions/${submissionId}`);
    setDetail(data);

    // Only sync notes/feedback from the server when the user has no in-progress
    // edits. Polling fires every 2s during runs, and an unconditional reset
    // here clobbers anything typed since the last save.
    if (!notesDirty.current) {
      setNotes(data.private_notes || '');
      setFeedback(data.student_feedback || '');
      setNotesDirtyState(false);
    }

    if (!rubricDirty.current) {
      const values: Record<string, number> = {};
      const approved: Record<string, boolean> = {};
      for (const row of data.rubric) {
        const key = `${row.component}:${row.dimension_key}`;
        values[key] = row.raw_score;
        approved[key] = row.approved !== false;
      }
      setRubricValues(values);
      setRubricApproved(approved);
      setRubricDirtyState(false);
    }

    if (data.executed_html_artifact_id) setActiveArtifact('notebook');
    else if (data.report_pdf_artifact_id) setActiveArtifact('pdf');
    else setActiveArtifact('files');

    if (data.executed_html_artifact_id) {
      try {
        const res = await apiFetch(`/api/artifacts/${data.executed_html_artifact_id}/raw`);
        const rawHtml = await res.text();
        setHtmlDoc(DOMPurify.sanitize(rawHtml));
      } catch {
        setHtmlDoc('');
      }
    } else {
      setHtmlDoc('');
    }
  }, [submissionId]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while a run is queued/running or a snapshot is mid-fetch. Stops automatically
  // once nothing is in flight — and resumes if the user comes back during a long run.
  useEffect(() => {
    if (!detail) return;
    const inFlight =
      detail.runs.some((r) => isRunInFlight(r.status)) ||
      detail.snapshots.some((s) => SNAP_INFLIGHT.has(s.status));
    if (!inFlight) return;
    const t = setInterval(() => {
      void load();
    }, 2000);
    return () => clearInterval(t);
  }, [detail, load]);

  // Tick every second so the "Running… mm:ss" label updates smoothly between polls.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!detail) return;
    const inFlight = detail.runs.some((r) => isRunInFlight(r.status));
    if (!inFlight) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [detail]);

  // Detect run transitions (RUNNING → terminal) and surface a toast with the result.
  const prevRunStatuses = useRef<Record<number, string>>({});
  useEffect(() => {
    if (!detail) return;
    const prev = prevRunStatuses.current;
    for (const r of detail.runs) {
      const before = prev[r.id];
      if (before && before !== r.status && isRunTerminal(r.status) && !isRunTerminal(before)) {
        const elapsed =
          r.started_at && r.ended_at
            ? formatElapsed(parseServerTime(r.ended_at) - parseServerTime(r.started_at))
            : null;
        if (r.status === 'SUCCESS') {
          const pct = Math.round((r.run_ratio || 0) * 100);
          setToast(`Run #${r.id} done · ${pct}% cells ran${elapsed ? ` · ${elapsed}` : ''}`);
        } else if (r.status === 'TIMEOUT') {
          setToast(`Run #${r.id} timed out${elapsed ? ` after ${elapsed}` : ''}`);
        } else if (r.status === 'FAILED') {
          const reason = r.error_summary ? `: ${r.error_summary}` : '';
          setToast(`Run #${r.id} failed${reason}`);
        }
      }
    }
    const next: Record<number, string> = {};
    for (const r of detail.runs) next[r.id] = r.status;
    prevRunStatuses.current = next;
  }, [detail]);

  // Queue for J/K navigation — submissions in this course of the same assignment type
  useEffect(() => {
    apiGet<CourseSubmission[]>(`/api/courses/${courseId}/submissions`)
      .then(setQueue)
      .catch(() => setQueue([]));
  }, [courseId]);

  const sameTypeQueue = useMemo(() => {
    if (!detail) return [] as CourseSubmission[];
    return queue.filter((s) => s.assignment_type === detail.submission.assignment_type);
  }, [queue, detail]);

  const myIdx = useMemo(
    () => sameTypeQueue.findIndex((s) => s.id === submissionId),
    [sameTypeQueue, submissionId]
  );
  const prev = myIdx > 0 ? sameTypeQueue[myIdx - 1] : null;
  const next = myIdx >= 0 && myIdx < sameTypeQueue.length - 1 ? sameTypeQueue[myIdx + 1] : null;

  const components = detail ? RUBRIC_COMPONENTS_BY_TYPE[detail.submission.assignment_type] || [] : [];
  const allDims = components.flatMap((c) => (DIMENSIONS[c] || []).map((d) => `${c}:${d}`));
  const filledCount = allDims.filter((k) => rubricValues[k] != null).length;

  // Use refs so saves always send the latest values, even if called from a
  // navigation/unload handler that won't see fresh closures.
  const saveRubric = useCallback(
    async (opts?: { silent?: boolean; targetId?: number }) => {
      const id = opts?.targetId ?? submissionIdRef.current;
      const values = rubricRef.current;
      const approved = rubricApprovedRef.current;
      const dimensions = Object.entries(values).map(([key, value]) => {
        const [component, dimension_key] = key.split(':');
        return { component, dimension_key, raw_score: value, approved: approved[key] !== false };
      });
      setRubricSaving(true);
      try {
        await apiPut(`/api/submissions/${id}/rubric`, { dimensions });
        rubricDirty.current = false;
        setRubricDirtyState(false);
        setRubricSavedAt(new Date());
        if (!opts?.silent) setToast('Rubric saved');
      } finally {
        setRubricSaving(false);
      }
    },
    []
  );

  const saveNotes = useCallback(
    async (opts?: { silent?: boolean; targetId?: number }) => {
      const id = opts?.targetId ?? submissionIdRef.current;
      const { notes, feedback } = notesRef.current;
      setNotesSaving(true);
      try {
        await apiPatch(`/api/submissions/${id}/notes`, {
          notes_private: notes,
          feedback_student: feedback
        });
        notesDirty.current = false;
        setNotesDirtyState(false);
        setNotesSavedAt(new Date());
        if (!opts?.silent) setToast('Notes saved');
      } finally {
        setNotesSaving(false);
      }
    },
    []
  );

  // Debounced autosave for rubric (700 ms after last change)
  useEffect(() => {
    if (!detail) return;
    if (!rubricDirty.current) return;
    const t = setTimeout(() => {
      void saveRubric({ silent: true });
    }, 700);
    return () => clearTimeout(t);
  }, [rubricValues, rubricApproved, detail, saveRubric]);

  // Debounced autosave for notes (1200 ms after last keystroke)
  useEffect(() => {
    if (!detail) return;
    if (!notesDirty.current) return;
    const t = setTimeout(() => {
      void saveNotes({ silent: true });
    }, 1200);
    return () => clearTimeout(t);
  }, [notes, feedback, detail, saveNotes]);

  // Flush pending saves before unload
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (rubricDirty.current || notesDirty.current) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, []);

  // Wrappers used by callers that mark dirty. These let us track changes
  // without making every component aware of the dirty refs.
  const updateRubric = useCallback(
    (updater: (prev: Record<string, number>) => Record<string, number>) => {
      rubricDirty.current = true;
      setRubricDirtyState(true);
      setRubricValues(updater);
    },
    []
  );

  // Per-key score change. Always marks the dimension as approved — touching
  // the dot is an explicit grader decision.
  const setRubricEntry = useCallback((key: string, value: number) => {
    rubricDirty.current = true;
    setRubricDirtyState(true);
    setRubricValues((prev) => ({ ...prev, [key]: value }));
    setRubricApproved((prev) => ({ ...prev, [key]: true }));
  }, []);

  // Explicit approve/unapprove without touching the score. Used by the ✓ button.
  const setRubricApprovalFor = useCallback((key: string, approved: boolean) => {
    rubricDirty.current = true;
    setRubricDirtyState(true);
    setRubricApproved((prev) => ({ ...prev, [key]: approved }));
  }, []);
  const updateNotes = useCallback((v: string) => {
    notesDirty.current = true;
    setNotesDirtyState(true);
    setNotes(v);
  }, []);
  const updateFeedback = useCallback((v: string) => {
    notesDirty.current = true;
    setNotesDirtyState(true);
    setFeedback(v);
  }, []);

  const queueRun = async (mode: 'snapshot' | 'latest') => {
    try {
      await apiPost(`/api/submissions/${submissionId}/runs`, { mode });
      setToast(mode === 'latest' ? 'Fetching from Colab…' : 'Queued');
      await load();
    } catch (e) {
      const msg = (e as Error).message || '';
      // FastAPI returns {"detail": "..."} — surface the reason
      const detail = (() => {
        try {
          return JSON.parse(msg).detail as string;
        } catch {
          return msg;
        }
      })();
      setToast(`Couldn't queue run: ${detail || 'unknown error'}`);
    }
  };

  const pinRun = async (runId: number) => {
    try {
      await apiPost(`/api/runs/${runId}/pin`);
      setToast('Run pinned');
      await load();
    } catch (e) {
      setToast(`Couldn't pin run: ${(e as Error).message || 'unknown error'}`);
    }
  };

  const [autoGrading, setAutoGrading] = useState(false);

  const autoGrade = useCallback(async () => {
    if (autoGrading) return;
    if (!detail) return;
    const isProject = detail.submission.assignment_type === 'PROJECT';
    setAutoGrading(true);
    try {
      setToast('Auto-grade: queueing notebook run…');
      const newRun = await apiPost<Run>(`/api/submissions/${submissionId}/runs`, { mode: 'snapshot' });

      // Poll the run directly so we have a deterministic terminal-state signal
      // here, independent of the page-level 2s polling effect.
      const start = Date.now();
      const timeoutMs = 16 * 60 * 1000; // worker hard-cap is 15min; pad by 1min
      let final: Run | undefined;
      while (Date.now() - start < timeoutMs) {
        const elapsedSec = Math.round((Date.now() - start) / 1000);
        const runs = await apiGet<Run[]>(`/api/submissions/${submissionId}/runs`);
        const r = runs.find((x) => x.id === newRun.id);
        if (r && isRunTerminal(r.status)) {
          final = r;
          break;
        }
        const phase = r?.status === 'RUNNING' ? `running (${r.ok_cells} ok, ${r.failed_cells} failed)` : 'queued';
        setToast(`Auto-grade: notebook ${phase} · ${elapsedSec}s`);
        await new Promise((rs) => setTimeout(rs, 2000));
      }
      if (!final) throw new Error('Notebook run did not finish in 16 minutes');
      if (final.status !== 'SUCCESS') {
        throw new Error(
          `Notebook ${final.status.toLowerCase()}${final.error_summary ? `: ${final.error_summary}` : ''}`
        );
      }

      setToast('Auto-grade: pinning run…');
      await apiPost(`/api/runs/${newRun.id}/pin`);

      if (isProject) {
        setToast('Auto-grade: asking Claude (10–30s)…');
        await apiPost(`/api/submissions/${submissionId}/llm-review`);
        try {
          await apiPost(`/api/submissions/${submissionId}/llm-review/apply`);
        } catch {
          // Non-fatal — same fallback as the standalone Claude card. Rationales
          // still display next to each rubric row even if apply fails.
        }
      }

      await load();
      setToast(isProject ? 'Auto-grade complete · code + report ✓' : 'Auto-grade complete · code ✓');
    } catch (e) {
      const msg = (e as Error).message || '';
      const detailMsg = (() => {
        try {
          return JSON.parse(msg).detail as string;
        } catch {
          return msg;
        }
      })();
      setToast(`Auto-grade failed: ${detailMsg || 'unknown error'}`);
    } finally {
      setAutoGrading(false);
    }
  }, [autoGrading, detail, submissionId, load]);

  const flushAndNavigate = useCallback(
    async (nextHref: string) => {
      const tasks: Promise<unknown>[] = [];
      if (rubricDirty.current) tasks.push(saveRubric({ silent: true }));
      if (notesDirty.current) tasks.push(saveNotes({ silent: true }));
      if (tasks.length > 0) await Promise.allSettled(tasks);
      window.location.assign(nextHref);
    },
    [saveRubric, saveNotes]
  );

  // Keyboard shortcuts (J/K nav, ⌘S save)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const tag = t?.tagName;
      const editable = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable;
      if (!editable) {
        if (e.key === 'j' && next) {
          void flushAndNavigate(`/course/${courseId}/submission/${next.id}`);
        } else if (e.key === 'k' && prev) {
          void flushAndNavigate(`/course/${courseId}/submission/${prev.id}`);
        }
      }
      if (e.key === 's' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void saveRubric();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [next, prev, courseId, saveRubric, flushAndNavigate]);

  if (!detail) {
    return <div className="p-10 text-ink-3">Loading…</div>;
  }

  const sub = detail.submission;
  const sharedProps: SharedProps = {
    detail,
    htmlDoc,
    rubricValues,
    setRubricValues: updateRubric,
    rubricApproved,
    setRubricEntry,
    setRubricApprovalFor,
    notes,
    setNotes: updateNotes,
    feedback,
    setFeedback: updateFeedback,
    components,
    activeArtifact,
    setActiveArtifact,
    saveRubric: () => void saveRubric(),
    saveNotes: () => void saveNotes(),
    queueRun,
    pinRun,
    setToast,
    rubricSavedAt,
    rubricSaving,
    rubricDirty: rubricDirtyState,
    notesSavedAt,
    notesSaving,
    notesDirty: notesDirtyState,
    courseId,
    refresh: load,
    now
  };

  return (
    <div className="min-h-screen">
      <ReviewHeader
        sub={sub}
        courseId={courseId}
        prev={prev}
        next={next}
        myIdx={myIdx}
        total={sameTypeQueue.length}
        filledCount={filledCount}
        totalDims={allDims.length}
        saveRubric={() => void saveRubric()}
        flushAndNavigate={flushAndNavigate}
        rubricSavedAt={rubricSavedAt}
        rubricSaving={rubricSaving}
        rubricDirty={rubricDirtyState || notesDirtyState}
        autoGrade={() => void autoGrade()}
        autoGrading={autoGrading}
      />

      {layout === 'split' ? <ReviewSplit {...sharedProps} /> : null}
      {layout === 'tabs' ? <ReviewTabs {...sharedProps} /> : null}
      {layout === 'focus' ? <ReviewFocus {...sharedProps} filledCount={filledCount} totalDims={allDims.length} /> : null}

      <TweaksPanel>
        <TweakRadio<Layout>
          label="Review layout"
          hint="Split: artifact left + sticky rubric right. Tabs: full-width artifact, rubric below. Focus: artifact full-bleed + drawer."
          value={layout}
          onChange={setLayout}
          options={[
            { value: 'split', label: 'Split' },
            { value: 'tabs', label: 'Tabs' },
            { value: 'focus', label: 'Focus' }
          ]}
        />
      </TweaksPanel>

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

/* ===== Header ===== */

function ReviewHeader({
  sub,
  courseId,
  prev,
  next,
  myIdx,
  total,
  filledCount,
  totalDims,
  saveRubric,
  flushAndNavigate,
  rubricSavedAt,
  rubricSaving,
  rubricDirty,
  autoGrade,
  autoGrading
}: {
  sub: SubmissionDetail['submission'];
  courseId: number;
  prev: CourseSubmission | null;
  next: CourseSubmission | null;
  myIdx: number;
  total: number;
  filledCount: number;
  totalDims: number;
  saveRubric: () => void;
  flushAndNavigate: (href: string) => Promise<void>;
  rubricSavedAt: Date | null;
  rubricSaving: boolean;
  rubricDirty: boolean;
  autoGrade: () => void;
  autoGrading: boolean;
}) {
  const isProject = sub.assignment_type === 'PROJECT';
  const tooltip = isProject
    ? 'Run notebook → pin → ask Claude to review the report'
    : 'Run notebook + auto code metrics';
  return (
    <header
      className="sticky top-0 z-40 flex items-center gap-4 border-b border-border px-7 py-3.5"
      style={{ background: 'rgba(245, 241, 232, 0.92)', backdropFilter: 'blur(10px)' }}
    >
      <Link
        href={`/course/${courseId}`}
        className="rounded-md px-2 py-1 text-[13px] text-ink-2 hover:bg-paper-2 hover:text-ink no-underline"
      >
        ← All submissions
      </Link>
      <div className="h-6 w-px bg-border" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2.5">
          <span className="font-display text-lg">
            {sub.assignment_type} · #{sub.id}
          </span>
          <span className="text-xs text-ink-3">WC{sub.workcode}</span>
          <RequirementsPill requirements={sub.requirements} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          {sub.member_names.map((name, i) => (
            <span key={i} className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
              <span className="he-name text-[13px]">{name || '—'}</span>
              <span className="text-ink-3">{sub.member_ids[i]}</span>
            </span>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-3">
        {totalDims > 0 ? (
          <div className="flex items-center gap-2">
            <ProgressRing value={filledCount} max={totalDims} size={32} stroke={3} />
            <div className="text-[11px] leading-tight text-ink-3">
              <div className="tnum text-ink">
                {filledCount}
                <span className="text-ink-3">/{totalDims}</span>
              </div>
              <div>scored</div>
            </div>
          </div>
        ) : null}
        <div className="h-6 w-px bg-border" />
        <div className="flex items-center gap-1">
          <button
            disabled={!prev}
            onClick={() => prev && void flushAndNavigate(`/course/${courseId}/submission/${prev.id}`)}
            className="rounded-md px-2 py-1 text-ink-2 hover:bg-paper-2 disabled:opacity-30"
            title="Previous (k)"
          >
            ←
          </button>
          <span className="tnum min-w-[64px] text-center text-xs text-ink-3">
            {myIdx >= 0 ? `${myIdx + 1} of ${total}` : `— of ${total}`}
          </span>
          <button
            disabled={!next}
            onClick={() => next && void flushAndNavigate(`/course/${courseId}/submission/${next.id}`)}
            className="rounded-md px-2 py-1 text-ink-2 hover:bg-paper-2 disabled:opacity-30"
            title="Next (j)"
          >
            →
          </button>
        </div>
        <SaveStatus saving={rubricSaving} savedAt={rubricSavedAt} dirty={rubricDirty} />
        <Button size="sm" variant="ghost" onClick={autoGrade} disabled={autoGrading} title={tooltip}>
          {autoGrading ? 'Auto-grading…' : '✦ Auto grade'}
        </Button>
        <Button size="sm" onClick={saveRubric} title="⌘S">
          Save now
          <span className="ml-1.5 rounded border border-paper/30 bg-paper/10 px-1 text-[10px] tracking-tight">⌘S</span>
        </Button>
      </div>
    </header>
  );
}

function SaveStatus({
  saving,
  savedAt,
  dirty,
  inline
}: {
  saving: boolean;
  savedAt: Date | null;
  dirty: boolean;
  inline?: boolean;
}) {
  let text = 'Not saved';
  let dot = 'var(--ink-4)';
  if (saving) {
    text = 'Saving…';
    dot = 'var(--info)';
  } else if (dirty) {
    text = 'Unsaved changes';
    dot = 'var(--warn)';
  } else if (savedAt) {
    const hh = String(savedAt.getHours()).padStart(2, '0');
    const mm = String(savedAt.getMinutes()).padStart(2, '0');
    text = `Saved · ${hh}:${mm}`;
    dot = 'var(--ok)';
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${inline ? 'text-[11px]' : 'text-[12px]'} text-ink-3`}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: dot }} />
      {text}
    </span>
  );
}

function RequirementsPill({ requirements }: { requirements: Requirements | null }) {
  if (!requirements) return null;
  if (requirements.overridden_by_manual_grade) {
    const tooltip = requirements.missing.length
      ? `Manual grade applied — would otherwise be missing: ${requirements.missing.join(', ')}`
      : 'Manual grade applied (rubric bypassed)';
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-forest-tint px-2 py-px text-[11px] text-forest"
        title={tooltip}
      >
        ✓ Manually graded
      </span>
    );
  }
  if (requirements.complete) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2 py-px text-[11px] text-ok"
        title={
          requirements.needs_pdf && requirements.needs_colab
            ? 'PDF + Colab URL present'
            : requirements.needs_pdf
              ? 'PDF present'
              : 'Colab URL present'
        }
      >
        ✓ Requirements met
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-px text-[11px] text-warn"
      title={`Missing: ${requirements.missing.join(', ')}`}
    >
      ⚠ Missing {requirements.missing.join(' + ')}
    </span>
  );
}

/* ===== Layout: Split ===== */

type SharedProps = {
  detail: SubmissionDetail;
  htmlDoc: string;
  rubricValues: Record<string, number>;
  setRubricValues: (updater: (prev: Record<string, number>) => Record<string, number>) => void;
  rubricApproved: Record<string, boolean>;
  setRubricEntry: (key: string, value: number) => void;
  setRubricApprovalFor: (key: string, approved: boolean) => void;
  notes: string;
  setNotes: (v: string) => void;
  feedback: string;
  setFeedback: (v: string) => void;
  components: string[];
  activeArtifact: ArtifactTab;
  setActiveArtifact: React.Dispatch<React.SetStateAction<ArtifactTab>>;
  saveRubric: () => void;
  saveNotes: () => void;
  queueRun: (mode: 'snapshot' | 'latest') => void;
  pinRun: (id: number) => void;
  setToast: (m: string) => void;
  rubricSavedAt: Date | null;
  rubricSaving: boolean;
  rubricDirty: boolean;
  notesSavedAt: Date | null;
  notesSaving: boolean;
  notesDirty: boolean;
  courseId: number;
  refresh: () => Promise<void>;
  now: number;
};

function ReviewSplit(props: SharedProps) {
  return (
    <div className="grid items-start" style={{ gridTemplateColumns: 'minmax(0, 1.4fr) minmax(420px, 1fr)' }}>
      <div className="min-w-0 px-7 py-5 pb-10">
        <ShortcutRow />
        <ArtifactPanel
          detail={props.detail}
          htmlDoc={props.htmlDoc}
          active={props.activeArtifact}
          setActive={props.setActiveArtifact}
          height={780}
          refresh={props.refresh}
          setToast={props.setToast}
        />
        <DataFilesPanel detail={props.detail} />
        <div className="mt-3.5">
          <RunsPanel detail={props.detail} queueRun={props.queueRun} pinRun={props.pinRun} now={props.now} />
        </div>
      </div>
      <aside
        className="sticky top-[78px] max-h-[calc(100vh-78px)] overflow-auto px-3.5 py-5 pb-10"
        style={{ paddingRight: 28 }}
      >
        <RubricPanel {...props} />
        <LLMReviewCard {...props} />
        <ManualGradeCard {...props} />
        <MissingFlagsCard {...props} />
        <NotesPanel
          notes={props.notes}
          setNotes={props.setNotes}
          feedback={props.feedback}
          setFeedback={props.setFeedback}
          saveNotes={props.saveNotes}
          notesSaving={props.notesSaving}
          notesSavedAt={props.notesSavedAt}
          notesDirty={props.notesDirty}
        />
        <OverrideCard {...props} />
        <ConsistencyPanel detail={props.detail} />
      </aside>
    </div>
  );
}

function ReviewTabs(props: SharedProps) {
  return (
    <div className="mx-auto max-w-[1500px] px-7 py-5 pb-10">
      <ArtifactPanel
        detail={props.detail}
        htmlDoc={props.htmlDoc}
        active={props.activeArtifact}
        setActive={props.setActiveArtifact}
        height={620}
        refresh={props.refresh}
        setToast={props.setToast}
      />
      <div className="mt-4 grid gap-4" style={{ gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 1fr)' }}>
        <RubricPanel {...props} />
        <div className="grid content-start gap-3">
          <LLMReviewCard {...props} />
          <ManualGradeCard {...props} />
          <MissingFlagsCard {...props} />
          <NotesPanel
            notes={props.notes}
            setNotes={props.setNotes}
            feedback={props.feedback}
            setFeedback={props.setFeedback}
            saveNotes={props.saveNotes}
            notesSaving={props.notesSaving}
            notesSavedAt={props.notesSavedAt}
            notesDirty={props.notesDirty}
          />
          <OverrideCard {...props} />
          <RunsPanel detail={props.detail} queueRun={props.queueRun} pinRun={props.pinRun} now={props.now} compact />
          <ConsistencyPanel detail={props.detail} />
        </div>
      </div>
    </div>
  );
}

function ReviewFocus(props: SharedProps & { filledCount: number; totalDims: number }) {
  const [drawer, setDrawer] = useState(true);
  return (
    <div
      className="grid"
      style={{ gridTemplateColumns: drawer ? '1fr 380px' : '1fr 0', transition: 'grid-template-columns 200ms ease' }}
    >
      <div className="min-w-0 px-7 py-3.5 pb-10">
        <ArtifactPanel
          detail={props.detail}
          htmlDoc={props.htmlDoc}
          active={props.activeArtifact}
          setActive={props.setActiveArtifact}
          height={'calc(100vh - 130px)'}
          refresh={props.refresh}
          setToast={props.setToast}
        />
      </div>
      <aside
        className="sticky top-[78px] max-h-[calc(100vh-78px)] overflow-auto border-l border-border bg-paper-2 transition-opacity duration-200"
        style={{ padding: drawer ? '18px 22px 40px' : 0, opacity: drawer ? 1 : 0 }}
      >
        {drawer ? (
          <>
            <div className="mb-3.5 flex items-center justify-between">
              <span className="font-display text-lg">Score</span>
              <button
                onClick={() => setDrawer(false)}
                className="text-sm text-ink-3 hover:text-ink"
                aria-label="Close drawer"
              >
                ×
              </button>
            </div>
            <RubricPanel {...props} embedded />
            <div className="my-4 h-px bg-border" />
            <LLMReviewCard {...props} embedded />
            <div className="my-4 h-px bg-border" />
            <ManualGradeCard {...props} embedded />
            <div className="my-4 h-px bg-border" />
            <MissingFlagsCard {...props} embedded />
            <div className="my-4 h-px bg-border" />
            <NotesPanel
              notes={props.notes}
              setNotes={props.setNotes}
              feedback={props.feedback}
              setFeedback={props.setFeedback}
              saveNotes={props.saveNotes}
              notesSaving={props.notesSaving}
              notesSavedAt={props.notesSavedAt}
              notesDirty={props.notesDirty}
              embedded
            />
            <div className="my-4 h-px bg-border" />
            <OverrideCard {...props} embedded />
            <div className="my-4 h-px bg-border" />
            <RunsPanel detail={props.detail} queueRun={props.queueRun} pinRun={props.pinRun} now={props.now} compact embedded />
          </>
        ) : null}
      </aside>
      {!drawer ? (
        <button
          onClick={() => setDrawer(true)}
          className="fixed right-6 top-[96px] z-40 rounded-md bg-forest-tint px-3.5 py-2 text-sm text-forest hover:bg-forest-soft"
        >
          Open rubric ({props.filledCount}/{props.totalDims})
        </button>
      ) : null}
    </div>
  );
}

/* ===== Shortcut row ===== */
function ShortcutRow() {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-ink-3">
      <span>
        <Kbd>J</Kbd> next
      </span>
      <span>
        <Kbd>K</Kbd> previous
      </span>
      <span>
        <Kbd>0</Kbd>–<Kbd>5</Kbd> score active dot
      </span>
      <span>
        <Kbd>⌘</Kbd>
        <Kbd>S</Kbd> save rubric
      </span>
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <span className="mx-0.5 inline-flex min-w-[18px] items-center justify-center rounded border border-b-2 border-border bg-paper-2 px-1.5 py-px font-mono text-[11px] text-ink-2">
      {children}
    </span>
  );
}

/* ===== Artifact panel ===== */

function ArtifactPanel({
  detail,
  htmlDoc,
  active,
  setActive,
  height,
  refresh,
  setToast
}: {
  detail: SubmissionDetail;
  htmlDoc: string;
  active: ArtifactTab;
  setActive: React.Dispatch<React.SetStateAction<ArtifactTab>>;
  height: number | string;
  refresh: () => Promise<void>;
  setToast: (m: string) => void;
}) {
  // Only "primary" submission artifacts go in the main viewer/strip — data
  // files (CSVs etc.) live in their own list below.
  const primaryFiles = detail.artifacts.filter((a) => PRIMARY_KINDS.has(a.kind) || (!AUXILIARY_KINDS.has(a.kind) && a.kind !== 'executed_html' && a.kind !== 'executed_ipynb' && a.kind !== 'run_logs' && a.kind !== 'originality_pdf'));
  const dataFiles = detail.artifacts.filter((a) => AUXILIARY_KINDS.has(a.kind));
  const primary = pickPrimary(primaryFiles);
  const [selectedId, setSelectedId] = useState<number | null>(primary?.id ?? null);
  useEffect(() => {
    setSelectedId(primary?.id ?? null);
  }, [primary?.id]);

  const tabs: { key: ArtifactTab; label: string; count?: number; available: boolean }[] = [
    { key: 'files', label: 'Submission file', count: primaryFiles.length, available: primaryFiles.length > 0 },
    { key: 'notebook', label: 'Executed notebook', available: !!detail.executed_html_artifact_id }
  ];
  const enabled = tabs.filter((t) => t.available);
  const showKey =
    enabled.find((t) => t.key === active)?.key || enabled[0]?.key || 'files';
  const showFile = primaryFiles.find((a) => a.id === selectedId) ?? primary;

  // Most recent Colab URL — link out to the live Colab regardless of run state.
  const latestColabUrl = detail.snapshots.find((s) => s.url)?.url ?? null;
  // Snapshots are returned id-DESC, so the last entry is the oldest paste —
  // i.e., the originally submitted URL. Only meaningful once an overwrite exists.
  const originalColabUrl =
    detail.snapshots.length > 1
      ? detail.snapshots[detail.snapshots.length - 1]?.url ?? null
      : null;

  const [urlEditOpen, setUrlEditOpen] = useState(false);
  const [urlDraft, setUrlDraft] = useState('');
  const [urlSaving, setUrlSaving] = useState(false);
  const [urlRemoving, setUrlRemoving] = useState(false);

  const openUrlEdit = () => {
    setUrlDraft(latestColabUrl ?? '');
    setUrlEditOpen(true);
  };
  const cancelUrlEdit = () => {
    setUrlEditOpen(false);
    setUrlDraft('');
  };
  const submitUrlEdit = async () => {
    const next = urlDraft.trim();
    if (!next) return;
    setUrlSaving(true);
    try {
      await apiPost(`/api/submissions/${detail.submission.id}/snapshot`, { url: next });
      setUrlEditOpen(false);
      setUrlDraft('');
      setToast(latestColabUrl ? 'URL updated — fetching snapshot' : 'Snapshot queued');
      await refresh();
    } catch (e) {
      setToast(`Couldn't update URL: ${(e as Error).message || 'unknown error'}`);
    } finally {
      setUrlSaving(false);
    }
  };
  const removeUrl = async () => {
    const runCount = detail.runs.length;
    const message = runCount > 0
      ? `Remove the Colab URL? This also discards ${runCount} run${runCount === 1 ? '' : 's'} and the snapshot history.`
      : 'Remove the Colab URL? The snapshot history will be discarded.';
    if (!window.confirm(message)) return;
    setUrlRemoving(true);
    try {
      const res = await apiFetch(`/api/submissions/${detail.submission.id}/snapshots`, { method: 'DELETE' });
      if (!res.ok) {
        const text = await res.text();
        setToast(`Couldn't remove URL: ${text || res.statusText}`);
        return;
      }
      setUrlEditOpen(false);
      setUrlDraft('');
      setToast('Colab URL removed');
      await refresh();
    } finally {
      setUrlRemoving(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card shadow-soft">
      <div className="flex items-center border-b border-border">
        <div className="flex flex-1">
          {(enabled.length > 0 ? enabled : tabs).map((t) => {
            const selected = showKey === t.key;
            return (
              <button
                key={t.key}
                disabled={!t.available}
                onClick={() => setActive(t.key)}
                className="-mb-px flex items-center gap-1.5 px-4 py-3 text-[13px] font-medium transition-colors disabled:opacity-40"
                style={{
                  color: selected ? 'var(--ink)' : 'var(--ink-3)',
                  borderBottom: selected ? '2px solid var(--forest)' : '2px solid transparent'
                }}
              >
                {t.label}
                {t.count != null ? (
                  <span className="tnum text-[11px] text-ink-3">{t.count}</span>
                ) : null}
                {!t.available ? <span className="text-[10px] text-ink-4">(none)</span> : null}
              </button>
            );
          })}
        </div>
        <div className="mr-3 flex items-center gap-1.5">
          {latestColabUrl ? (
            <a
              href={latestColabUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-[12px] text-ink-2 transition hover:border-forest-soft hover:text-forest"
              title="Open the live Colab notebook"
            >
              <span aria-hidden>⎘</span> Open in Colab
            </a>
          ) : null}
          <button
            type="button"
            onClick={openUrlEdit}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-[12px] text-ink-2 transition hover:border-forest-soft hover:text-forest"
            title={latestColabUrl ? 'Replace the Colab URL (original is kept as backup)' : 'Add a Colab URL'}
          >
            {latestColabUrl ? 'Change URL' : 'Add Colab URL'}
          </button>
          {latestColabUrl ? (
            <button
              type="button"
              onClick={() => void removeUrl()}
              disabled={urlRemoving}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-[12px] text-ink-3 transition hover:border-terracotta hover:text-terracotta disabled:opacity-60"
              title="Remove the Colab URL and its snapshot history"
            >
              {urlRemoving ? 'Removing…' : 'Remove URL'}
            </button>
          ) : null}
        </div>
      </div>
      {urlEditOpen ? (
        <div className="grid items-center gap-2 border-b border-border bg-paper-2/40 px-3 py-2"
          style={{ gridTemplateColumns: '1fr auto auto' }}>
          <Input
            placeholder="Paste Colab URL"
            value={urlDraft}
            onChange={(e) => setUrlDraft(e.target.value)}
            autoFocus
            disabled={urlSaving}
          />
          <Button size="sm" onClick={() => void submitUrlEdit()} disabled={urlSaving || !urlDraft.trim()}>
            {urlSaving ? 'Saving…' : 'Save'}
          </Button>
          <Button variant="ghost" size="sm" onClick={cancelUrlEdit} disabled={urlSaving}>
            Cancel
          </Button>
        </div>
      ) : null}
      {originalColabUrl ? (
        <div className="flex items-center gap-1.5 border-b border-border bg-paper-2/40 px-3 py-1.5 text-[12px] text-ink-3">
          <span>Originally submitted:</span>
          <a
            href={originalColabUrl}
            target="_blank"
            rel="noreferrer"
            className="truncate text-ink-2 underline-offset-2 hover:text-forest hover:underline"
            title={originalColabUrl}
          >
            {originalColabUrl}
          </a>
        </div>
      ) : null}
      {showKey === 'files' && primaryFiles.length > 1 ? (
        <div className="flex flex-wrap gap-1.5 border-b border-border bg-paper-2/40 px-3 py-2">
          {primaryFiles.map((a) => {
            const selected = selectedId === a.id;
            return (
              <button
                key={a.id}
                onClick={() => setSelectedId(a.id)}
                className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12px] transition ${
                  selected
                    ? 'border-forest bg-forest-tint text-forest'
                    : 'border-border bg-card text-ink-2 hover:text-ink'
                }`}
                title={a.filename}
              >
                <span aria-hidden>{fileIcon(a.filename)}</span>
                <span className="max-w-[260px] truncate">{a.filename}</span>
                <span className="text-ink-3">{formatBytes(a.size_bytes)}</span>
              </button>
            );
          })}
        </div>
      ) : null}
      <div className="bg-white" style={{ height }}>
        {showKey === 'notebook' ? (
          htmlDoc ? (
            <iframe
              title="executed-notebook"
              sandbox="allow-same-origin"
              className="h-full w-full bg-white"
              srcDoc={htmlDoc}
            />
          ) : (
            <EmptyArtifact title="No executed notebook yet" body="Queue a run from the runs panel below to generate one." />
          )
        ) : showFile ? (
          <FileViewer artifact={showFile} />
        ) : (
          <EmptyArtifact title="No files yet" body="Files appear here once a submission ZIP has been ingested." />
        )}
      </div>
    </div>
  );
}

function EmptyArtifact({ title, body }: { title: string; body: string }) {
  return (
    <div className="grid h-full place-items-center px-6 text-center">
      <div className="max-w-sm">
        <div className="mx-auto mb-2 grid h-14 w-14 place-items-center rounded-full bg-terracotta-tint text-terracotta">
          ✦
        </div>
        <div className="font-display text-lg text-ink">{title}</div>
        <div className="mt-1 text-sm text-ink-3">{body}</div>
      </div>
    </div>
  );
}

/* ===== Rubric panel ===== */

function RubricPanel(props: SharedProps & { embedded?: boolean }) {
  const { components, rubricValues, setRubricValues, saveRubric, embedded } = props;
  if (components.length === 0) {
    return (
      <div className={embedded ? '' : 'mb-3.5 rounded-lg border border-border bg-card p-[22px] shadow-soft'}>
        <div className="font-display text-lg">No rubric for HW1</div>
        <div className="mt-1 text-sm text-ink-3">
          HW1 is binary — completed or not. Just confirm and move on.
        </div>
      </div>
    );
  }

  return (
    <div className={embedded ? '' : 'mb-3.5 rounded-lg border border-border bg-card p-[22px] shadow-soft'}>
      {!embedded ? (
        <>
          <div className="mb-3 flex items-baseline justify-between">
            <div>
              <div className="font-display text-[19px]">Rubric</div>
              <div className="text-[13px] text-ink-3">
                Click a dot or press 0–5 to score. Autosaves as you go.
              </div>
            </div>
            <SaveStatus saving={props.rubricSaving} savedAt={props.rubricSavedAt} dirty={props.rubricDirty} />
          </div>
          <div className="hint hint-soft mb-3">
            <span className="hint-icon" style={{ background: 'var(--terracotta)' }}>
              ✦
            </span>
            <span>
              Score every dimension you can — partial rubrics still save. The curve in step 3 turns these 0–5 dots into
              0–100 scores.
            </span>
          </div>
        </>
      ) : null}

      <div className="grid gap-3.5">
        {components.map((comp) => {
          const reportZeroed =
            comp === 'project_report' &&
            (!!props.detail.submission.requirements?.missing_report_flag ||
              props.detail.submission.requirements?.has_pdf === false);
          return (
            <div key={comp}>
              {reportZeroed ? (
                <div className="mb-1.5 rounded-md border border-terracotta/40 bg-terracotta-tint px-3 py-2 text-[12px] text-ink-2">
                  Report PDF missing — <strong>project_report</strong> is forced to 0 in the gradebook regardless of the
                  scores below. Upload a PDF or clear the &quot;Mark missing&quot; flag to restore scoring.
                </div>
              ) : null}
              <RubricGroup
                component={comp}
                rubric={rubricValues}
                approved={props.rubricApproved}
                setRubricEntry={props.setRubricEntry}
                setRubricApproval={props.setRubricApprovalFor}
                llmDimensions={
                  comp === 'project_report'
                    ? props.detail.llm_review?.dimensions
                    : (comp === 'hw2_code' || comp === 'project_code')
                      ? props.detail.code_review?.dimensions
                      : undefined
                }
                submissionId={props.detail.submission.id}
                onRescored={props.refresh}
                setToast={props.setToast}
              />
            </div>
          );
        })}
      </div>

      {!embedded ? (
        <div className="mt-3.5 flex items-center justify-between">
          <div className="text-[12px] text-ink-3">
            <Kbd>←</Kbd>
            <Kbd>→</Kbd> between dots, <Kbd>0</Kbd>–<Kbd>5</Kbd> to score
          </div>
          <Button variant="ghost" size="sm" onClick={saveRubric}>
            Save now
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function RubricGroup({
  component,
  rubric,
  approved,
  setRubricEntry,
  setRubricApproval,
  llmDimensions,
  submissionId,
  onRescored,
  setToast
}: {
  component: string;
  rubric: Record<string, number>;
  approved: Record<string, boolean>;
  setRubricEntry: (key: string, value: number) => void;
  setRubricApproval: (key: string, approved: boolean) => void;
  llmDimensions?: Record<string, { score: number; rationale: string; source?: 'auto' | 'claude' }>;
  submissionId: number;
  onRescored: () => Promise<void>;
  setToast: (m: string) => void;
}) {
  const dims = DIMENSIONS[component] || [];
  const scored = dims.filter((d) => rubric[`${component}:${d}`] != null);
  const approvedCount = scored.filter((d) => approved[`${component}:${d}`] !== false).length;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <div className="text-[13px] font-medium capitalize text-ink">{component.replace(/_/g, ' ')}</div>
        <div className="tnum text-[11px] text-ink-3">
          {approvedCount}/{scored.length}/{dims.length}
          <span className="ml-1 text-ink-4" title="approved / scored / total">·</span>
        </div>
      </div>
      <div className="rounded-[10px] bg-paper-2 px-3.5">
        {dims.map((d, i) => {
          const key = `${component}:${d}`;
          const val = rubric[key];
          const isApproved = val != null && approved[key] !== false;
          const isUnapproved = val != null && approved[key] === false;
          const llm = llmDimensions?.[d];
          return (
            <div
              key={d}
              className="py-1.5"
              style={{ borderBottom: i < dims.length - 1 ? '1px solid var(--line-soft)' : 'none' }}
            >
              <div className="grid items-center gap-2.5" style={{ gridTemplateColumns: 'auto 1fr auto auto' }}>
                <ApprovalTick
                  state={val == null ? 'empty' : isApproved ? 'approved' : 'unapproved'}
                  onClick={() => {
                    if (val == null) return;
                    setRubricApproval(key, !isApproved);
                  }}
                />
                <div
                  className="text-[13px]"
                  style={{ color: val != null ? 'var(--ink)' : 'var(--ink-2)' }}
                >
                  {LABELS[d] || d.replace(/_/g, ' ')}
                  {isUnapproved ? (
                    <span className="ml-1.5 text-[10px] uppercase tracking-wider text-warn">auto</span>
                  ) : null}
                </div>
                <DotScale
                  value={val}
                  onChange={(v) => setRubricEntry(key, v)}
                />
                {isLlmScored(component, d) ? (
                  <RescoreButton
                    submissionId={submissionId}
                    component={component}
                    dimensionKey={d}
                    onDone={onRescored}
                    setToast={setToast}
                  />
                ) : (
                  <div style={{ width: 20 }} />
                )}
              </div>
              {llm ? (() => {
                const isAuto = llm.source === 'auto';
                const accent = isAuto ? 'var(--forest)' : 'var(--terracotta)';
                const tint = isAuto ? 'bg-forest-tint text-forest' : 'bg-terracotta-tint text-terracotta';
                const label = isAuto ? 'Auto' : 'Claude';
                const isHebrew = /[֐-׿]/.test(llm.rationale);
                const rationaleStyle: React.CSSProperties = isHebrew
                  ? { fontFamily: 'Frank Ruhl Libre, Newsreader, serif' }
                  : {};
                return (
                  <div
                    className="mt-1 rounded-md bg-card/60 px-2 py-1.5 text-[12px] text-ink-2"
                    style={{
                      direction: isHebrew ? 'rtl' : 'ltr',
                      textAlign: isHebrew ? 'right' : 'left',
                      borderInlineStart: `2px solid ${accent}`
                    }}
                    title={`${label} suggests ${llm.score}/5`}
                  >
                    <span
                      className={`me-1.5 inline-block rounded-full ${tint} px-1.5 py-px text-[10px] font-semibold tnum`}
                      style={{ direction: 'ltr' }}
                    >
                      {label} · {llm.score}/5
                    </span>
                    <span style={rationaleStyle}>{llm.rationale}</span>
                  </div>
                );
              })() : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ApprovalTick({
  state,
  onClick
}: {
  state: 'empty' | 'approved' | 'unapproved';
  onClick: () => void;
}) {
  const empty = state === 'empty';
  const approved = state === 'approved';
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={empty}
      title={
        empty
          ? 'Score this dimension first'
          : approved
            ? 'Approved — click to mark unapproved'
            : 'Click to approve this score'
      }
      className="inline-flex h-5 w-5 items-center justify-center rounded-full transition disabled:cursor-not-allowed"
      style={{
        background: approved ? 'var(--ok)' : 'transparent',
        border: empty
          ? '1.5px dashed var(--ink-4)'
          : approved
            ? '1.5px solid var(--ok)'
            : '1.5px dashed var(--warn)',
        color: approved ? '#fff' : empty ? 'var(--ink-4)' : 'var(--warn)',
        fontSize: 11,
        lineHeight: 1
      }}
    >
      {empty ? '' : '✓'}
    </button>
  );
}

function RescoreButton({
  submissionId,
  component,
  dimensionKey,
  onDone,
  setToast
}: {
  submissionId: number;
  component: string;
  dimensionKey: string;
  onDone: () => Promise<void>;
  setToast: (m: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      disabled={busy}
      onClick={async (e) => {
        e.stopPropagation();
        setBusy(true);
        setToast('Re-running LLM…');
        try {
          await apiPost(
            `/api/submissions/${submissionId}/rubric/${component}/${dimensionKey}/rescore-llm`
          );
          await onDone();
          setToast('Re-scored');
        } catch (err) {
          const raw = (err as Error).message || 'Re-score failed';
          let detail = raw;
          try {
            detail = JSON.parse(raw).detail || raw;
          } catch {
            /* not JSON */
          }
          setToast(`Re-score failed: ${detail}`);
        } finally {
          setBusy(false);
        }
      }}
      title={busy ? 'Re-scoring…' : 'Re-run LLM for this dimension'}
      className="inline-flex h-5 w-5 items-center justify-center rounded-full text-ink-3 transition hover:bg-paper-2 hover:text-ink disabled:opacity-40"
    >
      <svg
        width="11"
        height="11"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={busy ? 'animate-spin' : undefined}
      >
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
        <path d="M21 3v5h-5" />
        <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
        <path d="M3 21v-5h5" />
      </svg>
    </button>
  );
}

/* ===== Notes panel ===== */

function NotesPanel({
  notes,
  setNotes,
  feedback,
  setFeedback,
  saveNotes,
  notesSaving,
  notesSavedAt,
  notesDirty,
  embedded
}: {
  notes: string;
  setNotes: (v: string) => void;
  feedback: string;
  setFeedback: (v: string) => void;
  saveNotes: () => void;
  notesSaving: boolean;
  notesSavedAt: Date | null;
  notesDirty: boolean;
  embedded?: boolean;
}) {
  return (
    <div className={embedded ? '' : 'mb-3.5 rounded-lg border border-border bg-card p-[22px] shadow-soft'}>
      {!embedded ? (
        <>
          <div className="mb-2 flex items-baseline justify-between">
            <div className="font-display text-[19px]">Notes</div>
            <SaveStatus saving={notesSaving} savedAt={notesSavedAt} dirty={notesDirty} />
          </div>
          <div className="hint hint-soft mb-3">
            <span className="hint-icon" style={{ background: 'var(--ink-3)' }}>
              ·
            </span>
            <span>
              Two separate fields. Private notes are for your eyes (next term, edge cases). Student-facing feedback is
              rendered into the Hebrew PDF report. Autosaves while you type.
            </span>
          </div>
        </>
      ) : null}

      <div className="mb-3">
        <Label>
          Private notes <span className="text-ink-4">(only you see these)</span>
        </Label>
        <Textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={saveNotes}
          placeholder="Anything to remember next term…"
        />
      </div>
      <div>
        <Label>
          Student-facing feedback <span className="text-ink-4">(printed in PDF report)</span>
        </Label>
        <Textarea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          onBlur={saveNotes}
          placeholder="What the students will read."
        />
      </div>
      {embedded ? (
        <div className="mt-2 flex justify-end">
          <SaveStatus saving={notesSaving} savedAt={notesSavedAt} dirty={notesDirty} inline />
        </div>
      ) : null}
    </div>
  );
}

/* ===== Data files panel ===== */

function DataFilesPanel({ detail }: { detail: SubmissionDetail }) {
  const dataFiles = detail.artifacts.filter((a) => AUXILIARY_KINDS.has(a.kind));
  if (dataFiles.length === 0) return null;
  return (
    <div className="mt-3.5 rounded-lg border border-border bg-card p-[18px] shadow-soft">
      <div className="mb-2 flex items-baseline justify-between">
        <div>
          <div className="font-display text-[15px]">Data files</div>
          <div className="text-[12px] text-ink-3">
            Auxiliary files staged into the notebook's working directory at run time.
          </div>
        </div>
        <span className="tnum text-[11px] text-ink-3">{dataFiles.length}</span>
      </div>
      <div className="grid gap-1.5">
        {dataFiles.map((a) => (
          <div
            key={a.id}
            className="grid items-center gap-3 rounded-md border border-line-soft bg-paper-2/40 px-3 py-2"
            style={{ gridTemplateColumns: '24px 1fr auto auto' }}
          >
            <span aria-hidden>{fileIcon(a.filename)}</span>
            <div className="min-w-0">
              <div className="truncate text-[13px] text-ink" title={a.filename}>
                {a.filename}
              </div>
              <div className="text-[11px] text-ink-3">
                data · {formatBytes(a.size_bytes)}
              </div>
            </div>
            <a
              className="text-[12px] text-forest hover:underline"
              href={`${apiBase()}/api/artifacts/${a.id}?inline=1`}
              target="_blank"
              rel="noreferrer"
            >
              Open
            </a>
            <a
              className="text-[12px] text-forest hover:underline"
              href={`${apiBase()}/api/artifacts/${a.id}`}
              download={a.filename}
            >
              Download
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ===== Runs panel ===== */

function RunsPanel({
  detail,
  queueRun,
  pinRun,
  now,
  compact,
  embedded
}: {
  detail: SubmissionDetail;
  queueRun: (mode: 'snapshot' | 'latest') => void;
  pinRun: (id: number) => void;
  now: number;
  compact?: boolean;
  embedded?: boolean;
}) {
  const runs = detail.runs;
  const fetchedSnapshots = detail.snapshots.filter(
    (s) => s.status === 'PUBLIC_FETCHED' || s.status === 'PRIVATE_FETCHED'
  );
  const hasFetched = fetchedSnapshots.length > 0;
  const hasAnySnapshot = detail.snapshots.length > 0;

  // Most recent snapshot — used to show a "Fetching from Colab…" strip while
  // a 'latest' run is waiting on its Colab fetch.
  const latestSnapshot = detail.snapshots[0];
  const snapshotInFlight =
    latestSnapshot && SNAP_INFLIGHT.has(latestSnapshot.status) ? latestSnapshot : null;

  return (
    <div className={embedded ? '' : 'rounded-lg border border-border bg-card p-[22px] shadow-soft'}>
      {!embedded ? (
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="font-display text-[17px]">Run history</div>
            <div className="text-[13px] text-ink-3">
              {runs.length} {runs.length === 1 ? 'run' : 'runs'} for this submission
              {!hasAnySnapshot ? (
                <span className="ml-1.5 text-warn">
                  · no Colab URL yet — paste one above
                </span>
              ) : !hasFetched && !snapshotInFlight ? (
                <span className="ml-1.5 text-warn">
                  · waiting for snapshot fetch ({detail.snapshots[0]?.status?.toLowerCase()})
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              disabled={!hasFetched}
              onClick={() => queueRun('snapshot')}
              title={hasFetched ? 'Re-execute the most recent fetched snapshot' : 'No fetched snapshot to run'}
            >
              ▶ Run snapshot
            </Button>
            <Button
              variant="soft"
              size="sm"
              disabled={!hasAnySnapshot}
              onClick={() => queueRun('latest')}
              title={hasAnySnapshot ? 'Re-fetch from Colab and run again' : 'Add a Colab URL first'}
            >
              Fetch latest + run
            </Button>
          </div>
        </div>
      ) : (
        <div className="mb-2 text-[13px] font-medium">Runs</div>
      )}

      {snapshotInFlight ? (
        <div
          className="mb-2 flex items-center gap-2.5 rounded-md p-2.5 text-[13px]"
          style={{
            background: 'var(--info-soft)',
            color: 'var(--info)'
          }}
        >
          <span
            className="inline-block h-2 w-2 animate-pulse rounded-full"
            style={{ background: 'var(--info)' }}
          />
          <span>
            Fetching from Colab…{' '}
            <span className="text-ink-3">({snapshotInFlight.status.toLowerCase()})</span>
          </span>
        </div>
      ) : null}

      {runs.length === 0 ? (
        <div className="px-2 py-1 text-[13px] text-ink-3">
          {hasAnySnapshot
            ? 'No runs yet. Click ▶ to execute the snapshot.'
            : 'No Colab snapshot — paste a URL above first.'}
        </div>
      ) : (
        <div className="grid gap-2">
          {runs.map((r) => {
            const inFlight = isRunInFlight(r.status);
            const ranIn =
              !inFlight && r.started_at && r.ended_at
                ? formatElapsed(parseServerTime(r.ended_at) - parseServerTime(r.started_at))
                : null;
            return (
              <div
                key={r.id}
                className="relative grid items-center gap-3 overflow-hidden rounded-md p-2.5"
                style={{
                  gridTemplateColumns: 'auto 1fr auto auto',
                  background: r.is_pinned ? 'var(--forest-tint)' : 'var(--paper-2)',
                  border: r.is_pinned ? '1px solid var(--forest-soft)' : '1px solid transparent'
                }}
              >
                <span
                  className={`inline-block rounded-full ${inFlight ? 'h-2 w-2 animate-pulse' : 'h-1.5 w-1.5'}`}
                  style={{
                    background: inFlight
                      ? 'var(--info)'
                      : r.status === 'SUCCESS'
                        ? 'var(--ok)'
                        : r.status === 'TIMEOUT'
                          ? 'var(--warn)'
                          : 'var(--bad)'
                  }}
                />
                <div>
                  <div className="flex items-center gap-1.5 text-[13px]">
                    Run <span className="tnum">#{r.id}</span>
                    {r.status === 'QUEUED' ? (
                      <span className="pill pill-info">Queued…</span>
                    ) : r.status === 'RUNNING' ? (
                      <span className="pill pill-info tnum">
                        Running… {elapsedFrom(r.started_at, now)}
                      </span>
                    ) : r.status === 'TIMEOUT' ? (
                      <span className="pill pill-warn">Timed out</span>
                    ) : r.status === 'FAILED' ? (
                      <span className="pill pill-bad">Failed</span>
                    ) : null}
                    {r.is_pinned ? <span className="pill pill-forest">📍 Pinned</span> : null}
                  </div>
                  <div className="text-[11px] text-ink-3">
                    {r.status === 'QUEUED'
                      ? 'Waiting for worker'
                      : r.status === 'RUNNING'
                        ? 'Executing notebook (timeout 15:00)'
                        : `${r.ok_cells} ok, ${r.failed_cells} failed${ranIn ? ` · ran in ${ranIn}` : ''}`}
                  </div>
                  {r.error_summary && !inFlight ? (
                    <div className="mt-0.5 text-[12px] text-bad">{r.error_summary}</div>
                  ) : null}
                </div>
                <div className="text-right">
                  <div className="font-display tnum text-lg">
                    {inFlight ? '—' : r.run_ratio != null ? `${Math.round(r.run_ratio * 100)}%` : '—'}
                  </div>
                  <div className="text-[11px] text-ink-3">cells ran</div>
                </div>
                {inFlight ? (
                  <span className="w-10" />
                ) : !r.is_pinned ? (
                  <button
                    onClick={() => pinRun(r.id)}
                    className="text-[13px] text-forest hover:underline"
                  >
                    Pin
                  </button>
                ) : (
                  <span className="w-10" />
                )}
                {inFlight ? (
                  <div
                    className="absolute inset-x-0 bottom-0 h-0.5 animate-pulse"
                    style={{ background: 'var(--info)', opacity: 0.45 }}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ===== LLM review card (Claude Sonnet 4.6) ===== */

function LLMReviewCard({
  detail,
  refresh,
  setToast,
  setFeedback,
  embedded
}: SharedProps & { embedded?: boolean }) {
  const isProject = detail.submission.assignment_type === 'PROJECT';
  const review = detail.llm_review;
  const [running, setRunning] = useState(false);

  if (!isProject) return null;

  const run = async () => {
    setRunning(true);
    setToast('Running Claude review… this takes 10–30s');
    try {
      await apiPost(`/api/submissions/${detail.submission.id}/llm-review`);
      // Auto-apply suggested scores into the rubric (with approved=false so
      // they show as "auto" and the grader still has to confirm each one).
      try {
        await apiPost(`/api/submissions/${detail.submission.id}/llm-review/apply`);
      } catch (e) {
        // Non-fatal — the rationales still show as side annotations even if apply fails
        // eslint-disable-next-line no-console
        console.warn('llm-review/apply failed', e);
      }
      setToast('Claude review applied — confirm each ✓ on the rubric');
      await refresh();
    } catch (e) {
      const msg = (e as Error).message || '';
      const detail = (() => {
        try {
          return JSON.parse(msg).detail as string;
        } catch {
          return msg;
        }
      })();
      setToast(`LLM review failed: ${detail || 'unknown error'}`);
    } finally {
      setRunning(false);
    }
  };

  const useFeedback = () => {
    if (!review) return;
    setFeedback(review.feedback_he);
    setToast('Pasted into student feedback — review and save');
  };

  return (
    <div className={embedded ? '' : 'mb-3.5 rounded-lg border border-border bg-card p-[18px] shadow-soft'}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div className="font-display text-[15px]">Claude review</div>
        {review ? (
          <span className="text-[11px] text-ink-3">{review.model}</span>
        ) : (
          <span className="text-[11px] text-ink-3">Sonnet 4.6 · ~$0.05</span>
        )}
      </div>
      {!review ? (
        <>
          <div className="mb-2.5 text-[12px] text-ink-3">
            Reads the report PDF + executed notebook and suggests 0–5 scores per project_report dimension (with Hebrew
            rationales) plus a draft feedback paragraph. Suggestions appear next to each dot row — they don't
            auto-fill.
          </div>
          <Button size="sm" onClick={run} disabled={running}>
            {running ? 'Reviewing…' : '✦ Suggest with Claude'}
          </Button>
        </>
      ) : (
        <>
          <div className="mb-2 text-[12px] text-ink-3">
            Suggested scores are shown next to each rubric dimension. The Hebrew feedback draft is below — click
            "Use" to paste it into the student feedback field.
          </div>
          <div
            className="mb-2 rounded-md bg-paper-2/60 px-3 py-2.5 text-[13px] leading-relaxed text-ink"
            style={{
              direction: 'rtl',
              textAlign: 'right',
              fontFamily: 'Frank Ruhl Libre, Newsreader, serif'
            }}
          >
            {review.feedback_he}
          </div>
          <div className="flex items-center justify-between gap-2">
            <Button variant="ghost" size="sm" onClick={run} disabled={running}>
              {running ? 'Re-running…' : 'Re-run'}
            </Button>
            <Button size="sm" onClick={useFeedback}>
              Use this feedback →
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

/* ===== Manual grade card ===== */

function ManualGradeCard({
  detail,
  refresh,
  setToast,
  embedded
}: SharedProps & { embedded?: boolean }) {
  const stored = detail.submission.manual_grade;
  const assignmentType = detail.submission.assignment_type;
  const [draft, setDraft] = useState<string>(stored != null ? String(stored) : '');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setDraft(stored != null ? String(stored) : '');
  }, [stored]);

  const dirty = draft.trim() !== (stored != null ? String(stored) : '');
  const componentLabel =
    assignmentType === 'HW1'
      ? 'HW1 grade'
      : assignmentType === 'HW2'
        ? 'HW2 grade'
        : 'project grade (replaces 50/20/10/20 weighted blend)';

  const save = async () => {
    setSaving(true);
    try {
      const trimmed = draft.trim();
      const value = trimmed === '' ? null : Number(trimmed);
      if (value !== null && (Number.isNaN(value) || value < 0 || value > 100)) {
        setToast('Grade must be a number 0–100');
        return;
      }
      await apiPatch(`/api/submissions/${detail.submission.id}/manual-grade`, {
        manual_grade: value
      });
      setToast(value === null ? 'Manual grade cleared' : `Manual grade set to ${value}`);
      await refresh();
    } catch (e) {
      setToast(`Couldn't save grade: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const clear = async () => {
    setDraft('');
    setSaving(true);
    try {
      await apiPatch(`/api/submissions/${detail.submission.id}/manual-grade`, {
        manual_grade: null
      });
      setToast('Manual grade cleared — back to rubric');
      await refresh();
    } catch (e) {
      setToast(`Couldn't clear grade: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={embedded ? '' : 'mb-3.5 rounded-lg border border-border bg-card p-[18px] shadow-soft'}>
      {!embedded ? (
        <div className="mb-2 flex items-baseline justify-between">
          <div className="font-display text-[15px]">Manual grade</div>
          {stored != null ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-forest-tint px-2 py-px text-[11px] text-forest">
              ✓ Overriding rubric · {stored}
            </span>
          ) : (
            <span className="text-[11px] text-ink-3">using rubric</span>
          )}
        </div>
      ) : (
        <div className="mb-2 text-[13px] font-medium">Manual grade</div>
      )}
      {!embedded ? (
        <div className="mb-2.5 text-[12px] text-ink-3">
          Type a 0–100 score to override the {componentLabel}. Applies to every member of this group. Leave blank to
          keep using the rubric.
        </div>
      ) : null}
      <div className="flex items-center gap-2">
        <Input
          type="number"
          min={0}
          max={100}
          step={0.5}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void save();
          }}
          placeholder="—"
          className="w-24"
        />
        <span className="text-[13px] text-ink-3">/ 100</span>
        <div className="ml-auto flex gap-1.5">
          {stored != null ? (
            <Button variant="ghost" size="sm" onClick={clear} disabled={saving}>
              Clear
            </Button>
          ) : null}
          <Button size="sm" onClick={save} disabled={saving || !dirty}>
            {saving ? 'Saving…' : 'Save grade'}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ===== Missing flags card (manual report/data flags) ===== */

function MissingFlagsCard({
  detail,
  refresh,
  setToast,
  embedded
}: SharedProps & { embedded?: boolean }) {
  const req = detail.submission.requirements;
  const reportFlagged = !!req?.missing_report_flag;
  const dataFlagged = !!req?.missing_data_flag;
  const codeFlagged = !!req?.missing_code_flag;
  const [saving, setSaving] = useState<'report' | 'data' | 'code' | null>(null);

  const toggle = async (which: 'report' | 'data' | 'code') => {
    setSaving(which);
    const wasFlagged =
      which === 'report' ? reportFlagged : which === 'data' ? dataFlagged : codeFlagged;
    try {
      const body =
        which === 'report'
          ? { missing_report_flag: !reportFlagged }
          : which === 'data'
            ? { missing_data_flag: !dataFlagged }
            : { missing_code_flag: !codeFlagged };
      await apiPatch(`/api/submissions/${detail.submission.id}/flags`, body);
      setToast(
        wasFlagged
          ? `Cleared: missing ${which}`
          : `Marked: missing ${which}`
      );
      await refresh();
    } catch (e) {
      setToast(`Couldn't update flag: ${(e as Error).message}`);
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className={embedded ? '' : 'mb-3.5 rounded-lg border border-border bg-card p-[18px] shadow-soft'}>
      {!embedded ? (
        <>
          <div className="mb-1 font-display text-[15px]">Mark missing</div>
          <div className="mb-3 text-[12px] text-ink-3">
            Flag this submission as missing the report or the data, even if a file exists. Shows up in the queue and the
            requirements pill above.
          </div>
        </>
      ) : (
        <div className="mb-2 text-[13px] font-medium">Mark missing</div>
      )}
      <div className="grid gap-2">
        <FlagButton
          label="Report"
          flagged={reportFlagged}
          saving={saving === 'report'}
          onClick={() => toggle('report')}
        />
        <FlagButton
          label="Code"
          flagged={codeFlagged}
          saving={saving === 'code'}
          onClick={() => toggle('code')}
        />
        <FlagButton
          label="Data"
          flagged={dataFlagged}
          saving={saving === 'data'}
          onClick={() => toggle('data')}
        />
      </div>
    </div>
  );
}

function FlagButton({
  label,
  flagged,
  saving,
  onClick
}: {
  label: string;
  flagged: boolean;
  saving: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={saving}
      className={`flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-[13px] transition disabled:opacity-60 ${
        flagged
          ? 'border-warn-soft bg-warn-soft text-warn'
          : 'border-border bg-card text-ink-2 hover:border-ink-4 hover:text-ink'
      }`}
      title={flagged ? `Click to clear "missing ${label}"` : `Mark this submission as missing ${label}`}
    >
      <span className="inline-flex items-center gap-2">
        <span aria-hidden>{flagged ? '⚠' : '⊘'}</span>
        <span>
          {flagged ? `Missing ${label}` : `Mark ${label} missing`}
        </span>
      </span>
      <span className="text-[11px] text-ink-3">
        {saving ? 'Saving…' : flagged ? 'Tap to clear' : ''}
      </span>
    </button>
  );
}

/* ===== Override card (per-student delta) ===== */

const OVERRIDE_COMPONENTS = [
  'hw1',
  'hw2',
  'project_code',
  'project_report',
  'presentation',
  'final_talk',
  'attendance',
  'bonus'
];

function OverrideCard({
  detail,
  courseId,
  refresh,
  setToast,
  embedded
}: SharedProps & { embedded?: boolean }) {
  const sub = detail.submission;
  const [studentId, setStudentId] = useState<number | null>(sub.member_student_ids[0] ?? null);
  const [component, setComponent] = useState('bonus');
  const [delta, setDelta] = useState('0');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setStudentId(sub.member_student_ids[0] ?? null);
  }, [sub.member_student_ids]);

  const submit = async () => {
    if (studentId == null || !reason.trim()) {
      setToast('Override needs a student and a reason');
      return;
    }
    const numericDelta = Number(delta);
    if (Number.isNaN(numericDelta)) {
      setToast('Delta must be a number');
      return;
    }
    setSaving(true);
    try {
      await apiPost(`/api/courses/${courseId}/overrides`, {
        student_id: studentId,
        submission_id: sub.id,
        component,
        delta: numericDelta,
        reason
      });
      setReason('');
      setDelta('0');
      setToast('Override saved');
      await refresh();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={embedded ? '' : 'mb-3.5 rounded-lg border border-border bg-card p-[22px] shadow-soft'}>
      {!embedded ? (
        <>
          <div className="mb-2 font-display text-[19px]">Per-student override</div>
          <div className="text-[13px] text-ink-3">
            Add a delta tied to this submission. Reasons are required and visible in the audit log.
          </div>
        </>
      ) : (
        <div className="mb-2 text-[13px] font-medium">Override</div>
      )}
      <div className="mt-2.5 grid gap-2">
        <select
          className="rounded-md border border-border bg-card px-3 py-2 text-sm"
          value={studentId ?? ''}
          onChange={(e) => setStudentId(Number(e.target.value))}
        >
          {sub.member_student_ids.map((id, i) => (
            <option key={id} value={id}>
              {sub.member_names[i] || '—'} · {sub.member_ids[i]}
            </option>
          ))}
        </select>
        <div className="grid grid-cols-2 gap-2">
          <select
            className="rounded-md border border-border bg-card px-3 py-2 text-sm"
            value={component}
            onChange={(e) => setComponent(e.target.value)}
          >
            {OVERRIDE_COMPONENTS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <Input
            type="number"
            step="0.1"
            value={delta}
            onChange={(e) => setDelta(e.target.value)}
            placeholder="Delta"
          />
        </div>
        <Input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason (required, written to audit log)"
        />
        <Button variant="soft" size="sm" onClick={submit} disabled={saving}>
          {saving ? 'Saving…' : 'Save override'}
        </Button>
      </div>
    </div>
  );
}

/* ===== Consistency panel ===== */

function ConsistencyPanel({ detail }: { detail: SubmissionDetail }) {
  if (detail.submission.assignment_type !== 'PROJECT') return null;
  const flags = detail.consistency_flags;
  const summary = detail.consistency_summary;
  return (
    <div className="mb-3.5 rounded-lg border border-border bg-card p-[22px] shadow-soft">
      <div className="mb-2 font-display text-[17px]">Consistency signals</div>
      {flags.length === 0 ? (
        <div className="inline-flex items-center gap-1.5 text-[13px] text-ok">
          ✓ {summary || 'Report and code look consistent'}
        </div>
      ) : (
        <div className="grid gap-1.5">
          {flags.map((f, i) => (
            <div
              key={i}
              className="flex items-start gap-2 rounded-md p-2 text-[13px]"
              style={{ background: 'var(--bad-soft)', color: 'var(--bad)' }}
            >
              <span>⚑</span>
              <span>{f}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
