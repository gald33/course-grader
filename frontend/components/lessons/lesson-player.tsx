'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { BlockList, TERRA_PILL } from '@/components/lessons/blocks';
import { ruleDone } from '@/components/lessons/completion';
import { InlineText, Ltr, plainInline } from '@/components/lessons/inline';
import { newUuid } from '@/components/lessons/student-backend';
import {
  LessonApiError,
  type AttemptInput,
  type AttemptResult,
  type Block,
  type Commitment,
  type CommitmentInput,
  type CommitmentsResult,
  type CompletionRule,
  type Experiment,
  type ExperimentInput,
  type ExperimentsResult,
  type FinalInput,
  type LessonBackend,
  type LessonContent,
  type LessonPayload,
  type LessonStep,
  type Progress,
  type ProgressPatch,
  type QuestionState,
  type StepStatus
} from '@/components/lessons/types';

/* The guided lesson (Hebrew, RTL, phone-first): one step at a time, a lesson
 * map, back/next, resume, and honest autosave. Talks only to a LessonBackend —
 * the student API, or the instructor's in-memory preview.
 *
 * Progress (position, viewed steps, self-reported acks, drafts) is saved with
 * revision checks. Unsent changes are kept in a local outbox, mirrored to
 * localStorage (cg-lesson-draft:<token>:<slug>:<tab id>, one entry per open
 * tab) until the server acknowledges them, so they survive a reload, a lost
 * network or a sign-in redirect. A 409 stale answer is rebased: the server's
 * state is taken and the unsent local changes are re-applied on top, then sent
 * once more automatically. "Saved" is shown only after the server answered.
 * The preview never touches storage. */

type BlockedCode = 'not_signed_in' | 'wrong_account' | 'withdrawn';
const BLOCKING: string[] = ['not_signed_in', 'wrong_account', 'withdrawn'];

type SaveState = { kind: 'idle' } | { kind: 'saving' } | { kind: 'saved' } | { kind: 'error'; message: string };

export type DraftStatus = 'saving' | 'saved' | 'error' | null;

/** Unsent per-question state for this visit (never saved): an option picked
 * but not sent, and the request id of a send that may be retried. */
export type PendingUi = { choice?: string | null; request?: { id: string; sig: string } };

/** What blocks, questions, the experiment log etc. can read and do. */
export type LessonApi = {
  preview: boolean;
  token: string | null;
  content: LessonContent;
  colabUrl: string | null;
  progress: Progress | null; // as the server last acknowledged it
  steps: Record<string, StepStatus>;
  questions: Record<string, QuestionState>;
  experiments: Experiment[];
  commitments: Commitment[];
  completedAt: string | null;
  /** The draft as the student sees it: unsent local text first, then the server's. */
  draft(key: string): string | undefined;
  setDraft(key: string, value: string | null): void;
  draftStatus(key: string): DraftStatus;
  /** The last progress save failed (or saving is blocked); unsent changes are kept. */
  saveFailed: boolean;
  acked(key: string): boolean;
  setAck(key: string, on: boolean): void;
  submitAttempt(body: AttemptInput): Promise<AttemptResult>;
  reveal(questionKey: string, requestId: string): Promise<AttemptResult>;
  saveExperiment(runUuid: string, body: ExperimentInput): Promise<ExperimentsResult>;
  deleteExperiment(runUuid: string, expectedRevision: number): Promise<ExperimentsResult>;
  /** After a stale edit: show the server's current version of one record. */
  replaceExperiment(runUuid: string, current: Experiment | null): void;
  commit(body: CommitmentInput): Promise<CommitmentsResult>;
  recordFinal(commitmentId: number, body: FinalInput): Promise<CommitmentsResult>;
  goToStep(key: string): void;
  /** Kept by the player, so it survives leaving a step and coming back. */
  pending(key: string): PendingUi;
};

/* ---------------- Outbox of unsent progress changes ---------------- */

type Pending = {
  step?: string;
  viewed: string[];
  acks: Record<string, boolean>; // true = add, false = remove
  drafts: Record<string, string | null>; // null = delete
};

const EMPTY: Pending = { viewed: [], acks: {}, drafts: {} };

function isEmpty(p: Pending) {
  return p.step === undefined && !p.viewed.length && !Object.keys(p.acks).length && !Object.keys(p.drafts).length;
}

/** b is newer than a. */
function merge(a: Pending, b: Pending): Pending {
  return {
    step: b.step ?? a.step,
    viewed: Array.from(new Set([...a.viewed, ...b.viewed])),
    acks: { ...a.acks, ...b.acks },
    drafts: { ...a.drafts, ...b.drafts }
  };
}

/** Drop what the server already has, so nothing is re-sent for nothing. */
function prune(p: Pending, server: Progress | null): Pending {
  return {
    step: p.step !== undefined && p.step !== (server?.current_step_key ?? undefined) ? p.step : undefined,
    viewed: p.viewed.filter((k) => !server?.viewed.includes(k)),
    acks: Object.fromEntries(Object.entries(p.acks).filter(([k, on]) => on !== (server?.acks.includes(k) ?? false))),
    drafts: Object.fromEntries(Object.entries(p.drafts).filter(([k, v]) => v !== (server?.drafts[k] ?? null)))
  };
}

function toPatch(p: Pending, revision: number): ProgressPatch {
  const body: ProgressPatch = { expected_revision: revision };
  if (p.step !== undefined) body.current_step_key = p.step;
  if (p.viewed.length) body.viewed_add = p.viewed;
  const add = Object.keys(p.acks).filter((k) => p.acks[k]);
  const remove = Object.keys(p.acks).filter((k) => !p.acks[k]);
  if (add.length) body.acks_add = add;
  if (remove.length) body.acks_remove = remove;
  if (Object.keys(p.drafts).length) body.drafts = p.drafts;
  return body;
}

/* The device mirror: one entry per open tab (<prefix>:<tab id>), so one tab's
 * save never erases another tab's unsent text. An entry records the server
 * revision it was written against and, for each unsent draft or tick, the
 * server values it may be replacing (what the server had, and what was on its
 * way there). On the next load every entry of this lesson is taken over, oldest
 * first: an entry still at the server's revision is restored as is; from an
 * older one only the changes the server hasn't moved past since are kept (and
 * never its position), so a device that was offline can't overwrite newer work
 * saved elsewhere. Entries from before this format (v1, a single key) have no
 * base and are restored as they always were. */

type MirrorBase = { drafts: Record<string, (string | null)[]>; acks: Record<string, boolean[]> };
type MirrorEntry = { key: string; savedAt: number; rev: number | null; base: MirrorBase | null; pending: Pending };

const strings = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);
const record = <T,>(v: unknown, ok: (x: unknown) => x is T): Record<string, T> =>
  v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).filter(([, x]) => ok(x))) : {};
const isDraftValue = (x: unknown): x is string | null => typeof x === 'string' || x === null;

function parsePending(parsed: unknown): Pending | null {
  if (!parsed || typeof parsed !== 'object') return null;
  const p = parsed as Record<string, unknown>;
  return {
    step: typeof p.step === 'string' ? p.step : undefined,
    viewed: strings(p.viewed),
    acks: record(p.acks, (x): x is boolean => typeof x === 'boolean'),
    drafts: record(p.drafts, isDraftValue)
  };
}

function parseBase(raw: unknown): MirrorBase {
  const b = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  return {
    drafts: record(b.drafts, (x): x is (string | null)[] => Array.isArray(x) && x.every(isDraftValue)),
    acks: record(b.acks, (x): x is boolean[] => Array.isArray(x) && x.every((y) => typeof y === 'boolean'))
  };
}

/** Every mirror entry of this lesson on this device, oldest first. */
function readMirrors(prefix: string): MirrorEntry[] {
  const out: MirrorEntry[] = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || (key !== prefix && !key.startsWith(`${prefix}:`))) continue;
      let parsed: Record<string, unknown> | null = null;
      try {
        parsed = JSON.parse(localStorage.getItem(key) ?? 'null');
      } catch {
        parsed = null;
      }
      const v2 = parsed?.v === 2;
      out.push({
        key,
        savedAt: typeof parsed?.saved_at === 'number' ? parsed.saved_at : 0,
        rev: v2 && typeof parsed?.rev === 'number' ? parsed.rev : null,
        base: v2 ? parseBase(parsed?.base) : null,
        pending: parsePending(parsed?.pending) ?? EMPTY // unreadable: still taken over (removed)
      });
    }
  } catch {
    /* storage unavailable */
  }
  return out.sort((a, b) => a.savedAt - b.savedAt);
}

/** What is still worth restoring from the entries (later ones win). */
function fromMirrors(entries: MirrorEntry[], server: Progress | null): Pending {
  const revision = server?.revision ?? 0;
  let out: Pending = EMPTY;
  for (const e of entries) {
    if (e.rev == null || e.rev === revision) {
      out = merge(out, e.pending);
      continue;
    }
    // The server saved something since: keep a change only where the server
    // still has what this entry was based on, and never the old position.
    const base = e.base ?? { drafts: {}, acks: {} };
    out = merge(out, {
      viewed: e.pending.viewed,
      acks: Object.fromEntries(
        Object.entries(e.pending.acks).filter(([k]) => base.acks[k]?.includes(server?.acks.includes(k) ?? false))
      ),
      drafts: Object.fromEntries(
        Object.entries(e.pending.drafts).filter(([k]) => base.drafts[k]?.includes(server?.drafts[k] ?? null))
      )
    });
  }
  return out;
}

function writeMirror(key: string, unsent: Pending, rev: number, base: MirrorBase) {
  try {
    if (!isEmpty(unsent)) {
      localStorage.setItem(key, JSON.stringify({ v: 2, saved_at: Date.now(), rev, base, pending: unsent }));
    } else localStorage.removeItem(key);
  } catch {
    /* storage unavailable — saving still works, just without the safety net */
  }
}

function removeMirrors(keys: string[]) {
  try {
    for (const k of keys) localStorage.removeItem(k);
  } catch {
    /* storage unavailable */
  }
}

const DRAFT_DELAY = 900;
const QUICK_DELAY = 250;
const MAX_WAIT = 4000; // flush during continuous typing at least this often
const RETRY_DELAYS = [2000, 5000, 10000, 20000, 30000];

type SaverHooks = {
  patch(body: ProgressPatch): Promise<{ progress: Progress; steps: Record<string, StepStatus> }>;
  storageKey: string | null; // null in the preview: never touch storage
  onSteps(steps: Record<string, StepStatus>): void;
  onBlocked(code: BlockedCode): void;
  changed(): void;
};

/** Revision-aware progress writer with a single request in flight. */
class ProgressSaver {
  server: Progress | null;
  pending: Pending = EMPTY;
  inflight: Pending | null = null;
  state: SaveState = { kind: 'idle' };
  blocked: BlockedCode | null = null;
  private savedKeys = new Set<string>();
  private timer: number | null = null;
  private firstUnsentAt: number | null = null;
  private failures = 0;
  private staleRetried = false;
  private disposed = false;

  constructor(private hooks: SaverHooks, server: Progress | null) {
    this.server = server;
  }

  dispose() {
    this.disposed = true;
    if (this.timer != null) window.clearTimeout(this.timer);
    this.timer = null;
  }

  private unsent(): Pending {
    return this.inflight ? merge(this.inflight, this.pending) : this.pending;
  }

  private persist() {
    const key = this.hooks.storageKey;
    if (!key) return;
    const unsent = this.unsent();
    // For each unsent value: the server values it may be replacing — what the
    // server has now, and what is on its way there (in flight).
    const base: MirrorBase = { drafts: {}, acks: {} };
    for (const k of Object.keys(unsent.drafts)) {
      const now = this.server?.drafts[k] ?? null;
      const sending = this.inflight && k in this.inflight.drafts ? this.inflight.drafts[k] : now;
      base.drafts[k] = sending === now ? [now] : [now, sending];
    }
    for (const k of Object.keys(unsent.acks)) {
      const now = !!this.server?.acks.includes(k);
      const sending = this.inflight && k in this.inflight.acks ? this.inflight.acks[k] : now;
      base.acks[k] = sending === now ? [now] : [now, sending];
    }
    writeMirror(key, unsent, this.server?.revision ?? 0, base);
  }

  private setState(s: SaveState) {
    this.state = s;
    this.hooks.changed();
  }

  /** Restore unsent changes from an earlier visit (local mirror). */
  restore(p: Pending) {
    this.pending = merge(this.pending, prune(p, this.server));
    this.persist();
  }

  draft(key: string): string | undefined {
    if (key in this.pending.drafts) return this.pending.drafts[key] ?? undefined;
    if (this.inflight && key in this.inflight.drafts) return this.inflight.drafts[key] ?? undefined;
    return this.server?.drafts[key];
  }

  acked(key: string): boolean {
    if (key in this.pending.acks) return this.pending.acks[key];
    if (this.inflight && key in this.inflight.acks) return this.inflight.acks[key];
    return !!this.server?.acks.includes(key);
  }

  draftStatus(key: string): DraftStatus {
    const unsent = key in this.pending.drafts || (!!this.inflight && key in this.inflight.drafts);
    if (unsent) return this.blocked || this.state.kind === 'error' ? 'error' : 'saving';
    return this.savedKeys.has(key) ? 'saved' : null;
  }

  change(p: Partial<Pending>, delay: number) {
    this.pending = merge(this.pending, { ...EMPTY, ...p });
    for (const k of Object.keys(p.drafts ?? {})) this.savedKeys.delete(k);
    // Unsent changes: never leave an earlier "saved" on screen (an error stays
    // up until a save succeeds).
    if (!isEmpty(prune(this.pending, this.server)) && this.state.kind !== 'error') this.state = { kind: 'saving' };
    this.persist();
    this.hooks.changed();
    if (this.firstUnsentAt == null) this.firstUnsentAt = Date.now();
    const waited = Date.now() - this.firstUnsentAt;
    this.schedule(waited > MAX_WAIT ? 0 : delay);
  }

  private schedule(delay: number) {
    if (this.blocked || this.disposed) return;
    if (this.timer != null) window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => {
      this.timer = null;
      void this.flush();
    }, delay);
  }

  /** Manual retry (the "נסו שוב" button), also after signing in again elsewhere. */
  retry() {
    this.blocked = null;
    this.failures = 0;
    this.staleRetried = false;
    void this.flush();
  }

  async flush(): Promise<void> {
    if (this.timer != null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.inflight || this.blocked || this.disposed) return;
    const batch = prune(this.pending, this.server);
    this.pending = EMPTY;
    if (isEmpty(batch)) {
      // Everything is in sync (blocked and failed batches return earlier or are
      // merged back): an earlier "not saved" no longer applies either.
      this.firstUnsentAt = null;
      this.persist();
      if (this.state.kind === 'saving' || this.state.kind === 'error') this.setState({ kind: this.server ? 'saved' : 'idle' });
      else this.hooks.changed();
      return;
    }
    this.inflight = batch;
    this.firstUnsentAt = null; // the max wait counts again from the next change
    this.setState({ kind: 'saving' });
    try {
      const res = await this.hooks.patch(toPatch(batch, this.server?.revision ?? 0));
      if (this.disposed) return;
      this.inflight = null;
      this.server = res.progress;
      this.failures = 0;
      this.staleRetried = false;
      for (const [k, v] of Object.entries(batch.drafts)) {
        // A deleted draft (e.g. after the answer was sent) is not "a saved draft".
        if (v !== null && !(k in this.pending.drafts)) this.savedKeys.add(k);
        else this.savedKeys.delete(k);
      }
      this.hooks.onSteps(res.steps);
      this.persist();
      if (isEmpty(prune(this.pending, this.server))) {
        this.setState({ kind: 'saved' });
      } else {
        this.hooks.changed();
        this.schedule(QUICK_DELAY);
      }
    } catch (e) {
      if (this.disposed) return;
      // Nothing is lost: the batch goes back under any newer local changes.
      this.inflight = null;
      this.pending = merge(batch, this.pending);
      this.persist();
      const err = e instanceof LessonApiError ? e : new LessonApiError('error', e instanceof Error ? e.message : String(e), 0);
      if (err.code === 'stale') {
        // Another tab or device saved first: take its state, keep ours on top.
        if ('current' in err.detail) this.server = (err.detail.current as Progress | null) ?? null;
        if (err.detail.steps && typeof err.detail.steps === 'object') {
          this.hooks.onSteps(err.detail.steps as Record<string, StepStatus>);
        }
        if (!this.staleRetried) {
          this.staleRetried = true;
          return this.flush();
        }
        this.setState({ kind: 'error', message: 'השיעור עודכן גם בלשונית או במכשיר אחר. השינויים שלך שמורים במכשיר.' });
        return;
      }
      if (BLOCKING.includes(err.code)) {
        this.blocked = err.code as BlockedCode;
        this.setState({ kind: 'error', message: err.message });
        this.hooks.onBlocked(this.blocked);
        return;
      }
      this.setState({ kind: 'error', message: err.message });
      if (err.code === 'network') {
        const delay = RETRY_DELAYS[Math.min(this.failures, RETRY_DELAYS.length - 1)];
        this.failures += 1;
        this.schedule(delay);
      }
    }
  }
}

/* ---------------- Helpers ---------------- */

function readHashStep(): string | null {
  try {
    return new URLSearchParams(window.location.hash.replace(/^#/, '')).get('step');
  } catch {
    return null;
  }
}

function writeHashStep(key: string) {
  const url = `${window.location.pathname}${window.location.search}#step=${encodeURIComponent(key)}`;
  window.history.replaceState(window.history.state, '', url);
}

function findAck(blocks: Block[], key: string): Extract<Block, { type: 'ack' }> | null {
  for (const b of blocks) {
    if (b.type === 'ack' && b.key === key) return b;
    if (b.type === 'section' || b.type === 'expander') {
      const inner = findAck(b.blocks, key);
      if (inner) return inner;
    }
  }
  return null;
}

function loginHref() {
  const next = `${window.location.pathname}${window.location.hash}`;
  return `/login?next=${encodeURIComponent(next)}`;
}

const BLOCKED_CARD_ID = 'lesson-blocked-card';

/* ---------------- Player ---------------- */

export function LessonPlayer({
  backend,
  token,
  banner
}: {
  backend: LessonBackend;
  token: string | null;
  banner?: React.ReactNode;
}) {
  // Taken once, at mount (remount with a key to switch lessons or versions):
  // a backend built inline on every render must not reload the lesson, and
  // the preview backend keeps its in-memory state in the instance.
  const backendRef = useRef(backend);
  const tokenRef = useRef(token);
  const preview = backendRef.current.mode === 'preview';
  const [payload, setPayload] = useState<LessonPayload | null>(null);
  const [loadError, setLoadError] = useState<LessonApiError | null>(null);
  const [steps, setSteps] = useState<Record<string, StepStatus>>({});
  const [questions, setQuestions] = useState<Record<string, QuestionState>>({});
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [commitments, setCommitments] = useState<Commitment[]>([]);
  const [completedAt, setCompletedAt] = useState<string | null>(null);
  const [stepKey, setStepKey] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<BlockedCode | null>(null);
  const [mapOpen, setMapOpen] = useState(false);
  const [reloadCount, setReloadCount] = useState(0);
  const [, setTick] = useState(0);
  const saverRef = useRef<ProgressSaver | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false); // focus the step heading only after the student navigates
  const tabId = useRef(newUuid()); // this tab's own entry in the device mirror
  const pendingUi = useRef(new Map<string, PendingUi>());

  useEffect(() => {
    let cancelled = false;
    const be = backendRef.current;
    const tk = tokenRef.current;
    setLoadError(null);
    be.load()
      .then((data) => {
        if (cancelled) return;
        const prefix = be.mode !== 'preview' && tk ? `cg-lesson-draft:${tk}:${data.lesson.slug}` : null;
        const storageKey = prefix ? `${prefix}:${tabId.current}` : null;
        const saver = new ProgressSaver(
          {
            patch: (body) => be.patchProgress(body),
            storageKey,
            onSteps: setSteps,
            onBlocked: setBlocked,
            changed: () => {
              if (saver.server?.completed_at) setCompletedAt(saver.server.completed_at);
              setTick((t) => t + 1);
            }
          },
          data.progress
        );
        saverRef.current?.dispose();
        saverRef.current = saver;
        // Take over what this device kept for the lesson (earlier visits, closed
        // or blocked tabs): it is now this tab's to send, under this tab's entry.
        const entries = prefix ? readMirrors(prefix) : [];
        const stored = entries.length ? fromMirrors(entries, data.progress) : null;
        if (stored) saver.restore(stored);
        removeMirrors(entries.map((e) => e.key).filter((k) => k !== storageKey));

        setPayload(data);
        setSteps(data.steps);
        setQuestions(data.questions);
        setExperiments(data.experiments);
        setCommitments(data.commitments);
        setCompletedAt(data.progress?.completed_at ?? null);

        // Resume: the address (#step=… survives a trip to Colab and back),
        // then unsent local position, then the saved one, then the start.
        const keys = data.content.steps.map((s) => s.key);
        const start =
          [readHashStep(), stored?.step, data.progress?.current_step_key].find((k): k is string => !!k && keys.includes(k)) ??
          keys[0];
        if (start) {
          setStepKey(start);
          writeHashStep(start);
          saver.change({ step: start, viewed: [start] }, QUICK_DELAY);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setLoadError(e instanceof LessonApiError ? e : new LessonApiError('error', e instanceof Error ? e.message : String(e), 0));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadCount]);

  useEffect(() => () => saverRef.current?.dispose(), []);

  // Leaving the tab (e.g. for Colab) sends what's waiting right away; coming
  // back online retries a failed save.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === 'hidden') void saverRef.current?.flush();
    };
    const onOnline = () => {
      const s = saverRef.current;
      if (s && s.state.kind === 'error' && !s.blocked) s.retry();
    };
    document.addEventListener('visibilitychange', onHide);
    window.addEventListener('online', onOnline);
    return () => {
      document.removeEventListener('visibilitychange', onHide);
      window.removeEventListener('online', onOnline);
    };
  }, []);

  const goToStep = useCallback(
    (key: string) => {
      const saver = saverRef.current;
      if (!payload || !saver || !payload.content.steps.some((s) => s.key === key)) return;
      moved.current = true;
      setStepKey(key);
      writeHashStep(key);
      saver.change({ step: key, viewed: [key] }, QUICK_DELAY);
    },
    [payload]
  );

  // Someone edits the address bar's #step=…
  useEffect(() => {
    const onHash = () => {
      const k = readHashStep();
      if (k && k !== stepKey) goToStep(k);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [goToStep, stepKey]);

  useEffect(() => {
    if (!moved.current) return;
    const h = headingRef.current;
    if (!h) return;
    h.focus({ preventScroll: true });
    h.scrollIntoView({ block: 'start' });
  }, [stepKey]);

  const loginCard = (
    <Card tone="warn" id={BLOCKED_CARD_ID}>
      <h2 className="font-hebrew text-[20px]">צריך להתחבר</h2>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
        כדי לראות את השיעור ולשמור את ההתקדמות צריך להיות מחוברים לחשבון שלכם. מה שכבר כתבתם ולא נשמר נשאר במכשיר הזה, ויישלח
        אחרי ההתחברות.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <a
          href={typeof window !== 'undefined' ? loginHref() : '/login'}
          className="inline-flex h-11 items-center rounded-md bg-forest px-5 text-[15px] font-semibold text-paper"
        >
          כניסה לחשבון
        </a>
        <button
          type="button"
          className="text-[14px] text-forest underline"
          onClick={() => {
            if (payload && saverRef.current) {
              setBlocked(null);
              saverRef.current.retry();
            } else setReloadCount((n) => n + 1);
          }}
        >
          כבר התחברתי בלשונית אחרת – לנסות שוב
        </button>
      </div>
    </Card>
  );

  const wrongAccountCard = (
    <Card tone="warn" id={BLOCKED_CARD_ID}>
      <h2 className="font-hebrew text-[20px]">הקישור שייך לחשבון אחר</h2>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
        נראה שהמכשיר הזה מחובר לחשבון של סטודנט/ית אחר/ת מזה שהקישור הזה שייך לו. הקישור לשיעור אישי, והתשובות נשמרות לבעל/ת
        הקישור בלבד. אם זה לא הקישור שלכם – עברו לעמוד הקורס שלכם ופתחו משם את השיעור. אם זה הקישור שלכם – התנתקו והיכנסו עם
        החשבון שלכם.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {/* Plain /login (no next): a signed-in student goes on to their own course page. */}
        <a
          href="/login"
          className="inline-flex h-11 items-center rounded-md bg-forest px-5 text-[15px] font-semibold text-paper"
        >
          לעמוד הקורס שלי
        </a>
        <button
          type="button"
          onClick={async () => {
            try {
              await fetch('/api/student-auth/logout', { method: 'POST', credentials: 'same-origin' });
            } finally {
              window.location.assign(loginHref());
            }
          }}
          className="inline-flex h-11 items-center rounded-md border border-forest px-5 text-[15px] font-semibold text-forest"
        >
          התנתקות וכניסה מחדש
        </button>
      </div>
    </Card>
  );

  if (loadError && !payload) {
    return (
      <Shell banner={banner}>
        <main className="mx-auto w-full max-w-[640px] px-4 pb-24 pt-8">
        {loadError.code === 'not_signed_in' ? (
          loginCard
        ) : loadError.code === 'wrong_account' ? (
          wrongAccountCard
        ) : (
          <Card tone="bad">
            <p role="alert" className="text-[15px]">
              {loadError.message}
            </p>
            <div className="mt-3 flex flex-wrap gap-3 text-[14px]">
              {loadError.code === 'network' || loadError.code === 'error' ? (
                <button type="button" className="text-forest underline" onClick={() => setReloadCount((n) => n + 1)}>
                  נסו שוב
                </button>
              ) : null}
              {token && loadError.code !== 'invalid_link' ? (
                <a href={`/r/${token}`} className="text-forest underline">
                  לעמוד הקורס
                </a>
              ) : null}
            </div>
          </Card>
        )}
        </main>
      </Shell>
    );
  }

  const saver = saverRef.current;
  if (!payload || !saver || !stepKey) {
    return (
      <Shell banner={banner}>
        <main className="mx-auto w-full max-w-[640px] px-4 py-16 text-center text-ink-3">טוען…</main>
      </Shell>
    );
  }

  const be = backendRef.current;
  const content = payload.content;
  const allSteps = content.steps;
  const required = allSteps.filter((s) => !s.optional);
  const requiredDone = required.filter((s) => steps[s.key]?.completed).length;
  const index = Math.max(
    0,
    allSteps.findIndex((s) => s.key === stepKey)
  );
  const step = allSteps[index];
  const prev = index > 0 ? allSteps[index - 1] : null;
  const next = index < allSteps.length - 1 ? allSteps[index + 1] : null;

  const apply = {
    attempt: (r: AttemptResult) => {
      setQuestions((q) => ({ ...q, [r.question_key]: r.question }));
      setSteps(r.steps);
      setCompletedAt(r.completed_at ?? null);
    },
    experiments: (r: ExperimentsResult) => {
      setExperiments(r.experiments);
      setSteps(r.steps);
      setCompletedAt(r.completed_at ?? null);
    },
    commitments: (r: CommitmentsResult) => {
      setCommitments(r.commitments);
      setSteps(r.steps);
      setCompletedAt(r.completed_at ?? null);
    }
  };
  const write = async <T,>(fn: () => Promise<T>, done: (r: T) => void): Promise<T> => {
    try {
      const r = await fn();
      done(r);
      return r;
    } catch (e) {
      if (e instanceof LessonApiError && BLOCKING.includes(e.code)) setBlocked(e.code as BlockedCode);
      throw e;
    }
  };

  const api: LessonApi = {
    preview,
    token,
    content,
    colabUrl: payload.colab_url,
    progress: saver.server,
    steps,
    questions,
    experiments,
    commitments,
    completedAt,
    draft: (key) => saver.draft(key),
    setDraft: (key, value) => saver.change({ drafts: { [key]: value } }, DRAFT_DELAY),
    draftStatus: (key) => saver.draftStatus(key),
    saveFailed: saver.state.kind === 'error' || !!saver.blocked,
    acked: (key) => saver.acked(key),
    setAck: (key, on) => saver.change({ acks: { [key]: on } }, QUICK_DELAY),
    submitAttempt: (body) => write(() => be.submitAttempt(body), apply.attempt),
    reveal: (q, id) => write(() => be.reveal(q, id), apply.attempt),
    saveExperiment: (run, body) => write(() => be.saveExperiment(run, body), apply.experiments),
    deleteExperiment: (run, rev) => write(() => be.deleteExperiment(run, rev), apply.experiments),
    replaceExperiment: (run, current) =>
      setExperiments((list) => {
        if (!current) return list.filter((e) => e.run_uuid !== run);
        return list.some((e) => e.run_uuid === run) ? list.map((e) => (e.run_uuid === run ? current : e)) : [...list, current];
      }),
    commit: (body) => write(() => be.commit(body), apply.commitments),
    recordFinal: (id, body) => write(() => be.recordFinal(id, body), apply.commitments),
    goToStep,
    pending: (key) => {
      let entry = pendingUi.current.get(key);
      if (!entry) {
        entry = {};
        pendingUi.current.set(key, entry);
      }
      return entry;
    }
  };

  return (
    <Shell banner={banner}>
      <StatusBar
        preview={preview}
        step={step}
        state={saver.state}
        blocked={blocked}
        onRetry={() => {
          setBlocked(null);
          saver.retry();
        }}
        onShowBlocked={() => {
          const card = document.getElementById(BLOCKED_CARD_ID);
          card?.scrollIntoView({ block: 'start' });
          card?.focus({ preventScroll: true });
        }}
      />
      <main className="mx-auto w-full max-w-[640px] px-4 pb-24 pt-4">
        <header className="pb-2">
          {token ? (
            <nav aria-label="קישורים" className="mb-1 flex flex-wrap gap-x-4 text-[14px]">
              <a href={`/r/${token}`} className="inline-flex min-h-[40px] items-center text-forest hover:underline">
                → לעמוד הקורס
              </a>
              <a href={`/r/${token}/lessons`} className="inline-flex min-h-[40px] items-center text-forest hover:underline">
                כל השיעורים
              </a>
            </nav>
          ) : null}
          {/* The course line and the guiding question open the lesson (step A); later steps keep a smaller title. */}
          {index === 0 ? (
            <div className="text-[12px] tracking-wide text-ink-2">
              {payload.course.name}
              {payload.course.code ? (
                <>
                  {' '}
                  · <Ltr>{payload.course.code}</Ltr>
                </>
              ) : null}
            </div>
          ) : null}
          <h1 className={`font-hebrew leading-tight ${index === 0 ? 'text-[26px]' : 'text-[18px] text-ink-2'}`}>{content.title}</h1>
          {index === 0 ? (
            <p className="mt-1 text-[15px] text-ink-2">
              <InlineText text={content.guiding_question} />
            </p>
          ) : null}
          {/* completed_at is when the student first finished; the banner follows the current evidence. */}
          {completedAt && required.length > 0 && requiredDone === required.length ? (
            <p className="mt-2 text-[14px] text-ok">✓ השלמת את כל שלבי החובה. השלמה אינה ציון – אפשר לחזור לכל שלב.</p>
          ) : null}
        </header>

        {blocked === 'not_signed_in' ? loginCard : null}
        {blocked === 'wrong_account' ? wrongAccountCard : null}
        {blocked === 'withdrawn' ? (
          <Card tone="warn">
            <p className="text-[15px] leading-relaxed">
              ההרשמה שלך לקורס בוטלה, ולכן אפשר לעיין בשיעור אבל לא לשמור בו שינויים. אם זו טעות, פנו למרצה.
            </p>
          </Card>
        ) : null}

        <LessonMap
          steps={allSteps}
          status={steps}
          current={step.key}
          requiredDone={requiredDone}
          requiredTotal={required.length}
          open={mapOpen}
          setOpen={setMapOpen}
          onPick={goToStep}
        />

        <article key={step.key} aria-labelledby="lesson-step-title" className="mt-5 grid grid-cols-1 gap-4">
          <header>
            <div className="text-[13px] text-ink-2">
              {step.optional ? (
                <span className={TERRA_PILL}>הרחבה לבחירה</span>
              ) : (
                <>
                  שלב <Ltr>{step.letter}</Ltr> · {required.findIndex((s) => s.key === step.key) + 1} מתוך {required.length}
                </>
              )}
            </div>
            <h2
              id="lesson-step-title"
              ref={headingRef}
              tabIndex={-1}
              className="mt-1 scroll-mt-16 font-hebrew text-[24px] leading-tight outline-none"
            >
              <span
                aria-hidden
                className="me-2 inline-grid h-9 min-w-9 place-items-center rounded-md bg-forest px-1.5 align-middle font-sans text-[17px] font-semibold text-paper"
              >
                {step.letter}
              </span>
              <span className="sr-only">שלב {step.letter}: </span>
              <InlineText text={step.title} />
            </h2>
            <p className="mt-2 rounded-md border-s-4 border-forest bg-forest-tint px-3 py-2 text-[15px] leading-relaxed">
              <span className="font-semibold">שאלת השלב: </span>
              <InlineText text={step.goal} />
            </p>
            {step.optional ? (
              <p className="mt-2 text-[14px] text-ink-2">
                הרחבה לבחירה – לא נדרשת כדי להשלים את השיעור, ולא נספרת ב״{requiredDone} מתוך {required.length}״.
              </p>
            ) : null}
            {index === 0 && content.intro ? (
              <p className="mt-3 text-[15px] leading-relaxed text-ink-2">
                <InlineText text={content.intro} />
              </p>
            ) : null}
          </header>

          <BlockList blocks={step.blocks} api={api} />

          <StepChecklist step={step} status={steps[step.key]} api={api} />

          {step.next_hint ? (
            <p className="text-[14px] leading-relaxed text-ink-2">
              <InlineText text={step.next_hint} />
            </p>
          ) : null}

          <nav aria-label="מעבר בין שלבים" className="mt-2 flex items-stretch justify-between gap-3">
            {prev ? (
              <button
                type="button"
                onClick={() => goToStep(prev.key)}
                className="flex min-h-[52px] max-w-[48%] items-center gap-2 rounded-md border border-border bg-card px-3 text-right text-[14px]"
              >
                <span aria-hidden className="text-[18px]">
                  →
                </span>
                <span className="min-w-0">
                  <span className="block font-semibold">הקודם</span>
                  <span className="block truncate text-[12px] text-ink-3">
                    <Ltr>{prev.letter}</Ltr> · {plainInline(prev.title)}
                  </span>
                </span>
              </button>
            ) : (
              <span />
            )}
            {next ? (
              <button
                type="button"
                onClick={() => goToStep(next.key)}
                className="flex min-h-[52px] max-w-[52%] items-center gap-2 rounded-md bg-forest px-4 text-right text-[14px] text-paper"
              >
                <span className="min-w-0">
                  <span className="block font-semibold">{next.optional ? 'להרחבה (לבחירה)' : 'לשלב הבא'}</span>
                  <span className="block truncate text-[12px] text-paper/80">
                    <Ltr>{next.letter}</Ltr> · {plainInline(next.title)}
                  </span>
                </span>
                <span aria-hidden className="text-[18px]">
                  ←
                </span>
              </button>
            ) : (
              <span className="self-center text-[14px] text-ink-3">סוף השיעור</span>
            )}
          </nav>
        </article>
      </main>
    </Shell>
  );
}

/* ---------------- Pieces ---------------- */

function Shell({ children, banner }: { children: React.ReactNode; banner?: React.ReactNode }) {
  return (
    <div dir="rtl" lang="he" className="min-h-screen">
      {banner}
      {children}
    </div>
  );
}

function Card({ tone, id, children }: { tone: 'warn' | 'bad'; id?: string; children: React.ReactNode }) {
  return (
    <section
      id={id}
      tabIndex={id ? -1 : undefined}
      className={`mt-3 scroll-mt-16 rounded-lg border bg-card p-5 shadow-card outline-none ${tone === 'bad' ? 'border-bad-soft' : 'border-warn-soft'}`}
    >
      {children}
    </section>
  );
}

// What the sticky bar says when saving is blocked (also when a write, not the
// autosave, was the one that found out).
const BLOCKED_TEXT: Record<BlockedCode, string> = {
  not_signed_in: 'צריך להתחבר כדי לשמור. מה שכתבתם נשאר במכשיר הזה ויישלח אחרי ההתחברות.',
  wrong_account: 'המכשיר מחובר לחשבון אחר מזה שהקישור שייך לו.',
  withdrawn: 'ההרשמה לקורס בוטלה, ולכן אי אפשר לשמור שינויים.'
};

function StatusBar({
  preview,
  step,
  state,
  blocked,
  onRetry,
  onShowBlocked
}: {
  preview: boolean;
  step: LessonStep;
  state: SaveState;
  blocked: BlockedCode | null;
  onRetry: () => void;
  onShowBlocked: () => void;
}) {
  const message = blocked ? BLOCKED_TEXT[blocked] : state.kind === 'error' ? state.message : null;
  return (
    <div
      className={`${preview ? '' : 'sticky top-0 z-30'} border-b border-line-soft bg-paper/95 backdrop-blur`}
    >
      <div className="mx-auto flex min-h-[44px] w-full max-w-[640px] items-center justify-between gap-3 px-4 text-[13px]">
        <span className="min-w-0 truncate text-ink-2">
          שלב <Ltr>{step.letter}</Ltr> · {plainInline(step.title)}
        </span>
        <span role="status" aria-live="polite" className="flex shrink-0 items-center gap-2">
          {preview ? (
            <span className="font-semibold text-[#9a5533]">תצוגה מקדימה – שום דבר לא נשמר</span>
          ) : blocked ? (
            // Blocked: the action that unblocks it, right here (the card is at the top of the page).
            <>
              <span className="font-semibold text-bad">⚠ לא נשמר</span>
              {blocked === 'not_signed_in' ? (
                <a href={loginHref()} className="rounded border border-bad px-2 py-0.5 text-bad">
                  כניסה לחשבון
                </a>
              ) : blocked === 'wrong_account' ? (
                <button type="button" onClick={onShowBlocked} className="rounded border border-bad px-2 py-0.5 text-bad">
                  מה עושים?
                </button>
              ) : null}
            </>
          ) : state.kind === 'saving' ? (
            <span className="text-ink-2">שומר…</span>
          ) : state.kind === 'saved' ? (
            <span className="text-ok">✓ נשמר</span>
          ) : state.kind === 'error' ? (
            <>
              <span className="font-semibold text-bad" title={state.message}>
                ⚠ לא נשמר – נסו שוב
              </span>
              <button type="button" onClick={onRetry} className="rounded border border-bad px-2 py-0.5 text-bad">
                ניסיון חוזר
              </button>
            </>
          ) : (
            <span className="text-ink-2">שמירה אוטומטית</span>
          )}
        </span>
      </div>
      {!preview && message ? <p className="mx-auto w-full max-w-[640px] px-4 pb-1.5 text-[12px] text-ink-2">{message}</p> : null}
    </div>
  );
}

function statusWords(s: StepStatus | undefined) {
  if (s?.completed) return { icon: '✓', text: 'הושלם' };
  if (s?.viewed) return { icon: '◐', text: 'נפתח' };
  return { icon: '○', text: 'טרם נפתח' };
}

function LessonMap({
  steps,
  status,
  current,
  requiredDone,
  requiredTotal,
  open,
  setOpen,
  onPick
}: {
  steps: LessonStep[];
  status: Record<string, StepStatus>;
  current: string;
  requiredDone: number;
  requiredTotal: number;
  open: boolean;
  setOpen: (v: boolean) => void;
  onPick: (key: string) => void;
}) {
  return (
    <nav aria-label="מפת השיעור" className="mt-3 rounded-lg border border-border bg-card p-3 shadow-soft">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[14px]">
          <span className="font-semibold">מפת השיעור</span>
          <span className="text-ink-2">
            {' '}
            · {requiredDone} מתוך {requiredTotal} שלבי חובה הושלמו
          </span>
        </span>
        <button
          type="button"
          aria-expanded={open}
          aria-controls="lesson-map-list"
          onClick={() => setOpen(!open)}
          className="inline-flex min-h-[40px] shrink-0 items-center rounded px-1 text-[13px] text-forest underline"
        >
          {open ? 'תצוגה מקוצרת' : 'כל השלבים'}
        </button>
      </div>
      <div className="progress-bar mt-2" aria-hidden>
        <span style={{ width: `${requiredTotal ? (requiredDone / requiredTotal) * 100 : 0}%` }} />
      </div>
      {open ? (
        <ol id="lesson-map-list" className="mt-2 grid grid-cols-1 gap-1">
          {steps.map((s) => {
            const w = statusWords(status[s.key]);
            const here = s.key === current;
            return (
              <li key={s.key}>
                <button
                  type="button"
                  aria-current={here ? 'step' : undefined}
                  onClick={() => onPick(s.key)}
                  className={`flex min-h-[44px] w-full items-center gap-2 rounded-md px-2 text-right text-[14px] ${
                    here ? 'bg-forest-tint ring-1 ring-forest' : 'hover:bg-paper-2'
                  }`}
                >
                  <span
                    className={`grid h-7 min-w-7 place-items-center rounded px-1 text-[13px] font-semibold ${
                      s.optional ? 'border border-dashed border-terracotta text-[#9a5533]' : 'bg-paper-2 text-ink'
                    }`}
                  >
                    {s.letter}
                  </span>
                  <span className="min-w-0 flex-1">
                    <InlineText text={s.title} />
                    {s.optional ? <span className={`${TERRA_PILL} ms-2`}>הרחבה לבחירה</span> : null}
                    {here ? <span className="sr-only"> (השלב הנוכחי)</span> : null}
                  </span>
                  <span className={`shrink-0 text-[12px] ${status[s.key]?.completed ? 'text-ok' : 'text-ink-3'}`}>
                    <span aria-hidden>{w.icon}</span> {w.text}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      ) : (
        <ol id="lesson-map-list" className="mt-2 flex flex-wrap gap-1">
          {steps.map((s) => {
            const w = statusWords(status[s.key]);
            const here = s.key === current;
            return (
              <li key={s.key}>
                <button
                  type="button"
                  aria-current={here ? 'step' : undefined}
                  aria-label={`שלב ${s.letter}: ${plainInline(s.title)} – ${w.text}${s.optional ? ' (הרחבה לבחירה)' : ''}`}
                  title={`${plainInline(s.title)} – ${w.text}`}
                  onClick={() => onPick(s.key)}
                  className={`flex h-10 min-w-[36px] items-center justify-center gap-0.5 rounded-md px-1 text-[14px] font-semibold ${
                    here
                      ? 'bg-forest text-paper'
                      : s.optional
                        ? 'border border-dashed border-terracotta bg-card text-[#9a5533]'
                        : 'border border-border bg-paper text-ink'
                  }`}
                >
                  {s.letter}
                  <span aria-hidden className="text-[11px] font-normal">
                    {status[s.key]?.completed ? '✓' : status[s.key]?.viewed ? '·' : ''}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </nav>
  );
}

function ruleLabel(rule: CompletionRule, step: LessonStep, api: LessonApi): React.ReactNode {
  switch (rule.type) {
    case 'answered': {
      const q = api.content.questions[rule.question];
      // Clamped, not cut: a formula like `<= 5` keeps its LTR isolation.
      return (
        <span className="line-clamp-3">
          לענות על השאלה: {q ? <>״<InlineText text={q.prompt} />״</> : rule.question}
        </span>
      );
    }
    case 'ack': {
      const ack = findAck(step.blocks, rule.key);
      return <>לסמן: {ack ? <InlineText text={ack.label} /> : rule.key}</>;
    }
    case 'experiments': {
      const have = api.experiments.filter((e) => e.complete).length;
      return (
        <>
          לתעד ביומן לפחות {rule.min_complete} ריצות מלאות (יש עכשיו {have})
        </>
      );
    }
    case 'commitment':
      return <>לשמור בחירת הגדרות ונימוק – לפני שפותחים את המבחן הסופי</>;
    default:
      return null;
  }
}

function StepChecklist({ step, status, api }: { step: LessonStep; status: StepStatus | undefined; api: LessonApi }) {
  if (!step.completion.length) return null;
  return (
    <section aria-labelledby={`checklist-${step.key}`} className="rounded-lg border border-border bg-card p-4 shadow-soft">
      <h3 id={`checklist-${step.key}`} className="font-hebrew text-[18px]">
        מה נדרש כדי להשלים את השלב
      </h3>
      <ul className="mt-2 grid grid-cols-1 gap-2">
        {step.completion.map((rule, i) => {
          // The same rule the server applies, on what the server has acknowledged.
          const done = ruleDone(rule, api);
          return (
            <li key={i} className="flex items-start gap-2 text-[14px] leading-relaxed">
              <span aria-hidden className={`mt-0.5 shrink-0 ${done ? 'text-ok' : 'text-ink-3'}`}>
                {done ? '✓' : '○'}
              </span>
              <span className="min-w-0 flex-1">{ruleLabel(rule, step, api)}</span>
              <span className={`shrink-0 text-[12px] font-semibold ${done ? 'text-ok' : 'text-ink-3'}`}>
                {done ? 'בוצע' : 'עוד לא'}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-[13px] text-ink-2">
        {status?.completed
          ? '✓ השלב הושלם.'
          : 'אפשר להמשיך לשלב הבא גם לפני שהכול מסומן – תמיד אפשר לחזור.'}{' '}
        <span className="text-ink-2">השלמה פירושה שעשיתם את הפעולות; היא לא ציון ולא הוכחה להבנה.</span>
      </p>
    </section>
  );
}
