'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import { BilingualName } from '@/components/ui/bilingual-name';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  apiBase,
  apiDelete,
  apiFetch,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  errorMessage,
  putToStorage,
  type UploadTarget
} from '@/lib/api';

/* =============== Types =============== */

type SessionRow = { number: number; held_on: string | null; title: string };
type PresentationRow = {
  id: number;
  team_id: number;
  team_name: string;
  project_title: string;
  session_number: number | null;
  original_session_number: number | null;
  assignment_source: string;
  status: string;
  review_open: boolean;
  demo_url: string;
  materials_text: string;
  has_slides: boolean;
  slides_artifact_id: number | null;
  review_count: number;
  llm_reviewed: boolean;
  moves: number;
};
type RoundRow = {
  id: number;
  number: number;
  kind: 'progress' | 'final';
  title: string;
  status: 'draft' | 'scheduling' | 'reviewing' | 'closed';
  sessions: { number: number; capacity: number; load: number }[];
  selection_deadline: string | null;
  review_deadline: string | null;
  released_at: string | null;
  rubric_version: { id: number; version: number } | null;
  target_mean: number;
  target_std: number;
  missing_review_policy: 'missing' | 'zero';
  participation_factor: boolean;
  llm_enabled: boolean;
  counts_toward_grade: boolean;
  obligations: { expected: number; completed: number };
  presentations: PresentationRow[];
};
type Overview = {
  sessions: SessionRow[];
  rounds: RoundRow[];
  teams: { id: number; name: string; project_title: string; member_count: number }[];
  student_count: number;
};

type TabKey = 'schedule' | 'teams' | 'rubrics' | 'reviews' | 'scores';
const TABS: { key: TabKey; label: string }[] = [
  { key: 'schedule', label: 'Schedule & windows' },
  { key: 'teams', label: 'Teams & links' },
  { key: 'rubrics', label: 'Rubrics' },
  { key: 'reviews', label: 'Reviews & participation' },
  { key: 'scores', label: 'Scores & export' }
];

const STATUS_PILL: Record<RoundRow['status'], string> = {
  draft: 'pill',
  scheduling: 'pill pill-info',
  reviewing: 'pill pill-forest',
  closed: 'pill pill-warn'
};

/* =============== Helpers =============== */

function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';
}
function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? '—' : v.toFixed(digits);
}
function pct(v: number | null | undefined): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`;
}
function roundName(r: RoundRow): string {
  return r.counts_toward_grade ? `${r.number}. ${r.title}` : r.title;
}

function Th({ children, className = '' }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={`label-eyebrow border-b border-border px-3 py-2.5 text-left font-semibold ${className}`}>{children}</th>
  );
}
function Td({ children, className = '' }: { children?: React.ReactNode; className?: string }) {
  return <td className={`px-3 py-2.5 align-top ${className}`}>{children}</td>;
}
function TableCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-auto rounded-lg border border-border bg-card shadow-soft">
      <table className="w-full border-collapse text-[14px]">{children}</table>
    </div>
  );
}

/* =============== Step =============== */

export function PeerReviewStep({ courseId, setToast }: { courseId: number; setToast: (m: string) => void }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [tab, setTab] = useState<TabKey>('schedule');
  const [roundId, setRoundId] = useState<number | null>(null);
  const base = `/api/courses/${courseId}/peer`;

  const load = useCallback(async () => {
    const data = await apiGet<Overview>(`${base}/overview`);
    setOverview(data);
    setRoundId((cur) => {
      if (cur && data.rounds.some((r) => r.id === cur)) return cur;
      const active = data.rounds.find((r) => r.status === 'reviewing') ?? data.rounds.find((r) => r.status === 'scheduling');
      return (active ?? data.rounds[0])?.id ?? null;
    });
  }, [base]);

  useEffect(() => {
    void load().catch((e) => setToast(errorMessage(e)));
  }, [load, setToast]);

  const run = useCallback(
    async (fn: () => Promise<unknown>, success?: string) => {
      try {
        await fn();
        if (success) setToast(success);
      } catch (e) {
        setToast(errorMessage(e));
      }
      await load().catch(() => undefined);
    },
    [load, setToast]
  );

  if (!overview) return <div className="pt-6 text-ink-3">Loading…</div>;

  if (overview.rounds.length === 0) {
    return (
      <div className="grid gap-3.5 pt-6">
        <Card>
          <div className="label-eyebrow mb-1">Peer review</div>
          <h2 className="font-display text-[24px]">Set up the presentation schedule</h2>
          <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-ink-2">
            Creates 13 sessions and 5 review rounds: four progress rounds (sessions 2–3, 4–5, 6–7, 8–9) and the final
            round (sessions 12–13), with room for four teams per session. Sessions 10–11 stay free for postponed
            presentations. Default rubrics are created too; everything stays editable.
          </p>
          <Button className="mt-4" onClick={() => run(() => apiPost(`${base}/setup`), 'Schedule created')}>
            Create default schedule
          </Button>
        </Card>
      </div>
    );
  }

  const round = overview.rounds.find((r) => r.id === roundId) ?? overview.rounds[0];

  return (
    <div className="grid gap-4 pt-6">
      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-full border px-3.5 py-1.5 text-[13px] ${
              tab === t.key ? 'border-forest bg-forest text-paper' : 'border-border bg-card text-ink-2 hover:border-ink-4'
            }`}
          >
            {t.label}
          </button>
        ))}
        <a
          href={`/course/${courseId}/student-view`}
          className="ml-auto rounded-full border border-terracotta-soft bg-terracotta-tint px-3.5 py-1.5 text-[13px] text-ink hover:border-terracotta"
        >
          👁 View as student
        </a>
      </div>

      {tab !== 'teams' && tab !== 'rubrics' ? (
        <div className="flex flex-wrap gap-2">
          {overview.rounds.map((r) => (
            <button
              key={r.id}
              onClick={() => setRoundId(r.id)}
              className={`flex items-center gap-2 rounded-md border px-3 py-2 text-[13px] ${
                r.id === round.id ? 'border-forest bg-forest-tint text-forest' : 'border-border bg-card text-ink-2'
              }`}
            >
              <span className="font-semibold">{roundName(r)}</span>
              {!r.counts_toward_grade ? <span className="pill pill-terra">practice</span> : null}
              <span className={STATUS_PILL[r.status]}>{r.released_at ? 'released' : r.status}</span>
            </button>
          ))}
        </div>
      ) : null}

      {tab === 'schedule' ? <ScheduleTab base={base} overview={overview} round={round} run={run} /> : null}
      {tab === 'teams' ? (
        <>
          <AccountsCard courseId={courseId} setToast={setToast} />
          <TeamsTab base={base} courseId={courseId} run={run} setToast={setToast} />
        </>
      ) : null}
      {tab === 'rubrics' ? <RubricsTab base={base} setToast={setToast} /> : null}
      {tab === 'reviews' ? <ReviewsTab key={round.id} base={base} round={round} run={run} /> : null}
      {tab === 'scores' ? <ScoresTab key={round.id} base={base} courseId={courseId} round={round} run={run} setToast={setToast} /> : null}
    </div>
  );
}

type Run = (fn: () => Promise<unknown>, success?: string) => Promise<void>;

/* =============== Schedule =============== */

function ScheduleTab({ base, overview, round, run }: { base: string; overview: Overview; round: RoundRow; run: Run }) {
  const act = (action: string, msg: string, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    return run(() => apiPost(`${base}/rounds/${round.id}/actions/${action}`), msg);
  };
  const sessionNumbers = round.sessions.map((s) => s.number);
  const extraSessions = round.presentations
    .map((p) => p.session_number)
    .filter((n): n is number => n != null && !sessionNumbers.includes(n));
  const sessionsShown = [...sessionNumbers, ...Array.from(new Set(extraSessions)).sort((a, b) => a - b)];
  const heldOn = (n: number) => overview.sessions.find((s) => s.number === n)?.held_on;

  return (
    <div className="grid gap-4">
      <Card className="grid gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="label-eyebrow mb-1">
              {round.counts_toward_grade
                ? `Round ${round.number} · ${round.kind === 'final' ? 'final presentations' : 'progress review'}`
                : 'Practice round · not part of any grade'}
            </div>
            <h2 className="font-display text-[24px] leading-tight">{round.title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-ink-3">
              <span className={STATUS_PILL[round.status]}>{round.status}</span>
              {round.released_at ? <span className="pill pill-ok">results released</span> : null}
              <span>
                Rubric:{' '}
                {round.rubric_version ? `v${round.rubric_version.version} (frozen)` : 'frozen when reviewing opens'}
              </span>
              <span>
                · Reviews {round.obligations.completed}/{round.obligations.expected}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {round.status === 'draft' ? (
              <Button size="sm" variant="soft" onClick={() => act('open-selection', 'Date selection opened')}>
                Open date selection
              </Button>
            ) : null}
            {round.status === 'scheduling' ? (
              <Button size="sm" variant="soft" onClick={() => act('random-assign', 'Unassigned teams placed')}>
                🎲 Random-assign unassigned
              </Button>
            ) : null}
            {round.status === 'draft' || round.status === 'scheduling' ? (
              <Button
                size="sm"
                onClick={() =>
                  act(
                    'open-reviewing',
                    'Reviewing opened — rubric frozen',
                    'Open reviewing? This freezes the rubric for this round and snapshots team membership.'
                  )
                }
              >
                Open reviewing
              </Button>
            ) : null}
            {round.status === 'reviewing' ? (
              <Button
                size="sm"
                variant="warm"
                onClick={() => act('close', 'Round closed', 'Close reviewing for both sessions of this round?')}
              >
                Close round
              </Button>
            ) : null}
            {round.status === 'closed' && !round.released_at ? (
              <>
                <Button size="sm" variant="outline" onClick={() => act('reopen', 'Round reopened')}>
                  Reopen
                </Button>
                <Button
                  size="sm"
                  onClick={() =>
                    act('release', 'Results released', 'Release aggregate scores and anonymised feedback to the teams?')
                  }
                >
                  Release results
                </Button>
              </>
            ) : null}
            {round.released_at ? (
              <Button size="sm" variant="outline" onClick={() => act('unrelease', 'Results hidden again')}>
                Unrelease
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => act('sync', 'Synced teams and roster')}>
              Sync teams/roster
            </Button>
          </div>
        </div>

        {round.status === 'reviewing' && !round.counts_toward_grade ? (
          <div className="rounded-md bg-terracotta-tint px-3 py-2.5 text-[13px]">
            Practice round: every presentation accepts reviews while it's open, and teams you create or change join it
            automatically. Its scores are shown for practice only and never count toward a grade.
          </div>
        ) : null}
        {round.status === 'reviewing' && round.counts_toward_grade ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md bg-forest-tint px-3 py-2.5 text-[13px]">
            <span className="font-semibold text-forest">Reviews per session:</span>
            {sessionsShown.map((n) => {
              const inSession = round.presentations.filter((p) => p.session_number === n);
              if (!inSession.length) return null;
              const open = inSession.every((p) => p.review_open);
              return (
                <Button
                  key={n}
                  size="sm"
                  variant={open ? 'default' : 'outline'}
                  onClick={() =>
                    run(
                      () => apiPost(`${base}/rounds/${round.id}/sessions/${n}/reviewing`, { open: !open }),
                      open ? `Session ${n} closed for reviews` : `Session ${n} open for reviews`
                    )
                  }
                >
                  Session {n}: {open ? 'open ✓' : 'closed'}
                </Button>
              );
            })}
          </div>
        ) : null}

        <RoundSettings base={base} round={round} run={run} />
      </Card>

      <PresentationsTable base={base} round={round} sessionsShown={sessionsShown} heldOn={heldOn} run={run} />

      <div className="flex justify-end">
        <Button
          size="sm"
          variant="ghost"
          onClick={() =>
            window.confirm('Create a practice round and open it for reviews now? It never counts toward a grade.') &&
            run(() => apiPost(`${base}/rounds/practice`, { title: 'Practice round (not graded)', open_now: true }), 'Practice round opened')
          }
        >
          + Add practice round
        </Button>
      </div>

      <details className="rounded-lg border border-border bg-card p-4 shadow-soft">
        <summary className="cursor-pointer text-[14px] font-semibold">Session dates (1–13)</summary>
        <p className="mt-2 text-[13px] text-ink-3">
          Dates let the student page put “today’s presentations” first and show dates when teams pick a slot.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {overview.sessions.map((s) => (
            <label key={s.number} className="flex items-center gap-2 text-[13px]">
              <span className="w-[86px] shrink-0 font-semibold">Session {s.number}</span>
              <Input
                type="date"
                className="h-9"
                defaultValue={s.held_on ?? ''}
                onChange={(e) =>
                  run(() => apiPatch(`${base}/sessions/${s.number}`, { held_on: e.target.value || null }))
                }
              />
            </label>
          ))}
        </div>
      </details>
    </div>
  );
}

function RoundSettings({ base, round, run }: { base: string; round: RoundRow; run: Run }) {
  const [selection, setSelection] = useState(toLocalInput(round.selection_deadline));
  const [review, setReview] = useState(toLocalInput(round.review_deadline));
  const [caps, setCaps] = useState(round.sessions.map((s) => ({ number: s.number, capacity: s.capacity })));
  useEffect(() => {
    setSelection(toLocalInput(round.selection_deadline));
    setReview(toLocalInput(round.review_deadline));
    setCaps(round.sessions.map((s) => ({ number: s.number, capacity: s.capacity })));
  }, [round]);

  const save = (e: FormEvent) => {
    e.preventDefault();
    run(
      () =>
        apiPatch(`${base}/rounds/${round.id}`, {
          sessions: caps,
          selection_deadline: selection ? new Date(selection).toISOString() : null,
          clear_selection_deadline: !selection,
          review_deadline: review ? new Date(review).toISOString() : null,
          clear_review_deadline: !review
        }),
      'Round settings saved'
    );
  };

  return (
    <form onSubmit={save} className="grid gap-3 border-t border-line-soft pt-4 md:grid-cols-[1fr_1fr_1.4fr_auto] md:items-end">
      <div>
        <Label>Selection deadline</Label>
        <Input type="datetime-local" value={selection} onChange={(e) => setSelection(e.target.value)} />
      </div>
      <div>
        <Label>Review deadline (edits close)</Label>
        <Input type="datetime-local" value={review} onChange={(e) => setReview(e.target.value)} />
      </div>
      <div>
        <Label>Capacity per session</Label>
        <div className="flex flex-wrap gap-2">
          {caps.map((c, i) => (
            <label key={c.number} className="flex items-center gap-1.5 text-[13px]">
              S{c.number}
              <Input
                type="number"
                min={0}
                max={20}
                className="h-9 w-16"
                value={c.capacity}
                onChange={(e) => setCaps(caps.map((x, j) => (j === i ? { ...x, capacity: Number(e.target.value) } : x)))}
              />
            </label>
          ))}
        </div>
      </div>
      <Button type="submit" size="sm" variant="soft">
        Save
      </Button>
    </form>
  );
}

function PresentationsTable({
  base,
  round,
  sessionsShown,
  heldOn,
  run
}: {
  base: string;
  round: RoundRow;
  sessionsShown: number[];
  heldOn: (n: number) => string | null | undefined;
  run: Run;
}) {
  const [moving, setMoving] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [history, setHistory] = useState<{ id: number; rows: Record<string, unknown>[] } | null>(null);
  // A move changes the round payload; drop any history panel so it can't go stale.
  useEffect(() => setHistory(null), [round]);

  const byId = useMemo(() => Object.fromEntries(round.presentations.map((p) => [p.id, p])), [round.presentations]);
  const sorted = [...round.presentations].sort(
    (a, b) => (a.session_number ?? 99) - (b.session_number ?? 99) || a.team_name.localeCompare(b.team_name)
  );
  const showHistory = async (id: number) => {
    if (history?.id === id) return setHistory(null);
    setHistory({ id, rows: await apiGet(`${base}/presentations/${id}/moves`) });
  };

  return (
    <TableCard>
      <thead>
        <tr>
          <Th className="pl-5">Team</Th>
          <Th>Session</Th>
          <Th>Source</Th>
          <Th>Reviews</Th>
          <Th>Materials</Th>
          <Th className="pr-5 text-right">Actions</Th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((p) => (
          <FragmentRows key={p.id}>
            <tr className="border-b border-line-soft">
              <Td className="pl-5">
                <div className="font-semibold">{p.team_name}</div>
                <div className="text-[12px] text-ink-3">{p.project_title || '—'}</div>
              </Td>
              <Td>
                {p.session_number == null ? (
                  <span className="pill pill-warn">unassigned</span>
                ) : (
                  <span>
                    S{p.session_number}
                    {heldOn(p.session_number) ? (
                      <span className="text-[12px] text-ink-3"> · {heldOn(p.session_number)}</span>
                    ) : null}
                  </span>
                )}
                {p.status === 'postponed' ? <span className="pill pill-terra ml-1.5">postponed</span> : null}
                {p.original_session_number != null && p.original_session_number !== p.session_number ? (
                  <div className="text-[11px] text-ink-3">originally S{p.original_session_number}</div>
                ) : null}
                {round.status === 'reviewing' ? (
                  <div className="mt-1">
                    <label className="flex items-center gap-1.5 text-[12px]">
                      <input
                        type="checkbox"
                        checked={p.review_open}
                        onChange={() =>
                          run(() => apiPatch(`${base}/presentations/${p.id}`, { review_open: !p.review_open }))
                        }
                      />
                      accepting reviews
                    </label>
                  </div>
                ) : null}
              </Td>
              <Td>
                <span className="text-[12px] text-ink-2">{p.assignment_source || '—'}</span>
                {p.moves ? (
                  <button className="ml-1.5 text-[12px] text-forest hover:underline" onClick={() => showHistory(p.id)}>
                    {p.moves} move{p.moves > 1 ? 's' : ''}
                  </button>
                ) : null}
              </Td>
              <Td className="tnum">
                {p.review_count}
                {p.llm_reviewed ? <span className="pill pill-info ml-1.5">AI ✓</span> : null}
              </Td>
              <Td className="text-[12px]">
                {p.demo_url ? (
                  <a href={p.demo_url} target="_blank" rel="noreferrer" className="text-forest hover:underline">
                    demo ↗
                  </a>
                ) : (
                  <span className="text-ink-4">no demo</span>
                )}
                {' · '}
                {p.has_slides && p.slides_artifact_id ? (
                  <a
                    href={`${apiBase()}/api/artifacts/${p.slides_artifact_id}?inline=1`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-forest hover:underline"
                  >
                    slides ↗
                  </a>
                ) : (
                  <span className="text-ink-4">no slides</span>
                )}
                {' · '}
                <span className={p.materials_text ? 'text-ink-2' : 'text-ink-4'}>
                  {p.materials_text ? 'description ✓' : 'no description'}
                </span>
              </Td>
              <Td className="pr-5 text-right">
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="outline" onClick={() => setMoving(moving === p.id ? null : p.id)}>
                    Move / swap
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(editing === p.id ? null : p.id)}>
                    Materials
                  </Button>
                </div>
              </Td>
            </tr>
            {moving === p.id ? (
              <tr className="border-b border-line-soft bg-paper-2">
                <td colSpan={6} className="px-5 py-3">
                  <MoveForm
                    base={base}
                    round={round}
                    p={p}
                    sessions={sessionsShown}
                    others={round.presentations.filter((o) => o.id !== p.id)}
                    run={run}
                    done={() => setMoving(null)}
                  />
                </td>
              </tr>
            ) : null}
            {editing === p.id ? (
              <tr className="border-b border-line-soft bg-paper-2">
                <td colSpan={6} className="px-5 py-3">
                  <MaterialsForm base={base} p={p} run={run} done={() => setEditing(null)} />
                </td>
              </tr>
            ) : null}
            {history?.id === p.id ? (
              <tr className="border-b border-line-soft bg-paper-2">
                <td colSpan={6} className="px-5 py-3 text-[12px]">
                  {history.rows.map((m) => (
                    <div key={String(m.id)}>
                      {fmtDate(m.created_at as string)} · {String(m.kind)} by {String(m.actor)}: S
                      {String(m.from_session ?? '—')} → S{String(m.to_session ?? '—')}
                      {m.reason ? ` — “${String(m.reason)}”` : ''}
                    </div>
                  ))}
                  {!history.rows.length ? 'No moves recorded.' : null}
                  {byId[p.id]?.review_count ? (
                    <div className="mt-1 text-ink-3">Reviews stay attached to this presentation across moves.</div>
                  ) : null}
                </td>
              </tr>
            ) : null}
          </FragmentRows>
        ))}
      </tbody>
    </TableCard>
  );
}

function FragmentRows({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function MoveForm({
  base,
  round,
  p,
  sessions,
  others,
  run,
  done
}: {
  base: string;
  round: RoundRow;
  p: PresentationRow;
  sessions: number[];
  others: PresentationRow[];
  run: Run;
  done: () => void;
}) {
  const options = Array.from(new Set([...sessions, 10, 11, ...Array.from({ length: 13 }, (_, i) => i + 1)])).sort(
    (a, b) => a - b
  );
  const [target, setTarget] = useState<string>(String(p.session_number ?? sessions[0] ?? ''));
  const [postpone, setPostpone] = useState(false);
  const [reason, setReason] = useState('');
  const [swapWith, setSwapWith] = useState<string>('');

  const move = (e: FormEvent) => {
    e.preventDefault();
    run(
      () =>
        apiPatch(`${base}/presentations/${p.id}`, {
          move: true,
          session_number: target === '' ? null : Number(target),
          postpone,
          reason
        }),
      postpone ? 'Presentation postponed' : 'Presentation moved'
    ).then(done);
  };
  const swap = () => {
    if (!swapWith) return;
    run(
      () => apiPost(`${base}/rounds/${round.id}/swap`, { a_id: p.id, b_id: Number(swapWith), reason }),
      'Presentations swapped'
    ).then(done);
  };

  return (
    <form onSubmit={move} className="grid items-end gap-3 md:grid-cols-[140px_auto_1fr_auto_200px_auto]">
      <div>
        <Label>Session</Label>
        <select
          className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
        >
          <option value="">Unassigned</option>
          {options.map((n) => (
            <option key={n} value={n}>
              S{n}
              {sessions.includes(n) ? ' (round)' : n === 10 || n === 11 ? ' (build time)' : ''}
            </option>
          ))}
        </select>
      </div>
      <label className="flex h-10 items-center gap-1.5 text-[13px]">
        <input type="checkbox" checked={postpone} onChange={(e) => setPostpone(e.target.checked)} /> Postponement
      </label>
      <div>
        <Label>Reason (logged)</Label>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. two members sick" />
      </div>
      <Button size="sm" type="submit">
        Move
      </Button>
      <div>
        <Label>…or swap with</Label>
        <select
          className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm"
          value={swapWith}
          onChange={(e) => setSwapWith(e.target.value)}
        >
          <option value="">Choose team…</option>
          {others.map((o) => (
            <option key={o.id} value={o.id}>
              {o.team_name} (S{o.session_number ?? '—'})
            </option>
          ))}
        </select>
      </div>
      <Button size="sm" variant="outline" type="button" disabled={!swapWith} onClick={swap}>
        Approve swap
      </Button>
      <p className="text-[12px] text-ink-3 md:col-span-6">
        Moving keeps the presentation in round {round.number} with all its reviews. Moving to another session closes its
        review window until you reopen it.
      </p>
    </form>
  );
}

function MaterialsForm({ base, p, run, done }: { base: string; p: PresentationRow; run: Run; done: () => void }) {
  const [demo, setDemo] = useState(p.demo_url);
  const [text, setText] = useState(p.materials_text);
  const save = (e: FormEvent) => {
    e.preventDefault();
    run(() => apiPatch(`${base}/presentations/${p.id}`, { demo_url: demo, materials_text: text }), 'Materials saved').then(done);
  };
  const upload = async (file: File | undefined) => {
    if (!file) return;
    await run(async () => {
      const target = await apiPost<UploadTarget>(`${base}/presentations/${p.id}/slides/upload-url`);
      if (target.direct) {
        const key = await putToStorage(target, file);
        await apiPost(`${base}/presentations/${p.id}/slides/complete`, { key, filename: file.name });
        return;
      }
      const fd = new FormData();
      fd.append('file', file);
      const res = await apiFetch(`${base}/presentations/${p.id}/slides`, { method: 'POST', body: fd });
      if (!res.ok) throw new Error(await res.text());
    }, 'Slides uploaded');
  };
  return (
    <form onSubmit={save} className="grid gap-3 md:grid-cols-[1fr_2fr_auto] md:items-end">
      <div>
        <Label>Demo / MVP link</Label>
        <Input value={demo} onChange={(e) => setDemo(e.target.value)} placeholder="https://" />
        <Label className="mt-3 block">Slides (PDF)</Label>
        <input type="file" accept="application/pdf" className="text-[13px]" onChange={(e) => upload(e.target.files?.[0])} />
      </div>
      <div>
        <Label>Description (shown to the AI grader)</Label>
        <textarea
          dir="auto"
          className="min-h-[96px] w-full rounded-md border border-border bg-card px-3 py-2 text-sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <Button size="sm" type="submit">
        Save
      </Button>
    </form>
  );
}

/* =============== Student accounts =============== */

type AccountRow = {
  student_id: number;
  name: string;
  national_id: string;
  email: string | null;
  has_account: boolean;
  invited_at: string | null;
  activated_at: string | null;
  is_test: boolean;
};
type AccountsData = { configured: boolean; login_url: string; students: AccountRow[] };

function AccountsCard({ courseId, setToast }: { courseId: number; setToast: (m: string) => void }) {
  const [data, setData] = useState<AccountsData | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/api/courses/${courseId}/accounts`;
  const load = useCallback(async () => setData(await apiGet<AccountsData>(base)), [base]);
  useEffect(() => {
    void load().catch((e) => setToast(errorMessage(e)));
  }, [load, setToast]);

  if (!data) return null;
  const real = data.students.filter((s) => !s.is_test);
  const testStudent = data.students.find((s) => s.is_test);
  const withoutAccount = real.filter((s) => s.email && !s.has_account);
  const waiting = real.filter((s) => s.has_account && !s.activated_at).length;
  const active = real.filter((s) => s.activated_at).length;
  const noEmail = real.filter((s) => !s.email).length;

  const act = async (fn: () => Promise<string>) => {
    setBusy(true);
    try {
      setToast(await fn());
    } catch (e) {
      setToast(errorMessage(e));
    } finally {
      setBusy(false);
      await load();
    }
  };

  const create = (ids: number[]) =>
    act(async () => {
      const res = await apiPost<{ counts: Record<string, number>; results: { status: string; error?: string }[] }>(
        `${base}/create`,
        { student_ids: ids }
      );
      const failed = res.results.filter((r) => r.status === 'error');
      return failed.length
        ? `${res.counts.created ?? 0} created, ${failed.length} failed: ${failed[0].error ?? ''}`
        : `${res.counts.created ?? 0} account${res.counts.created === 1 ? '' : 's'} created`;
    });

  const reset = (s: AccountRow) => {
    if (!window.confirm(`Reset ${s.name}'s password to their ID number? They'll choose a new one at next login.`)) return;
    void act(async () => {
      await apiPost(`${base}/${s.student_id}/reset-password`);
      return 'Password reset to the ID number';
    });
  };

  const createTest = () => {
    const email = window.prompt(
      'Email for your test student account (it must not be a real student\'s). Tip: a +alias of your own address, e.g. you+student@…'
    );
    if (!email) return;
    void act(async () => {
      const res = await apiPost<{ email: string }>(`${base}/test-student`, { email });
      return `Test student ${res.email} ready — first password is shown in the accounts card`;
    });
  };

  const status = (s: AccountRow) =>
    s.is_test ? (
      <span className="pill pill-info">test student</span>
    ) : !s.email ? (
      <span className="pill pill-warn">no email</span>
    ) : s.activated_at ? (
      <span className="pill pill-ok">active</span>
    ) : s.has_account ? (
      <span className="pill pill-info">waiting for first login</span>
    ) : (
      <span className="pill">no account</span>
    );

  return (
    <Card className="mb-4 grid gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="font-display text-[20px]">Student accounts</h3>
          <p className="max-w-2xl text-[13px] text-ink-3">
            Students sign in with their email. The first password is their ID number, and they must choose their own at
            first login. Emails come from the roster import (the Yedion export works). {active} active · {waiting} waiting
            for first login · {withoutAccount.length} without an account{noEmail ? ` · ${noEmail} without email` : ''}.
          </p>
        </div>
        <Button
          size="sm"
          disabled={!data.configured || busy || !withoutAccount.length}
          onClick={() => create(withoutAccount.map((s) => s.student_id))}
        >
          Create accounts ({withoutAccount.length})
        </Button>
      </div>
      {!data.configured ? (
        <div className="hint hint-warm">
          <span className="hint-icon">!</span>
          <div>Accounts need SUPABASE_PROJECT_URL and SUPABASE_SECRET_KEY on the backend.</div>
        </div>
      ) : (
        <div className="hint hint-soft">
          <span className="hint-icon">i</span>
          <div>
            No email is sent: tell students to sign in at{' '}
            <button
              className="font-mono text-forest hover:underline"
              onClick={() => navigator.clipboard.writeText(data.login_url).then(() => setToast('Login link copied'))}
            >
              {data.login_url}
            </button>{' '}
            with their email and ID number. Until a student changes it, anyone who knows both can sign in as them.
          </div>
        </div>
      )}
      {data.configured ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line-soft px-3 py-2 text-[13px]">
          {testStudent ? (
            <div>
              <b>Your test student:</b> sign in at the login link as{' '}
              <span className="font-mono">{testStudent.email}</span>
              {testStudent.activated_at ? (
                ' with the password you chose.'
              ) : (
                <>
                  {' '}
                  with first password <span className="font-mono">{testStudent.national_id}</span> (you&apos;ll pick your
                  own).
                </>
              )}{' '}
              <span className="text-ink-3">It reviews like a student but never counts in scores, exports or grades.</span>
            </div>
          ) : (
            <div className="text-ink-3">
              Want to see the site as a student? Create a test student — it takes part like anyone else but never counts
              in scores, exports or grades.
            </div>
          )}
          {testStudent ? (
            <button className="text-forest hover:underline" disabled={busy} onClick={() => reset(testStudent)}>
              Reset its password
            </button>
          ) : (
            <Button size="sm" variant="outline" disabled={busy} onClick={createTest}>
              Create test student
            </Button>
          )}
        </div>
      ) : null}
      <details>
        <summary className="cursor-pointer text-[13px] text-ink-2">Per-student status</summary>
        <div className="mt-2 max-h-[360px] overflow-auto">
          <table className="w-full border-collapse text-[13px]">
            <tbody>
              {data.students.map((s) => (
                <tr key={s.student_id} className="border-b border-line-soft last:border-b-0">
                  <td className="py-1.5 pr-3">
                    <BilingualName name={s.name} />
                  </td>
                  <td className="py-1.5 pr-3 font-mono text-[12px] text-ink-3">{s.email ?? '—'}</td>
                  <td className="py-1.5 pr-3">{status(s)}</td>
                  <td className="py-1.5 text-right">
                    {!data.configured || !s.email ? null : s.has_account ? (
                      <button className="text-forest hover:underline" disabled={busy} onClick={() => reset(s)}>
                        Reset password
                      </button>
                    ) : (
                      <button className="text-forest hover:underline" disabled={busy} onClick={() => create([s.student_id])}>
                        Create
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Card>
  );
}

/* =============== Teams & links =============== */

type TeamsData = {
  settings: { teams_open: boolean; max_team_size: number };
  teams: { id: number; name: string; project_title: string; join_code: string | null }[];
  students: { student_id: number; name: string; national_id: string; team_id: number | null; is_test?: boolean }[];
};
type LinkRow = { enrollment_id: number; student_id: number; name: string; national_id: string; team_name: string | null; token: string | null };

function TeamsTab({
  base,
  courseId,
  run,
  setToast
}: {
  base: string;
  courseId: number;
  run: Run;
  setToast: (m: string) => void;
}) {
  const [data, setData] = useState<TeamsData | null>(null);
  const [links, setLinks] = useState<LinkRow[]>([]);
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [origin, setOrigin] = useState('');

  const load = useCallback(async () => {
    const [t, l] = await Promise.all([apiGet<TeamsData>(`${base}/teams`), apiGet<LinkRow[]>(`${base}/links`)]);
    setData(t);
    setLinks(l);
  }, [base]);
  useEffect(() => {
    void load();
    try {
      setOrigin(localStorage.getItem('cg-review-link-origin') || window.location.origin);
    } catch {
      setOrigin(window.location.origin);
    }
  }, [load]);

  const act = async (fn: () => Promise<unknown>, msg?: string) => {
    await run(fn, msg);
    await load();
  };
  const linkFor = (token: string) => `${origin.replace(/\/$/, '')}/r/${token}`;
  const copy = async (text: string, msg: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setToast(msg);
    } catch {
      window.prompt('Copy:', text);
    }
  };

  if (!data) return <div className="text-ink-3">Loading…</div>;
  const counts = data.students.reduce<Record<number, number>>((acc, s) => {
    if (s.team_id) acc[s.team_id] = (acc[s.team_id] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Card className="grid content-start gap-3">
          <h3 className="font-display text-[20px]">Teams</h3>
          <div className="grid gap-2 rounded-md border border-line-soft px-3 py-2 text-[13px]">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={data.settings.teams_open}
                onChange={(e) =>
                  act(
                    () => apiPut(`${base}/team-settings`, { teams_open: e.target.checked }),
                    e.target.checked ? 'Students can form teams' : 'Teams locked'
                  )
                }
              />
              Students can create, join and leave teams themselves
            </label>
            <label className="flex items-center gap-2">
              Max team size
              <Input
                type="number"
                min={1}
                max={50}
                className="h-8 w-20"
                defaultValue={data.settings.max_team_size}
                onBlur={(e) =>
                  Number(e.target.value) !== data.settings.max_team_size &&
                  act(() => apiPut(`${base}/team-settings`, { max_team_size: Number(e.target.value) }), 'Max team size saved')
                }
              />
            </label>
            <p className="text-ink-3">
              A student opens a team and shares its join code (below) with teammates. Lock this once teams are final;
              you can still move students yourself.
            </p>
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              act(() => apiPost(`${base}/teams`, { name, project_title: title }), 'Team created').then(() => {
                setName('');
                setTitle('');
              });
            }}
          >
            <Input placeholder="Team name" value={name} onChange={(e) => setName(e.target.value)} />
            <Input placeholder="Project title" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Button type="submit" size="sm">
              Add
            </Button>
          </form>
          <div className="grid gap-1.5">
            {data.teams.map((t) => (
              <div key={t.id} className="grid gap-1 border-b border-line-soft pb-2 last:border-b-0">
                <div className="grid grid-cols-[1fr_1.4fr] gap-2">
                  <Input
                    className="h-9"
                    defaultValue={t.name}
                    onBlur={(e) => e.target.value !== t.name && act(() => apiPatch(`${base}/teams/${t.id}`, { name: e.target.value }))}
                  />
                  <Input
                    className="h-9"
                    defaultValue={t.project_title}
                    placeholder="Project title"
                    onBlur={(e) =>
                      e.target.value !== t.project_title &&
                      act(() => apiPatch(`${base}/teams/${t.id}`, { project_title: e.target.value }))
                    }
                  />
                </div>
                <div className="flex items-center gap-3 text-[12px] text-ink-3">
                  <span className="tnum">
                    {counts[t.id] ?? 0} member{(counts[t.id] ?? 0) === 1 ? '' : 's'}
                  </span>
                  <span>
                    join code{' '}
                    <button
                      className="font-mono tracking-wider text-ink-2 hover:text-forest"
                      title="Click to copy"
                      onClick={() => t.join_code && copy(t.join_code, 'Join code copied')}
                    >
                      {t.join_code ?? '—'}
                    </button>
                  </span>
                  <button
                    className="ml-auto hover:text-bad"
                    onClick={() => window.confirm(`Delete ${t.name}?`) && act(() => apiDelete(`${base}/teams/${t.id}`), 'Team deleted')}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
            {!data.teams.length ? <p className="text-[13px] text-ink-3">No teams yet.</p> : null}
          </div>
          <p className="text-[12px] leading-relaxed text-ink-3">
            Moving a student ends their old membership instead of rewriting it. Rounds already open for reviewing keep
            the team each student had when reviewing opened.
          </p>
        </Card>

        <Card className="grid content-start gap-3">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="font-display text-[20px]">Students</h3>
            <span className="text-[13px] text-ink-3">
              {data.students.filter((s) => !s.team_id && !s.is_test).length} without a team
            </span>
          </div>
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full border-collapse text-[14px]">
              <tbody>
                {[...data.students]
                  .sort((a, b) => Number(!!a.team_id) - Number(!!b.team_id))
                  .map((s) => (
                  <tr key={s.student_id} className="border-b border-line-soft last:border-b-0">
                    <td className="py-1.5 pr-2">
                      <BilingualName name={s.name} />
                      <div className="font-mono text-[11px] text-ink-3">{s.national_id}</div>
                    </td>
                    <td className="py-1.5 text-right">
                      <select
                        className="h-9 rounded-md border border-border bg-card px-2 text-sm"
                        value={s.team_id ?? ''}
                        onChange={(e) =>
                          act(() =>
                            apiPut(`${base}/students/${s.student_id}/team`, {
                              team_id: e.target.value ? Number(e.target.value) : null
                            })
                          )
                        }
                      >
                        <option value="">No team</option>
                        {data.teams.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card className="grid gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h3 className="font-display text-[20px]">Student review links</h3>
            <p className="max-w-2xl text-[13px] text-ink-3">
              Each student gets a personal link — their only credential. Share it privately (e.g. email). Anyone with the
              link can review as that student, so regenerate a link if it leaks.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <Label>Link base URL</Label>
              <Input
                className="h-9 w-[280px]"
                value={origin}
                onChange={(e) => {
                  setOrigin(e.target.value);
                  try {
                    localStorage.setItem('cg-review-link-origin', e.target.value);
                  } catch {
                    /* ignore */
                  }
                }}
              />
            </div>
            <Button size="sm" variant="soft" onClick={() => act(() => apiPost(`${base}/links/generate`), 'Links generated')}>
              Generate missing links
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!links.some((l) => l.token)}
              onClick={() =>
                copy(
                  ['national_id,name,team,link']
                    .concat(
                      links
                        .filter((l) => l.token)
                        .map((l) => [l.national_id, `"${l.name}"`, `"${l.team_name ?? ''}"`, linkFor(l.token!)].join(','))
                    )
                    .join('\n'),
                  'All links copied as CSV'
                )
              }
            >
              Copy all (CSV)
            </Button>
          </div>
        </div>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full border-collapse text-[13px]">
            <tbody>
              {links.map((l) => (
                <tr key={l.enrollment_id} className="border-b border-line-soft last:border-b-0">
                  <td className="py-1.5 pr-3">
                    <BilingualName name={l.name} />
                  </td>
                  <td className="py-1.5 pr-3 text-ink-3">{l.team_name ?? '—'}</td>
                  <td className="py-1.5 pr-3 font-mono text-[11px] text-ink-3">
                    {l.token ? `${linkFor(l.token).slice(0, 48)}…` : 'no link yet'}
                  </td>
                  <td className="py-1.5 text-right">
                    {l.token ? (
                      <>
                        <button className="mr-3 text-forest hover:underline" onClick={() => copy(linkFor(l.token!), 'Link copied')}>
                          Copy
                        </button>
                        <a
                          className="mr-3 text-forest hover:underline"
                          href={`/course/${courseId}/student-view?student=${l.student_id}`}
                          title="See this student's page, read-only"
                        >
                          Preview
                        </a>
                        <a className="mr-3 text-forest hover:underline" href={`/r/${l.token}`} target="_blank" rel="noreferrer">
                          Open
                        </a>
                        <button
                          className="text-ink-3 hover:text-bad"
                          onClick={() =>
                            window.confirm(`Replace ${l.name}'s link? The old link stops working.`) &&
                            act(() => apiPost(`${base}/links/${l.enrollment_id}/regenerate`), 'New link created')
                          }
                        >
                          Regenerate
                        </button>
                      </>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* =============== Rubrics =============== */

type RubricData = {
  id: number;
  kind: 'progress' | 'final';
  version: number;
  criteria: { key: string; label: string; description: string; weight: number; counts?: boolean; max?: number | null }[];
  scale: { value: number; label: string }[];
  prompts: { key: string; label: string; required: boolean }[];
  instructions: string;
  frozen: boolean;
  used_by_rounds: number[];
};

function RubricsTab({ base, setToast }: { base: string; setToast: (m: string) => void }) {
  const [rubrics, setRubrics] = useState<Record<string, RubricData> | null>(null);
  const [kind, setKind] = useState<'progress' | 'final'>('progress');
  const load = useCallback(async () => setRubrics(await apiGet(`${base}/rubrics`)), [base]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!rubrics) return <div className="text-ink-3">Loading…</div>;
  return (
    <div className="grid gap-3">
      <div className="hint">
        <span className="hint-icon">i</span>
        <div>
          Each round freezes the rubric version that is current when its reviewing opens, so every review in a round uses
          the same criteria and weights. Editing a frozen version saves a new version for rounds opened later.
          Students see the labels, descriptions, and instructions in Hebrew as you write them here.
        </div>
      </div>
      <div className="flex gap-2">
        {(['progress', 'final'] as const).map((k) => (
          <Button key={k} size="sm" variant={k === kind ? 'default' : 'outline'} onClick={() => setKind(k)}>
            {k === 'progress' ? 'Progress rounds' : 'Final round'} · v{rubrics[k].version}
          </Button>
        ))}
      </div>
      <RubricEditor key={`${kind}-${rubrics[kind].id}`} base={base} rubric={rubrics[kind]} onSaved={load} setToast={setToast} />
    </div>
  );
}

function RubricEditor({
  base,
  rubric,
  onSaved,
  setToast
}: {
  base: string;
  rubric: RubricData;
  onSaved: () => Promise<void>;
  setToast: (m: string) => void;
}) {
  const [draft, setDraft] = useState(rubric);

  const save = async () => {
    try {
      const saved = await apiPut<RubricData>(`${base}/rubrics/${rubric.kind}`, {
        criteria: draft.criteria,
        scale: draft.scale,
        prompts: draft.prompts,
        instructions: draft.instructions
      });
      setToast(saved.version !== rubric.version ? `Saved as version ${saved.version}` : 'Rubric saved');
      await onSaved();
    } catch (e) {
      setToast(errorMessage(e));
    }
  };

  return (
    <Card className="grid gap-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13px] text-ink-3">
          Version {rubric.version}
          {rubric.frozen ? (
            <span className="pill pill-warn ml-2">
              frozen · used by round{rubric.used_by_rounds.length > 1 ? 's' : ''} {rubric.used_by_rounds.join(', ')} — saving
              creates v{rubric.version + 1}
            </span>
          ) : (
            <span className="pill ml-2">draft</span>
          )}
        </div>
        <Button size="sm" onClick={save}>
          Save rubric
        </Button>
      </div>

      <div>
        <div className="label-eyebrow mb-2">
          Criteria · only those marked “counts” are required and make up the score (weights normalised by their sum);
          everything else, including the text prompts, is optional for students
        </div>
        <div className="grid gap-2">
          {draft.criteria.map((c, i) => (
            <div key={i} className="grid items-center gap-2 md:grid-cols-[1.2fr_2fr_90px_auto_auto_auto]" dir="auto">
              <Input
                value={c.label}
                dir="auto"
                onChange={(e) => setDraft({ ...draft, criteria: draft.criteria.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })}
                placeholder="Label"
              />
              <Input
                value={c.description}
                dir="auto"
                onChange={(e) =>
                  setDraft({ ...draft, criteria: draft.criteria.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)) })
                }
                placeholder="Description"
              />
              <Input
                type="number"
                step="0.1"
                min="0.1"
                value={c.weight}
                onChange={(e) =>
                  setDraft({ ...draft, criteria: draft.criteria.map((x, j) => (j === i ? { ...x, weight: Number(e.target.value) } : x)) })
                }
              />
              <label className="flex items-center gap-1.5 whitespace-nowrap text-[13px]">
                <input
                  type="checkbox"
                  checked={c.counts !== false}
                  onChange={(e) =>
                    setDraft({ ...draft, criteria: draft.criteria.map((x, j) => (j === i ? { ...x, counts: e.target.checked } : x)) })
                  }
                />
                counts
              </label>
              <label className="flex items-center gap-1.5 whitespace-nowrap text-[13px]" title="A number from 0 to 100 instead of the scale">
                <input
                  type="checkbox"
                  checked={c.max != null}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      criteria: draft.criteria.map((x, j) => (j === i ? { ...x, max: e.target.checked ? 100 : null } : x))
                    })
                  }
                />
                0–100
              </label>
              <Button
                size="sm"
                variant="ghost"
                disabled={draft.criteria.length <= 1}
                onClick={() => setDraft({ ...draft, criteria: draft.criteria.filter((_, j) => j !== i) })}
              >
                ✕
              </Button>
            </div>
          ))}
          <Button
            size="sm"
            variant="soft"
            className="justify-self-start"
            onClick={() => setDraft({ ...draft, criteria: [...draft.criteria, { key: '', label: '', description: '', weight: 1, counts: false }] })}
          >
            + Criterion
          </Button>
        </div>
      </div>

      <div>
        <div className="label-eyebrow mb-2">Scale labels</div>
        <div className="grid gap-2 sm:grid-cols-5">
          {draft.scale.map((s, i) => (
            <label key={s.value} className="flex items-center gap-2 text-[13px]">
              <span className="font-semibold tnum">{s.value}</span>
              <Input
                dir="auto"
                value={s.label}
                onChange={(e) => setDraft({ ...draft, scale: draft.scale.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })}
              />
            </label>
          ))}
        </div>
      </div>

      <div>
        <div className="label-eyebrow mb-2">Text prompts · always optional for students</div>
        <div className="grid gap-2">
          {draft.prompts.map((p, i) => (
            <div key={i} className="grid items-center gap-2 md:grid-cols-[1fr_auto]">
              <Input
                dir="auto"
                value={p.label}
                onChange={(e) => setDraft({ ...draft, prompts: draft.prompts.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })}
              />
              <Button size="sm" variant="ghost" onClick={() => setDraft({ ...draft, prompts: draft.prompts.filter((_, j) => j !== i) })}>
                ✕
              </Button>
            </div>
          ))}
          <Button
            size="sm"
            variant="soft"
            className="justify-self-start"
            onClick={() => setDraft({ ...draft, prompts: [...draft.prompts, { key: '', label: '', required: false }] })}
          >
            + Prompt
          </Button>
        </div>
      </div>

      <div>
        <div className="label-eyebrow mb-2">Instructions shown above the form</div>
        <textarea
          dir="auto"
          className="min-h-[72px] w-full rounded-md border border-border bg-card px-3 py-2 text-sm"
          value={draft.instructions}
          onChange={(e) => setDraft({ ...draft, instructions: e.target.value })}
        />
      </div>
    </Card>
  );
}

/* =============== Reviews & participation =============== */

type ParticipationRow = {
  student_id: number;
  name: string;
  national_id: string;
  team_name: string | null;
  expected: number;
  completed: number;
  exempt: number;
  excluded: number;
  items: { presentation_id: number; team_name: string; session_number: number | null; state: string; exempt_reason: string }[];
};
type ReviewRow = {
  id: number;
  presentation_id: number;
  team_name: string;
  session_number: number | null;
  reviewer_kind: 'student' | 'llm';
  reviewer_name: string | null;
  reviewer_national_id: string | null;
  reviewer_team_name: string | null;
  scores: Record<string, number>;
  weighted_total: number | null;
  responses: Record<string, string>;
  llm_rationales: Record<string, string> | null;
  excluded: boolean;
  exclusion_reason: string;
  updated_at: string | null;
};

const STATE_PILL: Record<string, string> = {
  done: 'pill pill-ok',
  missing: 'pill pill-bad',
  exempt: 'pill pill-info',
  excluded: 'pill pill-warn'
};

function ReviewsTab({ base, round, run }: { base: string; round: RoundRow; run: Run }) {
  const [participation, setParticipation] = useState<ParticipationRow[]>([]);
  const [reviews, setReviews] = useState<ReviewRow[]>([]);
  const [filter, setFilter] = useState('');
  const load = useCallback(async () => {
    const [p, r] = await Promise.all([
      apiGet<ParticipationRow[]>(`${base}/rounds/${round.id}/participation`),
      apiGet<ReviewRow[]>(`${base}/rounds/${round.id}/reviews`)
    ]);
    setParticipation(p);
    setReviews(r);
  }, [base, round.id]);
  useEffect(() => {
    void load();
  }, [load]);
  const act = async (fn: () => Promise<unknown>, msg?: string) => {
    await run(fn, msg);
    await load();
  };

  const exempt = (s: ParticipationRow) => {
    const session = window.prompt(
      `Exempt ${s.name} — session number (leave empty for the whole round):`,
      ''
    );
    if (session === null) return;
    const reason = window.prompt('Reason (required, e.g. absence approved):', '');
    if (!reason) return;
    act(
      () =>
        apiPost(`${base}/rounds/${round.id}/exemptions`, {
          student_id: s.student_id,
          session_number: session.trim() ? Number(session) : null,
          exempt: true,
          reason
        }),
      'Exemption recorded'
    );
  };
  const unexempt = (s: ParticipationRow) =>
    act(() => apiPost(`${base}/rounds/${round.id}/exemptions`, { student_id: s.student_id, exempt: false }), 'Exemption removed');

  const toggleExclusion = (r: ReviewRow) => {
    if (r.excluded) {
      act(() => apiPost(`${base}/reviews/${r.id}/exclusion`, { excluded: false }), 'Review included again');
      return;
    }
    const reason = window.prompt('Why exclude this review from aggregation? (kept on record, never deleted)', '');
    if (!reason) return;
    act(() => apiPost(`${base}/reviews/${r.id}/exclusion`, { excluded: true, reason }), 'Review excluded');
  };

  const shownReviews = reviews.filter(
    (r) =>
      !filter ||
      `${r.team_name} ${r.reviewer_name ?? ''} ${Object.values(r.responses).join(' ')}`.toLowerCase().includes(filter.toLowerCase())
  );
  const totals = participation.reduce((a, s) => ({ e: a.e + s.expected, c: a.c + s.completed }), { e: 0, c: 0 });

  return (
    <div className="grid gap-4">
      <div className="hint hint-warm">
        <span className="hint-icon">!</span>
        <div>
          <strong className="text-ink">Reviewer identities are visible only here.</strong> Students and presenting teams
          never see who wrote a review — their pages show only aggregates and anonymised feedback, and exports replace
          reviewers with random pseudonyms. You see names to track participation and moderate content.
        </div>
      </div>

      {round.status === 'draft' || round.status === 'scheduling' ? (
        <Card className="text-[14px] text-ink-3">Review obligations are created when reviewing opens for this round.</Card>
      ) : (
        <>
          <div className="flex items-baseline justify-between">
            <h3 className="font-display text-[20px]">Participation</h3>
            <span className="text-[13px] text-ink-3">
              {totals.c}/{totals.e} required reviews done · each student’s own reviews only — a teammate’s review never
              counts for them
            </span>
          </div>
          <TableCard>
            <thead>
              <tr>
                <Th className="pl-5">Student</Th>
                <Th>Team</Th>
                <Th>Done</Th>
                <Th>Per presentation</Th>
                <Th className="pr-5 text-right">Exemption</Th>
              </tr>
            </thead>
            <tbody>
              {participation.map((s) => (
                <tr key={s.student_id} className="border-b border-line-soft last:border-b-0">
                  <Td className="pl-5">
                    <BilingualName name={s.name} />
                    <div className="font-mono text-[11px] text-ink-3">{s.national_id}</div>
                  </Td>
                  <Td className="text-ink-2">{s.team_name ?? '—'}</Td>
                  <Td className="tnum">
                    <span style={{ color: s.completed >= s.expected ? 'var(--ok)' : 'var(--bad)' }}>
                      {s.completed}/{s.expected}
                    </span>
                    {s.exempt ? <div className="text-[11px] text-ink-3">{s.exempt} exempt</div> : null}
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {s.items.map((i) => (
                        <span
                          key={i.presentation_id}
                          className={STATE_PILL[i.state] ?? 'pill'}
                          title={i.exempt_reason || `S${i.session_number ?? '—'}`}
                        >
                          {i.team_name}
                        </span>
                      ))}
                    </div>
                  </Td>
                  <Td className="pr-5 text-right">
                    <button className="text-[13px] text-forest hover:underline" onClick={() => exempt(s)}>
                      Exempt…
                    </button>
                    {s.exempt ? (
                      <button className="ml-3 text-[13px] text-ink-3 hover:underline" onClick={() => unexempt(s)}>
                        Clear
                      </button>
                    ) : null}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableCard>

          <div className="flex items-baseline justify-between gap-3">
            <h3 className="font-display text-[20px]">Individual reviews</h3>
            <Input className="h-9 max-w-[280px]" placeholder="Filter by team, reviewer, text…" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </div>
          <TableCard>
            <thead>
              <tr>
                <Th className="pl-5">Presenting team</Th>
                <Th>Reviewer</Th>
                <Th>Scores</Th>
                <Th>Feedback</Th>
                <Th className="pr-5 text-right">Moderation</Th>
              </tr>
            </thead>
            <tbody>
              {shownReviews.map((r) => (
                <tr key={r.id} className={`border-b border-line-soft last:border-b-0 ${r.excluded ? 'opacity-60' : ''}`}>
                  <Td className="pl-5">
                    <div className="font-semibold">{r.team_name}</div>
                    <div className="text-[11px] text-ink-3">S{r.session_number ?? '—'}</div>
                  </Td>
                  <Td>
                    {r.reviewer_kind === 'llm' ? (
                      <span className="pill pill-info">AI grader</span>
                    ) : (
                      <>
                        <BilingualName name={r.reviewer_name ?? '—'} />
                        <div className="text-[11px] text-ink-3">
                          {r.reviewer_national_id} · {r.reviewer_team_name ?? 'no team'}
                        </div>
                      </>
                    )}
                  </Td>
                  <Td className="tnum text-[12px]">
                    <div className="font-semibold">{fmt(r.weighted_total)}</div>
                    <div className="text-ink-3">{Object.values(r.scores).join(' · ')}</div>
                  </Td>
                  <Td className="max-w-[420px] text-[13px]" >
                    {Object.entries(r.responses)
                      .filter(([, v]) => v)
                      .map(([k, v]) => (
                        <p key={k} dir="auto" className="leading-snug">
                          {v}
                        </p>
                      ))}
                    {r.llm_rationales ? (
                      <details className="mt-1 text-[12px] text-ink-3">
                        <summary className="cursor-pointer">AI rationale</summary>
                        {Object.entries(r.llm_rationales).map(([k, v]) => (
                          <div key={k}>
                            <strong>{k}:</strong> {v}
                          </div>
                        ))}
                      </details>
                    ) : null}
                  </Td>
                  <Td className="pr-5 text-right">
                    {r.excluded ? (
                      <div className="mb-1 text-[12px] text-warn">Excluded: “{r.exclusion_reason}”</div>
                    ) : null}
                    <button className="text-[13px] text-forest hover:underline" onClick={() => toggleExclusion(r)}>
                      {r.excluded ? 'Include again' : 'Exclude…'}
                    </button>
                  </Td>
                </tr>
              ))}
              {!shownReviews.length ? (
                <tr>
                  <td colSpan={5} className="px-5 py-6 text-center text-[13px] text-ink-3">
                    No reviews yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </TableCard>
        </>
      )}
    </div>
  );
}

/* =============== Scores & export =============== */

type ScoresData = {
  criteria: { key: string; label: string; weight: number }[];
  teams: {
    presentation_id: number;
    team_name: string;
    project_title: string;
    session_number: number | null;
    valid_reviews: number;
    share: number | null;
    relative: number | null;
    mean_total: number | null;
    criterion_means: Record<string, number>;
  }[];
  students: {
    student_id: number;
    name: string;
    national_id: string;
    team_name: string | null;
    expected: number;
    completed: number;
    participation_rate: number | null;
    review_score: number | null;
    adjusted_review_score: number | null;
    team_share: number | null;
    raw: number | null;
    normalized: number | null;
    bonus: number;
    final: number | null;
    flags: string[];
  }[];
};

const FLAG_TEXT: Record<string, string> = {
  no_reviews: 'no reviews',
  imputed_review_score: 'fully exempt → class-average review score',
  no_team: 'no team',
  team_not_scored: 'team not yet scored'
};

function ScoresTab({
  base,
  courseId,
  round,
  run,
  setToast
}: {
  base: string;
  courseId: number;
  round: RoundRow;
  run: Run;
  setToast: (m: string) => void;
}) {
  const [scores, setScores] = useState<ScoresData | null>(null);
  const [settings, setSettings] = useState({
    target_mean: round.target_mean,
    target_std: round.target_std,
    missing_review_policy: round.missing_review_policy,
    participation_factor: round.participation_factor,
    llm_enabled: round.llm_enabled
  });
  const [llmBusy, setLlmBusy] = useState(false);
  const load = useCallback(async () => setScores(await apiGet<ScoresData>(`${base}/rounds/${round.id}/scores`)), [base, round.id]);
  useEffect(() => {
    void load();
  }, [load]);

  const saveSettings = async (e: FormEvent) => {
    e.preventDefault();
    await run(() => apiPatch(`${base}/rounds/${round.id}`, settings), 'Scoring settings saved');
    await load();
  };
  const runLlm = async () => {
    if (!window.confirm('Run the AI grader on every presentation in this round? It replaces any earlier AI review.')) return;
    setLlmBusy(true);
    try {
      const res = await apiPost<{ reviews: number }>(`${base}/rounds/${round.id}/llm-review`);
      setToast(`AI grader reviewed ${res.reviews} presentations`);
    } catch (err) {
      setToast(errorMessage(err));
    } finally {
      setLlmBusy(false);
    }
    await run(async () => undefined);
    await load();
  };
  const addBonus = async (s: ScoresData['students'][number]) => {
    const points = window.prompt(`Bonus points for ${s.name} in round ${round.number}:`, '');
    if (!points || Number.isNaN(Number(points))) return;
    const reason = window.prompt('Reason (required):', '');
    if (!reason) return;
    await run(
      () =>
        apiPost(`/api/courses/${courseId}/overrides`, {
          student_id: s.student_id,
          component: `peer_round_${round.number}_bonus`,
          delta: Number(points),
          reason
        }),
      'Bonus added (see Overrides to remove)'
    );
    await load();
  };

  const applyToGradebook = async () => {
    if (!window.confirm(`Write each student's round ${round.number} final score to the gradebook as an override (peer_round_${round.number})? Running it again updates those overrides.`)) return;
    await run(async () => {
      const res = await apiPost<{ created: number; updated: number; removed: number }>(`${base}/rounds/${round.id}/apply-to-gradebook`);
      setToast(`Applied to gradebook: ${res.created} added, ${res.updated} updated, ${res.removed} removed`);
    });
  };

  return (
    <div className="grid gap-4">
      {!round.counts_toward_grade ? (
        <div className="hint hint-warm">
          <span className="hint-icon">!</span>
          <div>
            <strong className="text-ink">Practice round.</strong> These scores are for trying the process only and are
            never part of any grade.
          </div>
        </div>
      ) : null}
      <div className="hint">
        <span className="hint-icon">i</span>
        <div className="leading-relaxed">
          <strong className="text-ink">How a round is scored.</strong> Each review’s criterion scores are combined with the
          rubric weights. Every reviewer’s totals are normalised to sum to 1 across the teams they reviewed, so only their
          relative judgement counts. <strong className="text-ink">Team score</strong> = the team’s share of all normalised
          score (shares sum to 1; ×relative shows it against the average team). <strong className="text-ink">Review score</strong>{' '}
          = Σ team score × the student’s own normalised score for that team.{' '}
          <strong className="text-ink">Raw</strong> = review score × own team’s score, normalised to sum to 1, then rescaled
          to the target mean and SD. <strong className="text-ink">Final</strong> = normalised + bonus. The AI grader counts
          as one more reviewer. Missing reviews are never zeros for the presenting team; a team with no valid reviews is
          “not yet scored”.
        </div>
      </div>

      <Card>
        <form onSubmit={saveSettings} className="grid items-end gap-3 md:grid-cols-[110px_110px_1.6fr_1.2fr_1fr_auto]">
          <div>
            <Label>Target mean</Label>
            <Input type="number" step="0.5" value={settings.target_mean} onChange={(e) => setSettings({ ...settings, target_mean: Number(e.target.value) })} />
          </div>
          <div>
            <Label>Target SD</Label>
            <Input type="number" step="0.5" value={settings.target_std} onChange={(e) => setSettings({ ...settings, target_std: Number(e.target.value) })} />
          </div>
          <div>
            <Label>Missing reviews</Label>
            <select
              className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm"
              value={settings.missing_review_policy}
              onChange={(e) => setSettings({ ...settings, missing_review_policy: e.target.value as 'missing' | 'zero' })}
            >
              <option value="missing">Treat as missing (average over reviews received)</option>
              <option value="zero">Literal share of all mass (missing = 0)</option>
            </select>
          </div>
          <label className="flex h-10 items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={settings.participation_factor}
              onChange={(e) => setSettings({ ...settings, participation_factor: e.target.checked })}
            />
            Scale review score by completion rate
          </label>
          <label className="flex h-10 items-center gap-2 text-[13px]">
            <input type="checkbox" checked={settings.llm_enabled} onChange={(e) => setSettings({ ...settings, llm_enabled: e.target.checked })} />
            AI grader
          </label>
          <Button size="sm" type="submit" variant="soft">
            Save
          </Button>
        </form>
        <div className="mt-4 flex flex-wrap gap-2 border-t border-line-soft pt-4">
          <Button size="sm" disabled={!round.llm_enabled || !round.rubric_version || llmBusy} onClick={runLlm}>
            {llmBusy ? 'AI grader running…' : '✦ Run AI grader for this round'}
          </Button>
          <a
            className="inline-flex items-center rounded-md border border-border bg-card px-2.5 py-1 text-[13px] text-ink hover:bg-paper-2"
            href={`${apiBase()}${base}/rounds/${round.id}/export.xlsx`}
          >
            ⬇ Export round (xlsx)
          </a>
          {round.counts_toward_grade ? (
            <Button
              size="sm"
              variant="soft"
              disabled={!round.released_at}
              title={round.released_at ? undefined : 'Release the results first'}
              onClick={applyToGradebook}
            >
              Apply to gradebook
            </Button>
          ) : null}
          <span className="self-center text-[12px] text-ink-3">
            Sheets: team scores, student scores, participation, and reviews with reviewers pseudonymised.
          </span>
        </div>
      </Card>

      {!scores ? (
        <div className="text-ink-3">Loading…</div>
      ) : (
        <>
          <h3 className="font-display text-[20px]">Team scores</h3>
          <TableCard>
            <thead>
              <tr>
                <Th className="pl-5">Team</Th>
                <Th>Session</Th>
                <Th className="text-right">Valid reviews</Th>
                <Th className="text-right">Team score</Th>
                <Th className="text-right">× avg</Th>
                <Th className="text-right">Mean total</Th>
                {scores.criteria.map((c) => (
                  <Th key={c.key} className="text-right">
                    <span title={c.label}>{c.key}</span>
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scores.teams.map((t) => (
                <tr key={t.presentation_id} className="border-b border-line-soft last:border-b-0">
                  <Td className="pl-5">
                    <div className="font-semibold">{t.team_name}</div>
                    <div className="text-[12px] text-ink-3">{t.project_title}</div>
                  </Td>
                  <Td>S{t.session_number ?? '—'}</Td>
                  <Td className="tnum text-right">{t.valid_reviews}</Td>
                  <Td className="tnum text-right font-semibold">
                    {t.share == null ? <span className="pill">not yet scored</span> : pct(t.share)}
                  </Td>
                  <Td className="tnum text-right">{fmt(t.relative)}</Td>
                  <Td className="tnum text-right">{fmt(t.mean_total)}</Td>
                  {scores.criteria.map((c) => (
                    <Td key={c.key} className="tnum text-right">
                      {fmt(t.criterion_means[c.key])}
                    </Td>
                  ))}
                </tr>
              ))}
            </tbody>
          </TableCard>

          <h3 className="font-display text-[20px]">Student scores</h3>
          <TableCard>
            <thead>
              <tr>
                <Th className="pl-5">Student</Th>
                <Th>Team</Th>
                <Th className="text-right">Done</Th>
                <Th className="text-right">Review score</Th>
                <Th className="text-right">Team score</Th>
                <Th className="text-right">Raw</Th>
                <Th className="text-right">Normalised</Th>
                <Th className="text-right">Bonus</Th>
                <Th className="pr-5 text-right">Final</Th>
              </tr>
            </thead>
            <tbody>
              {scores.students.map((s) => (
                <tr key={s.student_id} className="border-b border-line-soft last:border-b-0">
                  <Td className="pl-5">
                    <BilingualName name={s.name} />
                    <div className="font-mono text-[11px] text-ink-3">{s.national_id}</div>
                    {s.flags.length ? (
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {s.flags.map((f) => (
                          <span key={f} className="pill pill-warn">
                            {FLAG_TEXT[f] ?? f}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </Td>
                  <Td className="text-ink-2">{s.team_name ?? '—'}</Td>
                  <Td className="tnum text-right">
                    {s.completed}/{s.expected}
                  </Td>
                  <Td className="tnum text-right" >
                    {fmt(s.adjusted_review_score, 4)}
                    {s.participation_rate != null && s.participation_rate < 1 ? (
                      <div className="text-[11px] text-ink-3">×{s.participation_rate.toFixed(2)} completion</div>
                    ) : null}
                  </Td>
                  <Td className="tnum text-right">{pct(s.team_share)}</Td>
                  <Td className="tnum text-right">{fmt(s.raw, 4)}</Td>
                  <Td className="tnum text-right">{fmt(s.normalized, 1)}</Td>
                  <Td className="tnum text-right">
                    {s.bonus ? `+${s.bonus}` : ''}
                    <button className="ml-1.5 text-[12px] text-forest hover:underline" onClick={() => addBonus(s)}>
                      + bonus
                    </button>
                  </Td>
                  <Td className="tnum pr-5 text-right font-display text-[17px]">{fmt(s.final, 1)}</Td>
                </tr>
              ))}
            </tbody>
          </TableCard>
          <p className="text-[12px] text-ink-3">
            This round’s final score is reported on its own here and in the export. <strong>Apply to gradebook</strong>{' '}
            (after release) writes it as one override per student with component <code>peer_round_{round.number}</code>;
            it is not part of the course formula. Bonus points are stored as overrides with component{' '}
            <code>peer_round_{round.number}_bonus</code>.
          </p>
        </>
      )}
    </div>
  );
}
