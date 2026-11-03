'use client';

import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { apiDelete, apiPost, apiPut, errorMessage } from '@/lib/api';

/* Review of one submission against its assignment's custom rubric: the LLM's
 * score and rationale per criterion, and the instructor's override, which
 * wins and survives re-runs. Rationales are Hebrew, so they follow the text
 * direction. */

export type CustomRubricCriterion = {
  id: number;
  name: string;
  description: string;
  max_points: number;
  levels: { points: number; description: string }[];
  status: 'scored' | 'not_scored';
  llm_score: number | null;
  rationale: string;
  run_id: number | null;
  error: string;
  last_attempt_failed: boolean;
  override: { score: number; note: string } | null;
  effective_score: number | null;
  source: 'override' | 'llm' | null;
};

export type CustomRubricView = {
  criteria: CustomRubricCriterion[];
  total: number;
  max_total: number;
  percent: number;
  not_scored: number;
  penalty_multiplier: number;
  component_score: number;
};

const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

export function CustomRubricCard({
  submissionId,
  view,
  refresh,
  setToast
}: {
  submissionId: number;
  view: CustomRubricView;
  refresh: () => Promise<void>;
  setToast: (m: string) => void;
}) {
  const [scoring, setScoring] = useState(false);

  const scoreNow = async () => {
    setScoring(true);
    try {
      await apiPost(`/api/submissions/${submissionId}/custom-rubric/score`);
      setToast('Scoring with the LLM…');
      // The worker picks the job up within seconds; check back a few times.
      for (const wait of [4000, 8000, 15000]) {
        await new Promise((r) => setTimeout(r, wait));
        await refresh();
      }
    } catch (e) {
      setToast(errorMessage(e));
    } finally {
      setScoring(false);
    }
  };

  return (
    <div className="mb-3.5 rounded-lg border border-border bg-card p-[22px] shadow-soft" data-testid="custom-rubric">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <div>
          <div className="font-display text-[19px]">Custom rubric</div>
          <div className="text-[13px] text-ink-3">
            Claude scores each criterion from the executed notebook. Your override wins and survives re-runs.
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="tnum font-display text-[22px]">
            {fmt(view.total)} <span className="text-ink-3">/ {fmt(view.max_total)}</span>
          </div>
          <div className="tnum text-[11px] text-ink-3" title="percent × run-ratio penalty = gradebook score">
            {fmt(view.percent)}% × {view.penalty_multiplier.toFixed(2)} = {fmt(view.component_score)}
          </div>
        </div>
      </div>
      {view.not_scored ? (
        <div className="mb-3 flex items-center justify-between gap-2 rounded-md border border-terracotta/40 bg-terracotta-tint px-3 py-2 text-[12px] text-ink-2">
          <span>
            {view.not_scored} of {view.criteria.length} criteria not scored; they count as 0 until scored or overridden.
          </span>
          <Button variant="outline" size="sm" disabled={scoring} onClick={() => void scoreNow()}>
            {scoring ? 'Scoring…' : 'Score with LLM'}
          </Button>
        </div>
      ) : null}
      <div className="rounded-[10px] bg-paper-2 px-3.5">
        {view.criteria.map((c, i) => (
          <CriterionRow
            key={c.id}
            submissionId={submissionId}
            criterion={c}
            last={i === view.criteria.length - 1}
            refresh={refresh}
            setToast={setToast}
          />
        ))}
      </div>
      {!view.not_scored ? (
        <div className="mt-3 flex justify-end">
          <Button variant="ghost" size="sm" disabled={scoring} onClick={() => void scoreNow()}>
            {scoring ? 'Scoring…' : 'Re-score with LLM'}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function CriterionRow({
  submissionId,
  criterion: c,
  last,
  refresh,
  setToast
}: {
  submissionId: number;
  criterion: CustomRubricCriterion;
  last: boolean;
  refresh: () => Promise<void>;
  setToast: (m: string) => void;
}) {
  const [score, setScore] = useState(c.override ? String(c.override.score) : '');
  const [note, setNote] = useState(c.override?.note ?? '');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setScore(c.override ? String(c.override.score) : '');
    setNote(c.override?.note ?? '');
  }, [c.override]);

  const url = `/api/submissions/${submissionId}/custom-rubric/${c.id}/override`;
  const value = Number(score);
  const valid = score.trim() !== '' && value >= 0 && value <= c.max_points;
  const changed = valid && (c.override == null || value !== c.override.score || note !== c.override.note);

  const save = async () => {
    setSaving(true);
    try {
      await apiPut(url, { score: value, note });
      await refresh();
      setToast(`${c.name}: ${fmt(value)} / ${fmt(c.max_points)}`);
    } catch (e) {
      setToast(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };
  const clear = async () => {
    setSaving(true);
    try {
      await apiDelete(url);
      await refresh();
      setToast(`${c.name}: override cleared`);
    } catch (e) {
      setToast(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="py-2.5"
      style={{ borderBottom: last ? 'none' : '1px solid var(--line-soft)' }}
      data-testid="custom-criterion"
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0 text-[13px] font-medium text-ink" dir="auto" title={c.description}>
          {c.name}
        </div>
        <div className="tnum shrink-0 text-[13px]">
          {c.effective_score != null ? fmt(c.effective_score) : '—'}{' '}
          <span className="text-ink-3">/ {fmt(c.max_points)}</span>
          {c.source === 'override' ? (
            <span className="ml-1.5 text-[10px] uppercase tracking-wider text-forest">override</span>
          ) : null}
        </div>
      </div>
      {c.status === 'scored' ? (
        <div
          className="mt-1 rounded-md bg-card/60 px-2 py-1.5 text-[12px] text-ink-2"
          dir="auto"
          style={{ borderInlineStart: '2px solid var(--terracotta)' }}
        >
          <span
            className="me-1.5 inline-block rounded-full bg-terracotta-tint px-1.5 py-px text-[10px] font-semibold text-terracotta tnum"
            dir="ltr"
          >
            Claude · {fmt(c.llm_score ?? 0)}/{fmt(c.max_points)}
          </span>
          {c.rationale}
          {c.last_attempt_failed ? (
            <div className="mt-1 text-[11px] text-warn" dir="ltr">
              The latest scoring attempt failed; this is the previous score.
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-1 text-[12px] text-ink-3" title={c.error}>
          <span className="pill">Not scored</span>
          {c.error ? (
            <span className="ms-1.5">{c.error.length > 120 ? `${c.error.slice(0, 120)}…` : c.error}</span>
          ) : null}
        </div>
      )}
      <div
        className="mt-1.5 grid items-center gap-1.5"
        style={{ gridTemplateColumns: '96px minmax(0, 1fr) auto auto' }}
      >
        <Input
          className="h-8 text-[13px]"
          type="number"
          min={0}
          max={c.max_points}
          step="any"
          placeholder="Score"
          aria-label={`Override score for ${c.name}`}
          value={score}
          onChange={(e) => setScore(e.target.value)}
        />
        <Input
          className="h-8 text-[13px]"
          dir="auto"
          placeholder="Note (instructor only)"
          aria-label={`Override note for ${c.name}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button size="sm" disabled={!changed || saving} onClick={() => void save()}>
          Save
        </Button>
        <Button variant="ghost" size="sm" disabled={!c.override || saving} onClick={() => void clear()}>
          Clear
        </Button>
      </div>
    </div>
  );
}
