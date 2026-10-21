'use client';

import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { apiDelete, apiGet, apiPost, apiPut, errorMessage } from '@/lib/api';

/* Course step "Rubrics": a custom rubric per autograded assignment (HW2,
 * PROJECT). With one, the autograder scores each criterion with the LLM and
 * the gradebook uses those points instead of the fixed code dimensions.
 * Criterion text is usually Hebrew, so its fields follow the text direction. */

type Level = { points: number; description: string };
export type Criterion = {
  id?: number;
  name: string;
  description: string;
  max_points: number;
  levels: Level[];
};
type Rubric = {
  id: number;
  criteria: Required<Criterion>[];
  total_points: number;
  copied_from: { assignment_id: number; name: string } | null;
};
type RubricState = {
  assignment: { id: number; name: string; assignment_type: string; workcode: number };
  supported: boolean;
  rubric: Rubric | null;
};
type Source = {
  assignment_id: number;
  assignment_name: string;
  assignment_type: string;
  course_label: string;
  course_id: number;
  criteria_count: number;
  total_points: number;
};
type AssignmentLite = { id: number; name: string; assignment_type: string; workcode: number };

/* A draft row; `key` keeps React state stable while rows move. */
type Draft = Omit<Criterion, 'max_points'> & { key: string; max_points: string };

let draftSeq = 0;
const newKey = () => `d${++draftSeq}`;

function toDrafts(rubric: Rubric | null): Draft[] {
  return (rubric?.criteria ?? []).map((c) => ({ ...c, key: newKey(), max_points: String(c.max_points) }));
}

const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

export function RubricsStep({
  courseId,
  assignments,
  setToast,
  refresh
}: {
  courseId: number;
  assignments: AssignmentLite[];
  setToast: (m: string) => void;
  refresh: () => Promise<void>;
}) {
  const scorable = useMemo(
    () =>
      assignments
        .filter((a) => a.assignment_type === 'HW2' || a.assignment_type === 'PROJECT')
        .sort((a, b) => a.assignment_type.localeCompare(b.assignment_type) || a.workcode - b.workcode),
    [assignments]
  );
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    if (selected == null && scorable.length) setSelected(scorable[0].id);
  }, [scorable, selected]);

  if (scorable.length === 0) {
    return (
      <div className="pt-6">
        <Card>
          <div className="font-display text-[19px]">No autograded assignments yet</div>
          <div className="mt-1 text-[13px] text-ink-3">
            Import an HW2 or PROJECT assignment ZIP first. Custom rubrics apply to assignments the autograder runs.
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="grid gap-3.5 pt-6" style={{ gridTemplateColumns: '240px minmax(0, 1fr)' }}>
      <Card className="self-start p-3">
        <div className="label-eyebrow mb-2 px-1">Assignments</div>
        <div className="grid gap-1">
          {scorable.map((a) => (
            <button
              key={a.id}
              className={`rounded-md px-2.5 py-2 text-left text-[13px] ${
                selected === a.id ? 'bg-forest-tint text-forest' : 'text-ink-2 hover:bg-paper-2'
              }`}
              onClick={() => setSelected(a.id)}
            >
              <span className="font-medium">{a.assignment_type}</span> <span className="text-ink-3">· {a.name}</span>
            </button>
          ))}
        </div>
      </Card>
      {selected != null ? (
        <RubricEditor
          key={selected}
          courseId={courseId}
          assignmentId={selected}
          setToast={setToast}
          refresh={refresh}
        />
      ) : null}
    </div>
  );
}

function RubricEditor({
  courseId,
  assignmentId,
  setToast,
  refresh
}: {
  courseId: number;
  assignmentId: number;
  setToast: (m: string) => void;
  refresh: () => Promise<void>;
}) {
  const base = `/api/courses/${courseId}/assignments/${assignmentId}/rubric`;
  const [state, setState] = useState<RubricState | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [dirty, setDirty] = useState(false);
  const [sources, setSources] = useState<Source[]>([]);
  const [copyFrom, setCopyFrom] = useState('');
  const [busy, setBusy] = useState(false);

  const apply = (s: RubricState) => {
    setState(s);
    setDrafts(toDrafts(s.rubric));
    setDirty(false);
  };

  useEffect(() => {
    apiGet<RubricState>(base)
      .then(apply)
      .catch((e) => setToast(errorMessage(e)));
    apiGet<Source[]>(`/api/courses/${courseId}/rubric-sources`)
      .then((rows) => setSources(rows.filter((r) => r.assignment_id !== assignmentId)))
      .catch(() => setSources([]));
  }, [base, courseId, assignmentId, setToast]);

  const edit = (updater: (prev: Draft[]) => Draft[]) => {
    setDrafts(updater);
    setDirty(true);
  };
  const update = (key: string, patch: Partial<Draft>) =>
    edit((prev) => prev.map((d) => (d.key === key ? { ...d, ...patch } : d)));
  const move = (index: number, delta: number) =>
    edit((prev) => {
      const next = [...prev];
      const target = index + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  const remove = (key: string) => edit((prev) => prev.filter((d) => d.key !== key));
  const add = () =>
    edit((prev) => [...prev, { key: newKey(), name: '', description: '', max_points: '10', levels: [] }]);

  const total = drafts.reduce((sum, d) => sum + (Number(d.max_points) || 0), 0);
  const problems = drafts.flatMap((d, i) => {
    const out: string[] = [];
    const max = Number(d.max_points);
    if (!d.name.trim()) out.push(`Criterion ${i + 1} needs a name`);
    if (!(max > 0)) out.push(`Criterion ${i + 1} needs max points above 0`);
    if (d.levels.some((l) => !l.description.trim())) out.push(`Criterion ${i + 1} has a level without a description`);
    if (d.levels.some((l) => l.points > max)) out.push(`Criterion ${i + 1} has a level above its max`);
    return out;
  });

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setToast(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      const criteria = drafts.map((d) => ({
        ...(d.id != null ? { id: d.id } : {}),
        name: d.name.trim(),
        description: d.description,
        max_points: Number(d.max_points),
        levels: d.levels
      }));
      apply(await apiPut<RubricState>(base, { criteria }));
      setToast('Rubric saved');
      await refresh();
    });

  const deleteRubric = () =>
    run(async () => {
      if (
        !window.confirm(
          'Delete this rubric? Its criterion scores and overrides go too, and the assignment goes back to the fixed rubric.'
        )
      )
        return;
      apply(await apiDelete<RubricState>(base));
      setToast('Rubric deleted; the fixed rubric applies again');
      await refresh();
    });

  const copy = () =>
    run(async () => {
      if (!copyFrom) return;
      if (
        state?.rubric &&
        !window.confirm('Replace this rubric with the copy? Current criteria, their scores and overrides are deleted.')
      )
        return;
      apply(await apiPost<RubricState>(`${base}/copy`, { source_assignment_id: Number(copyFrom) }));
      setCopyFrom('');
      setToast('Rubric copied');
      await refresh();
    });

  const scoreAll = () =>
    run(async () => {
      const res = await apiPost<{ queued: number }>(`${base}/score`);
      setToast(
        res.queued
          ? `Scoring ${res.queued} submission${res.queued === 1 ? '' : 's'} with the LLM`
          : 'No executed notebooks to score yet'
      );
    });

  if (!state) return <div className="p-4 text-ink-3">Loading…</div>;

  return (
    <div className="grid gap-3.5">
      <Card>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="font-display text-[19px]">
              {state.assignment.assignment_type} · {state.assignment.name}
            </div>
            <div className="mt-0.5 text-[13px] text-ink-3">
              {state.rubric
                ? 'Custom rubric: the autograder scores each criterion with the LLM, and the gradebook uses these points (times the run-ratio penalty) instead of the fixed code dimensions.'
                : 'No custom rubric: the fixed code dimensions grade this assignment. Add criteria below, or copy a rubric from another assignment.'}
            </div>
            {state.rubric?.copied_from ? (
              <div className="mt-1 text-[12px] text-ink-3">Copied from {state.rubric.copied_from.name}</div>
            ) : null}
          </div>
          <div className="shrink-0 text-right">
            <div className="tnum font-display text-[24px]" data-testid="rubric-total">
              {fmt(total)}
            </div>
            <div className="text-[11px] text-ink-3">total points</div>
          </div>
        </div>

        {sources.length ? (
          <div className="mt-4 flex items-end gap-2">
            <div className="min-w-0 flex-1">
              <Label htmlFor="rubric-copy-from">Copy from another assignment</Label>
              <select
                id="rubric-copy-from"
                className="h-9 w-full rounded-md border border-border bg-card px-2 text-[13px]"
                value={copyFrom}
                onChange={(e) => setCopyFrom(e.target.value)}
              >
                <option value="">Choose an assignment…</option>
                {sources.map((s) => (
                  <option key={s.assignment_id} value={s.assignment_id}>
                    {s.course_label} · {s.assignment_type} · {s.assignment_name} ({s.criteria_count} criteria,{' '}
                    {fmt(s.total_points)} pts)
                  </option>
                ))}
              </select>
            </div>
            <Button variant="outline" size="sm" disabled={!copyFrom || busy} onClick={() => void copy()}>
              Copy
            </Button>
          </div>
        ) : null}
      </Card>

      {drafts.map((d, i) => (
        <CriterionCard
          key={d.key}
          index={i}
          count={drafts.length}
          draft={d}
          update={(patch) => update(d.key, patch)}
          move={(delta) => move(i, delta)}
          remove={() => remove(d.key)}
        />
      ))}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="soft" size="sm" onClick={add}>
          + Add criterion
        </Button>
        <div className="flex items-center gap-2">
          {problems.length ? <span className="text-[12px] text-bad">{problems[0]}</span> : null}
          {dirty ? <span className="text-[12px] text-warn">Unsaved changes</span> : null}
          {state.rubric ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="text-bad"
                disabled={busy}
                onClick={() => void deleteRubric()}
              >
                Delete rubric
              </Button>
              <Button variant="outline" size="sm" disabled={busy || dirty} onClick={() => void scoreAll()}>
                Score all with LLM
              </Button>
            </>
          ) : null}
          <Button
            size="sm"
            disabled={busy || !dirty || drafts.length === 0 || problems.length > 0}
            onClick={() => void save()}
          >
            Save rubric
          </Button>
        </div>
      </div>
    </div>
  );
}

function CriterionCard({
  index,
  count,
  draft,
  update,
  move,
  remove
}: {
  index: number;
  count: number;
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
  move: (delta: number) => void;
  remove: () => void;
}) {
  const setLevel = (i: number, patch: Partial<Level>) =>
    update({ levels: draft.levels.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  return (
    <Card className="p-4" data-testid="rubric-criterion">
      <div className="flex items-start gap-3">
        <div className="tnum mt-6 w-5 text-center text-[13px] text-ink-3">{index + 1}</div>
        <div className="grid min-w-0 flex-1 gap-2.5">
          <div className="grid gap-2.5" style={{ gridTemplateColumns: 'minmax(0, 1fr) 110px' }}>
            <div>
              <Label htmlFor={`crit-name-${draft.key}`}>Criterion name</Label>
              <Input
                id={`crit-name-${draft.key}`}
                dir="auto"
                value={draft.name}
                placeholder="e.g. עיבוד מקדים של הנתונים"
                onChange={(e) => update({ name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor={`crit-max-${draft.key}`}>Max points</Label>
              <Input
                id={`crit-max-${draft.key}`}
                type="number"
                min={0}
                step="any"
                value={draft.max_points}
                onChange={(e) => update({ max_points: e.target.value })}
              />
            </div>
          </div>
          <div>
            <Label htmlFor={`crit-desc-${draft.key}`}>What earns full or partial credit</Label>
            <textarea
              id={`crit-desc-${draft.key}`}
              dir="auto"
              className="min-h-[72px] w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-ink outline-none focus:border-forest focus:ring-2 focus:ring-forest-tint"
              value={draft.description}
              onChange={(e) => update({ description: e.target.value })}
            />
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[12px] text-ink-3">Levels (optional)</span>
              <Button
                variant="link"
                size="sm"
                onClick={() => update({ levels: [...draft.levels, { points: 0, description: '' }] })}
              >
                + Level
              </Button>
            </div>
            {draft.levels.map((l, i) => (
              <div
                key={i}
                className="mb-1.5 grid items-center gap-2"
                style={{ gridTemplateColumns: '90px minmax(0, 1fr) auto' }}
              >
                <Input
                  type="number"
                  min={0}
                  step="any"
                  aria-label="Level points"
                  value={String(l.points)}
                  onChange={(e) => setLevel(i, { points: Number(e.target.value) })}
                />
                <Input
                  dir="auto"
                  aria-label="Level description"
                  value={l.description}
                  onChange={(e) => setLevel(i, { description: e.target.value })}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Remove level"
                  onClick={() => update({ levels: draft.levels.filter((_, j) => j !== i) })}
                >
                  ✕
                </Button>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-5 flex shrink-0 flex-col gap-1">
          <Button variant="ghost" size="sm" aria-label="Move up" disabled={index === 0} onClick={() => move(-1)}>
            ↑
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label="Move down"
            disabled={index === count - 1}
            onClick={() => move(1)}
          >
            ↓
          </Button>
          <Button variant="ghost" size="sm" aria-label="Delete criterion" className="text-bad" onClick={remove}>
            ✕
          </Button>
        </div>
      </div>
    </Card>
  );
}
