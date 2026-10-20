'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { BlockList } from '@/components/lessons/blocks';
import { ruleDone } from '@/components/lessons/completion';
import { InlineText, Ltr, plainInline } from '@/components/lessons/inline';
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
 * localStorage (cg-lesson-draft:<token>:<slug>) until the server acknowledges
 * them, so they survive a reload, a lost network or a sign-in redirect. A 409
 * stale answer is rebased: the server's state is taken and the unsent local
 * changes are re-applied on top, then sent once more automatically. "Saved" is
 * shown only after the server answered. The preview never touches storage. */

type BlockedCode = 'not_signed_in' | 'wrong_account' | 'withdrawn';
const BLOCKING: string[] = ['not_signed_in', 'wrong_account', 'withdrawn'];

type SaveState = { kind: 'idle' } | { kind: 'saving' } | { kind: 'saved' } | { kind: 'error'; message: string };

export type DraftStatus = 'saving' | 'saved' | 'error' | null;

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

function readMirror(key: string): Pending | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw)?.pending;
    if (!parsed || typeof parsed !== 'object') return null;
    const strings = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);
    const record = <T,>(v: unknown, ok: (x: unknown) => x is T): Record<string, T> =>
      v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).filter(([, x]) => ok(x))) : {};
    return {
      step: typeof parsed.step === 'string' ? parsed.step : undefined,
      viewed: strings(parsed.viewed),
      acks: record(parsed.acks, (x): x is boolean => typeof x === 'boolean'),
      drafts: record(parsed.drafts, (x): x is string | null => typeof x === 'string' || x === null)
    };
  } catch {
    return null;
  }
}

function writeMirror(key: string, unsent: Pending | null) {
  try {
    if (unsent && !isEmpty(unsent)) localStorage.setItem(key, JSON.stringify({ v: 1, pending: unsent }));
    else localStorage.removeItem(key);
  } catch {
    /* storage unavailable — saving still works, just without the safety net */
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
    if (this.hooks.storageKey) writeMirror(this.hooks.storageKey, this.unsent());
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
      this.firstUnsentAt = null;
      this.persist();
      if (this.state.kind === 'saving') this.setState({ kind: 'saved' });
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

function shorten(text: string, max = 90) {
  const t = text.replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

function loginHref() {
  const next = `${window.location.pathname}${window.location.hash}`;
  return `/login?next=${encodeURIComponent(next)}`;
}

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

  useEffect(() => {
    let cancelled = false;
    const be = backendRef.current;
    const tk = tokenRef.current;
    setLoadError(null);
    be.load()
      .then((data) => {
        if (cancelled) return;
        const storageKey = be.mode !== 'preview' && tk ? `cg-lesson-draft:${tk}:${data.lesson.slug}` : null;
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
        const stored = storageKey ? readMirror(storageKey) : null;
        if (stored) saver.restore(stored);

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
    <Card tone="warn">
      <h2 className="font-hebrew text-[20px]">צריך להתחבר</h2>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
        כדי לראות את השיעור ולשמור את ההתקדמות צריך להיות מחוברים לחשבון שלך. מה שכבר כתבת ולא נשמר נשאר במכשיר הזה, ויישלח
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
    <Card tone="warn">
      <h2 className="font-hebrew text-[20px]">הקישור שייך לחשבון אחר</h2>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
        נראה שהמכשיר הזה מחובר לחשבון של סטודנט/ית אחר/ת מזה שהקישור הזה שייך לו. הקישור לשיעור אישי, והתשובות נשמרות לבעל/ת
        הקישור בלבד. אם זה הקישור שלך – התנתקו והיכנסו עם החשבון שלך. אם לא – פתחו את הקישור האישי שלכם מעמוד הכניסה.
      </p>
      <button
        type="button"
        onClick={async () => {
          try {
            await fetch('/api/student-auth/logout', { method: 'POST', credentials: 'same-origin' });
          } finally {
            window.location.assign(loginHref());
          }
        }}
        className="mt-3 inline-flex h-11 items-center rounded-md border border-forest px-5 text-[15px] font-semibold text-forest"
      >
        התנתקות וכניסה מחדש
      </button>
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
      if (r.completed_at) setCompletedAt(r.completed_at);
    },
    experiments: (r: ExperimentsResult) => {
      setExperiments(r.experiments);
      setSteps(r.steps);
      if (r.completed_at) setCompletedAt(r.completed_at);
    },
    commitments: (r: CommitmentsResult) => {
      setCommitments(r.commitments);
      setSteps(r.steps);
      if (r.completed_at) setCompletedAt(r.completed_at);
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
    goToStep
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
      />
      <main className="mx-auto w-full max-w-[640px] px-4 pb-24 pt-4">
        <header className="pb-2">
          {token ? (
            <nav aria-label="קישורים" className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[14px]">
              <a href={`/r/${token}`} className="text-forest hover:underline">
                → לעמוד הקורס
              </a>
              <a href={`/r/${token}/lessons`} className="text-forest hover:underline">
                כל השיעורים
              </a>
            </nav>
          ) : null}
          <div className="text-[12px] tracking-wide text-ink-3">
            {payload.course.name}
            {payload.course.code ? (
              <>
                {' '}
                · <Ltr>{payload.course.code}</Ltr>
              </>
            ) : null}
          </div>
          <h1 className="font-hebrew text-[26px] leading-tight">{content.title}</h1>
          <p className="mt-1 text-[15px] text-ink-2">
            <InlineText text={content.guiding_question} />
          </p>
          {completedAt ? (
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
            <div className="text-[13px] text-ink-3">
              {step.optional ? (
                <span className="pill pill-terra">הרחבה לבחירה</span>
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

function Card({ tone, children }: { tone: 'warn' | 'bad'; children: React.ReactNode }) {
  return (
    <section className={`mt-3 rounded-lg border bg-card p-5 shadow-card ${tone === 'bad' ? 'border-bad-soft' : 'border-warn-soft'}`}>
      {children}
    </section>
  );
}

function StatusBar({
  preview,
  step,
  state,
  blocked,
  onRetry
}: {
  preview: boolean;
  step: LessonStep;
  state: SaveState;
  blocked: BlockedCode | null;
  onRetry: () => void;
}) {
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
            <span className="font-semibold text-terracotta">תצוגה מקדימה – שום דבר לא נשמר</span>
          ) : state.kind === 'saving' ? (
            <span className="text-ink-2">שומר…</span>
          ) : state.kind === 'saved' ? (
            <span className="text-ok">✓ נשמר</span>
          ) : state.kind === 'error' ? (
            <>
              <span className="font-semibold text-bad" title={state.message}>
                ⚠ לא נשמר – נסו שוב
              </span>
              {blocked !== 'not_signed_in' && blocked !== 'wrong_account' && blocked !== 'withdrawn' ? (
                <button type="button" onClick={onRetry} className="rounded border border-bad px-2 py-0.5 text-bad">
                  ניסיון חוזר
                </button>
              ) : null}
            </>
          ) : (
            <span className="text-ink-3">שמירה אוטומטית</span>
          )}
        </span>
      </div>
      {!preview && state.kind === 'error' ? (
        <p className="mx-auto w-full max-w-[640px] px-4 pb-1.5 text-[12px] text-ink-2">{state.message}</p>
      ) : null}
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
          className="shrink-0 rounded px-1 text-[13px] text-forest underline"
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
                      s.optional ? 'border border-dashed border-terracotta text-terracotta' : 'bg-paper-2 text-ink'
                    }`}
                  >
                    {s.letter}
                  </span>
                  <span className="min-w-0 flex-1">
                    <InlineText text={s.title} />
                    {s.optional ? <span className="pill pill-terra ms-2">הרחבה לבחירה</span> : null}
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
                        ? 'border border-dashed border-terracotta bg-card text-terracotta'
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
      return <>לענות על השאלה: {q ? `״${shorten(plainInline(q.prompt))}״` : rule.question}</>;
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
              <span aria-hidden className={`mt-0.5 shrink-0 ${done ? 'text-ok' : 'text-ink-4'}`}>
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
        <span className="text-ink-3">השלמה פירושה שעשיתם את הפעולות; היא לא ציון ולא הוכחה להבנה.</span>
      </p>
    </section>
  );
}
