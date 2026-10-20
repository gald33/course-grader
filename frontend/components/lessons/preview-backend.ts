/* The player's backend for the instructor preview. The lesson comes from the
 * instructor preview endpoint (any version, answer keys stripped exactly as
 * for students); answers get their feedback from /preview/evaluate, which
 * applies the student feedback rules and stores nothing. Progress, attempts,
 * experiments and commitments live only in this object's memory, validated
 * like the student API so the preview shows the same messages: nothing is
 * written anywhere, no student endpoint is called, and a reload starts the
 * preview over. */

import { computeSteps, experimentComplete, requiredProgress } from '@/components/lessons/completion';
import {
  LessonApiError,
  type Answer,
  type AttemptInput,
  type AttemptResult,
  type Block,
  type Commitment,
  type CommitmentInput,
  type CommitmentsResult,
  type DepthKind,
  type Experiment,
  type ExperimentInput,
  type ExperimentsResult,
  type Feedback,
  type FinalInput,
  type LessonBackend,
  type LessonContent,
  type LessonPayload,
  type Progress,
  type ProgressPatch,
  type ProgressResult,
  type Question,
  type QuestionState,
  type StepStatus
} from '@/components/lessons/types';
import { apiFetch } from '@/lib/api';

// Same limits as backend/app/services/lessons.py and app/lessons/schema.py.
// (Answers are checked by /preview/evaluate itself.)
const MAX_EXPERIMENTS = 30;
const MAX_TEXT = 5000;
const MIN_JUSTIFICATION = 10;
const MAX_DEPTH = 50;
const MIN_TRAINING_EXAMPLES = 20;
const MAX_TRAINING_EXAMPLES = 720;
const MAX_DRAFT_KEYS = 200;
const MAX_DRAFT_KEY_CHARS = 100;
const MAX_DRAFT_CHARS = 20000;
const MAX_DRAFTS_BYTES = 200 * 1024;
const REQUEST_ID = /^[A-Za-z0-9_-]{8,64}$/;
const RUN_UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

// The student API's messages (MSG in the lesson service), so the preview reads the same.
const MSG = {
  network: 'אין חיבור לשרת. נסו שוב.',
  error: 'משהו השתבש. נסו שוב.',
  invalid_values: 'חלק מהערכים אינם תקינים — תקנו את השדות המסומנים',
  stale: 'הנתונים עודכנו בלשונית או במכשיר אחר',
  experiment_gone: 'הריצה הזו נמחקה בלשונית או במכשיר אחר',
  question_not_found: 'השאלה לא נמצאה בשיעור',
  request_id: 'מזהה בקשה לא תקין',
  request_reused: 'מזהה הבקשה כבר שימש לפעולה אחרת',
  step: 'שלב לא מוכר בשיעור',
  ack: 'סימון לא מוכר בשיעור',
  draft_key: 'שם טיוטה לא תקין',
  draft_long: 'הטיוטה ארוכה מדי (עד 20,000 תווים)',
  drafts_many: 'יותר מדי טיוטות שמורות',
  drafts_big: 'הטיוטות השמורות גדולות מדי',
  too_long: 'הטקסט ארוך מדי (עד 5,000 תווים)',
  run_uuid: 'מזהה ריצה לא תקין',
  run_unknown: 'הריצה שנבחרה לא נמצאה ביומן הניסויים שלכם',
  depth_kind: 'בחרו עומק מהרשימה',
  depth_kind_required: 'בחרו עומק',
  depth_without_kind: 'בחרו קודם את סוג העומק',
  depth_required: `הזינו עומק (מספר שלם בין 1 ל-${MAX_DEPTH})`,
  depth: `העומק חייב להיות מספר שלם בין 1 ל-${MAX_DEPTH}`,
  depth_zero: 'בקולאב 0 פירושו עומק ללא הגבלה — בחרו "ללא הגבלה" במקום 0',
  depth_unlimited: 'בעומק ללא הגבלה לא מזינים מספר',
  training_examples: `מספר דוגמאות האימון חייב להיות מספר שלם בין ${MIN_TRAINING_EXAMPLES} ל-${MAX_TRAINING_EXAMPLES}`,
  training_examples_required: `הזינו את מספר דוגמאות האימון (${MIN_TRAINING_EXAMPLES}–${MAX_TRAINING_EXAMPLES})`,
  pct: 'הזינו אחוז בין 0 ל-100',
  pct_required: 'הזינו את הדיוק באחוזים (0–100)',
  empty_run: 'כתבו לפחות השערה או הגדרות ריצה לפני השמירה',
  too_many_experiments: `אפשר לשמור עד ${MAX_EXPERIMENTS} ריצות בשיעור`,
  experiment_not_found: 'הריצה לא נמצאה',
  justification: `כתבו נימוק של ${MIN_JUSTIFICATION} תווים לפחות`,
  commitment_not_found: 'הבחירה לא נמצאה',
  final_already_recorded: 'תוצאת המבחן הסופי כבר נשמרה לבחירה הזו'
};

type Fields = Record<string, string>;
type StoredExperiment = Experiment & { deleted_at: string | null };
type Evaluated = { feedback: Feedback; correct: boolean | null };
type RequestKind = 'answer' | 'reveal' | 'commit';

function fail(code: string, message: string, status: number, extra: Record<string, unknown> = {}): LessonApiError {
  return new LessonApiError(code, message, status, { code, message, ...extra });
}

function invalid(fields: Fields): LessonApiError {
  return fail('invalid_values', MSG.invalid_values, 422, { fields });
}

/** Plain data in, an independent copy out: callers never hold our state. */
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function now(): string {
  return new Date().toISOString();
}

/** A JSON number as the API would receive it (NaN and Infinity travel as null). */
function num(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function whole(value: number): boolean {
  return Number.isInteger(value);
}

function ackKeys(content: LessonContent): string[] {
  const keys: string[] = [];
  const walk = (blocks: Block[]) => {
    for (const block of blocks) {
      if (block.type === 'ack' && !keys.includes(block.key)) keys.push(block.key);
      if (block.type === 'section' || block.type === 'expander') walk(block.blocks);
    }
  };
  for (const step of content.steps) walk(step.blocks);
  return keys;
}

function emptyQuestion(): QuestionState {
  return { attempts: 0, revealed: false, first: null, latest: null, feedback: null };
}

/** The answer as the server stores it: trimmed; an explanation only where the question asks for one. */
function cleanAnswer(question: Question, answer: Answer): Answer {
  const text = (answer.text ?? '').trim();
  if (question.type === 'single_choice') {
    const clean: Answer = { choice: answer.choice };
    if (text && (question.explain ?? 'none') !== 'none') clean.text = text;
    return clean;
  }
  return { text };
}

function checkRequestId(requestId: string) {
  if (!REQUEST_ID.test(requestId ?? '')) throw invalid({ request_id: MSG.request_id });
}

function cleanRunUuid(value: string | null | undefined, fields: Fields, name = 'run_uuid'): string | null {
  if (value == null || !RUN_UUID.test(value)) {
    fields[name] = MSG.run_uuid;
    return null;
  }
  return value.toLowerCase();
}

/** depth_kind / depth / training_examples, checked together: a limited depth
 * is 1..50, unlimited has no number (Colab's 0), examples 20..720. */
function cleanSettings(
  fields: Fields,
  depthKind: DepthKind | null | undefined,
  rawDepth: number | null | undefined,
  rawExamples: number | null | undefined,
  required: boolean
): { kind: DepthKind | null; depth: number | null; examples: number | null } {
  const depth = num(rawDepth);
  const examples = num(rawExamples);
  let kind: DepthKind | null = null;
  let cleanDepth: number | null = null;
  let cleanExamples: number | null = null;
  if (depthKind == null) {
    if (required) fields.depth_kind = MSG.depth_kind_required;
    else if (depth != null) fields.depth = MSG.depth_without_kind;
  } else if (depthKind !== 'limited' && depthKind !== 'unlimited') {
    fields.depth_kind = MSG.depth_kind;
  } else if (depthKind === 'limited') {
    if (depth == null) fields.depth = MSG.depth_required;
    else if (depth === 0) fields.depth = MSG.depth_zero;
    else if (!whole(depth) || depth < 1 || depth > MAX_DEPTH) fields.depth = MSG.depth;
    else {
      kind = 'limited';
      cleanDepth = depth;
    }
  } else if (depth != null) {
    fields.depth = MSG.depth_unlimited;
  } else {
    kind = 'unlimited';
  }
  if (examples == null) {
    if (required) fields.training_examples = MSG.training_examples_required;
  } else if (!whole(examples) || examples < MIN_TRAINING_EXAMPLES || examples > MAX_TRAINING_EXAMPLES) {
    fields.training_examples = MSG.training_examples;
  } else {
    cleanExamples = examples;
  }
  return { kind, depth: cleanDepth, examples: cleanExamples };
}

/** A percentage 0..100 from the UI, kept once as a fraction 0..1. */
function fraction(fields: Fields, name: string, raw: number | null | undefined, required = false): number | null {
  const pct = num(raw);
  if (pct == null) {
    if (required) fields[name] = MSG.pct_required;
    return null;
  }
  if (pct < 0 || pct > 100) {
    fields[name] = MSG.pct;
    return null;
  }
  return Math.round((pct / 100) * 1e6) / 1e6;
}

function cleanText(fields: Fields, name: string, value: string | null | undefined, minChars = 0, short = ''): string {
  const text = (value ?? '').trim();
  if (text.length > MAX_TEXT) fields[name] = MSG.too_long;
  else if (text.length < minChars) fields[name] = short;
  return text;
}

/** fetch() an instructor preview endpoint; failures become LessonApiError like the student adapter's. */
async function call<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await apiFetch(
      path,
      body === undefined
        ? { cache: 'no-store' }
        : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    );
  } catch {
    throw fail('network', MSG.network, 0);
  }
  if (!res.ok) {
    let code = res.status >= 500 ? 'network' : 'error';
    let message = res.status >= 500 ? MSG.network : MSG.error;
    let detail: Record<string, unknown> = {};
    try {
      const parsed = await res.json();
      if (typeof parsed?.detail === 'string') message = parsed.detail;
      else if (parsed?.detail && typeof parsed.detail === 'object' && !Array.isArray(parsed.detail)) {
        detail = parsed.detail as Record<string, unknown>;
        if (typeof detail.code === 'string') code = detail.code;
        if (typeof detail.message === 'string') message = detail.message;
      }
    } catch {
      /* not JSON */
    }
    throw new LessonApiError(code, message, res.status, detail);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw fail('network', MSG.network, res.status);
  }
}

/** versionId: the version to preview (null: the lesson's latest version). */
export function previewLessonBackend(courseId: number, lessonId: number, versionId: number | null): LessonBackend {
  const base = `/api/courses/${courseId}/lessons/${lessonId}`;

  let loaded: LessonPayload | null = null;
  let loading: Promise<LessonPayload> | null = null;
  let progress: Progress | null = null;
  let questions: Record<string, QuestionState> = {};
  let experiments: StoredExperiment[] = []; // soft-deleted ones included, like the database
  let commitments: Commitment[] = [];
  let nextCommitmentId = 1;
  // request_id → what it was used for (attempts, reveals, commitments are idempotent).
  const requests = new Map<string, { kind: RequestKind; questionKey: string | null }>();
  const inFlight = new Map<string, { kind: RequestKind; questionKey: string | null; result: Promise<unknown> }>();

  async function ready(): Promise<LessonPayload> {
    if (loaded) return loaded;
    if (!loading) {
      const query = versionId != null ? `?version_id=${encodeURIComponent(versionId)}` : '';
      loading = call<LessonPayload>(`${base}/preview${query}`)
        .then((payload) => {
          loaded = payload;
          return payload;
        })
        .finally(() => {
          loading = null;
        });
    }
    return loading;
  }

  const content = () => (loaded as LessonPayload).content;
  const live = () => experiments.filter((e) => !e.deleted_at);
  const questionState = (key: string) => questions[key] ?? emptyQuestion();

  function steps(): Record<string, StepStatus> {
    return computeSteps(content(), { progress, questions, experiments: live(), commitments });
  }

  /** Step statuses after a write; marks the run-through completed (once) when every required step is. */
  function stepsAfterWrite(): Record<string, StepStatus> {
    const current = steps();
    const { done, total } = requiredProgress(content(), current);
    if (progress && progress.completed_at == null && done === total) progress.completed_at = now();
    return current;
  }

  /** Like the server's ensure_progress: any first save starts the run-through (revision 0). */
  function ensureProgress() {
    if (progress) return;
    const at = now();
    progress = {
      revision: 0,
      current_step_key: null,
      viewed: [],
      acks: [],
      drafts: {},
      started_at: at,
      updated_at: at,
      completed_at: null
    };
  }

  function experimentView({ deleted_at: _deleted, ...e }: StoredExperiment): Experiment {
    return clone(e);
  }

  function attemptResult(questionKey: string): AttemptResult {
    const current = stepsAfterWrite();
    return {
      question_key: questionKey,
      question: clone(questionState(questionKey)),
      steps: current,
      completed_at: progress?.completed_at ?? null
    };
  }

  function experimentsResult(): ExperimentsResult {
    const current = stepsAfterWrite();
    return { experiments: live().map(experimentView), steps: current, completed_at: progress?.completed_at ?? null };
  }

  function commitmentsResult(): CommitmentsResult {
    const current = stepsAfterWrite();
    return { commitments: clone(commitments), steps: current, completed_at: progress?.completed_at ?? null };
  }

  /** Runs a request once per request_id: a retry gets the current result, never a second record. */
  async function once<T>(
    requestId: string,
    kind: RequestKind,
    questionKey: string | null,
    replay: () => T,
    run: () => Promise<T>
  ): Promise<T> {
    checkRequestId(requestId);
    const used = requests.get(requestId) ?? inFlight.get(requestId);
    if (used && (used.kind !== kind || used.questionKey !== questionKey)) {
      throw fail('request_reused', MSG.request_reused, 409);
    }
    if (requests.has(requestId)) return replay();
    const pending = inFlight.get(requestId);
    if (pending) return pending.result as Promise<T>;
    const result = run().then((value) => {
      requests.set(requestId, { kind, questionKey });
      return value;
    });
    inFlight.set(requestId, { kind, questionKey, result });
    try {
      return await result;
    } finally {
      inFlight.delete(requestId);
    }
  }

  function question(key: string): Question {
    const q = content().questions[key];
    if (!q) throw fail('question_not_found', MSG.question_not_found, 404);
    return q;
  }

  function evaluate(questionKey: string, answer: Answer | null, reveal: boolean, priorAnswers: number) {
    return call<Evaluated>(`${base}/preview/evaluate`, {
      version_id: (loaded as LessonPayload).version.id,
      question_key: questionKey,
      answer,
      reveal,
      prior_answers: priorAnswers
    });
  }

  function staleExperiment(runUuid: string): LessonApiError {
    const row = experiments.find((e) => e.run_uuid === runUuid);
    if (!row || row.deleted_at) return fail('stale', row ? MSG.experiment_gone : MSG.stale, 409, { current: null });
    return fail('stale', MSG.stale, 409, { current: experimentView(row) });
  }

  return {
    mode: 'preview',

    async load(): Promise<LessonPayload> {
      const payload = await ready();
      const all: Record<string, QuestionState> = {};
      for (const key of Object.keys(payload.content.questions)) all[key] = clone(questionState(key));
      return {
        ...clone(payload),
        mode: 'preview',
        progress: clone(progress),
        steps: steps(),
        questions: all,
        experiments: live().map(experimentView),
        commitments: clone(commitments)
      };
    },

    async patchProgress(body: ProgressPatch): Promise<ProgressResult> {
      const lesson = (await ready()).content;
      if (body.expected_revision !== (progress?.revision ?? 0)) {
        throw fail('stale', MSG.stale, 409, { current: clone(progress), steps: steps() });
      }
      const stepOrder = lesson.steps.map((s) => s.key);
      const ackOrder = ackKeys(lesson);
      const viewedAdd = body.viewed_add ?? [];
      const acksAdd = body.acks_add ?? [];
      const acksRemove = body.acks_remove ?? [];
      const fields: Fields = {};
      if (body.current_step_key != null && !stepOrder.includes(body.current_step_key)) fields.current_step_key = MSG.step;
      if (viewedAdd.some((k) => !stepOrder.includes(k))) fields.viewed_add = MSG.step;
      if (acksAdd.some((k) => !ackOrder.includes(k))) fields.acks_add = MSG.ack;
      if (acksRemove.some((k) => !ackOrder.includes(k))) fields.acks_remove = MSG.ack;
      const drafts: Record<string, string> = { ...(progress?.drafts ?? {}) };
      for (const [key, value] of Object.entries(body.drafts ?? {})) {
        if (!key.trim() || key.length > MAX_DRAFT_KEY_CHARS) fields.drafts = MSG.draft_key;
        else if (value == null) delete drafts[key];
        else if (value.length > MAX_DRAFT_CHARS) fields[`drafts.${key}`] = MSG.draft_long;
        else drafts[key] = value;
      }
      if (!fields.drafts) {
        if (Object.keys(drafts).length > MAX_DRAFT_KEYS) fields.drafts = MSG.drafts_many;
        else if (new TextEncoder().encode(JSON.stringify(drafts)).length > MAX_DRAFTS_BYTES) fields.drafts = MSG.drafts_big;
      }
      if (Object.keys(fields).length) throw invalid(fields);

      const viewed = new Set([...(progress?.viewed ?? []), ...viewedAdd]);
      const acks = new Set([...(progress?.acks ?? []), ...acksAdd]);
      for (const key of acksRemove) acks.delete(key);
      const at = now();
      progress = {
        revision: body.expected_revision + 1,
        current_step_key: body.current_step_key || progress?.current_step_key || null,
        viewed: stepOrder.filter((k) => viewed.has(k)),
        acks: ackOrder.filter((k) => acks.has(k)),
        drafts,
        started_at: progress?.started_at ?? at,
        updated_at: at,
        completed_at: progress?.completed_at ?? null
      };
      const current = stepsAfterWrite();
      return { progress: clone(progress), steps: current };
    },

    async submitAttempt(body: AttemptInput): Promise<AttemptResult> {
      await ready();
      return once(
        body.request_id,
        'answer',
        body.question_key,
        () => attemptResult(body.question_key),
        async () => {
          const q = question(body.question_key);
          const before = questionState(q.key);
          // The server checks the answer (422 with the same field messages) and computes the feedback.
          const res = await evaluate(q.key, body.answer, false, before.attempts);
          ensureProgress();
          const at = now();
          const answer = cleanAnswer(q, body.answer);
          const number = before.attempts + 1;
          const state = questionState(q.key);
          questions = {
            ...questions,
            [q.key]: {
              attempts: number,
              revealed: state.revealed,
              first: state.first ?? { answer, correct: res.correct, submitted_at: at },
              latest: { answer, correct: res.correct, submitted_at: at, attempt_number: number },
              feedback: res.feedback
            }
          };
          return attemptResult(q.key);
        }
      );
    },

    async reveal(questionKey: string, requestId: string): Promise<AttemptResult> {
      await ready();
      return once(
        requestId,
        'reveal',
        questionKey,
        () => attemptResult(questionKey),
        async () => {
          const q = question(questionKey);
          const before = questionState(q.key);
          // Check-mode questions answer 409 answer_first before a first answer, as for students.
          const res = await evaluate(q.key, before.latest?.answer ?? null, true, before.attempts);
          ensureProgress();
          questions = { ...questions, [q.key]: { ...questionState(q.key), revealed: true, feedback: res.feedback } };
          return attemptResult(q.key);
        }
      );
    },

    async saveExperiment(runUuid: string, body: ExperimentInput): Promise<ExperimentsResult> {
      await ready();
      const fields: Fields = {};
      const run = cleanRunUuid(runUuid, fields);
      const settings = cleanSettings(fields, body.depth_kind, body.depth, body.training_examples, false);
      const values = {
        depth_kind: settings.kind,
        depth: settings.depth,
        training_examples: settings.examples,
        train_accuracy: fraction(fields, 'train_accuracy_pct', body.train_accuracy_pct),
        validation_accuracy: fraction(fields, 'validation_accuracy_pct', body.validation_accuracy_pct),
        baseline_validation: fraction(fields, 'baseline_validation_pct', body.baseline_validation_pct),
        hypothesis: cleanText(fields, 'hypothesis', body.hypothesis),
        observation: cleanText(fields, 'observation', body.observation),
        explanation: cleanText(fields, 'explanation', body.explanation)
      };
      if (!Object.keys(fields).length && Object.values(values).every((v) => v == null || v === '')) {
        fields.hypothesis = MSG.empty_run;
      }
      if (Object.keys(fields).length || run == null) throw invalid(fields);

      const row = experiments.find((e) => e.run_uuid === run);
      const at = now();
      if (!row) {
        if (body.expected_revision != null) throw staleExperiment(run);
        if (live().length >= MAX_EXPERIMENTS) throw fail('too_many_experiments', MSG.too_many_experiments, 409);
        ensureProgress();
        const created: StoredExperiment = {
          run_uuid: run,
          revision: 1,
          ...values,
          provenance: 'student_entered',
          complete: false,
          created_at: at,
          updated_at: at,
          deleted_at: null
        };
        created.complete = experimentComplete(created);
        experiments = [...experiments, created];
      } else {
        if (row.deleted_at || body.expected_revision !== row.revision) throw staleExperiment(run);
        const updated: StoredExperiment = { ...row, ...values, revision: row.revision + 1, updated_at: at };
        updated.complete = experimentComplete(updated);
        experiments = experiments.map((e) => (e.run_uuid === run ? updated : e));
      }
      return experimentsResult();
    },

    async deleteExperiment(runUuid: string, expectedRevision: number): Promise<ExperimentsResult> {
      await ready();
      const fields: Fields = {};
      const run = cleanRunUuid(runUuid, fields);
      if (run == null) throw invalid(fields);
      const row = experiments.find((e) => e.run_uuid === run);
      if (!row) throw fail('experiment_not_found', MSG.experiment_not_found, 404);
      if (!row.deleted_at) {
        // Soft delete, as for students: gone from the log, kept with deleted_at.
        if (expectedRevision !== row.revision) throw staleExperiment(run);
        experiments = experiments.map((e) => (e.run_uuid === run ? { ...e, deleted_at: now() } : e));
      }
      return experimentsResult();
    },

    async commit(body: CommitmentInput): Promise<CommitmentsResult> {
      await ready();
      return once(body.request_id, 'commit', null, commitmentsResult, async () => {
        const fields: Fields = {};
        const settings = cleanSettings(fields, body.depth_kind, body.depth, body.training_examples, true);
        let run: string | null = null;
        if (body.run_uuid) {
          run = cleanRunUuid(body.run_uuid, fields);
          if (run && !live().some((e) => e.run_uuid === run)) fields.run_uuid = MSG.run_unknown;
        }
        const justification = cleanText(fields, 'justification', body.justification, MIN_JUSTIFICATION, MSG.justification);
        if (Object.keys(fields).length || settings.kind == null || settings.examples == null) throw invalid(fields);
        ensureProgress();
        commitments = [
          ...commitments,
          {
            id: nextCommitmentId++,
            run_uuid: run,
            depth_kind: settings.kind,
            depth: settings.depth,
            training_examples: settings.examples,
            justification,
            committed_at: now(),
            // A choice made after a final-test result was recorded is flagged, never rewritten.
            after_final_seen: commitments.some((c) => c.final != null),
            final: null
          }
        ];
        return commitmentsResult();
      });
    },

    async recordFinal(commitmentId: number, body: FinalInput): Promise<CommitmentsResult> {
      await ready();
      const row = commitments.find((c) => c.id === commitmentId);
      if (!row) throw fail('commitment_not_found', MSG.commitment_not_found, 404);
      if (row.final) throw fail('final_already_recorded', MSG.final_already_recorded, 409);
      const fields: Fields = {};
      const accuracy = fraction(fields, 'final_accuracy_pct', body.final_accuracy_pct, true);
      const precision = fraction(fields, 'final_precision_pct', body.final_precision_pct);
      const recall = fraction(fields, 'final_recall_pct', body.final_recall_pct);
      const note = cleanText(fields, 'final_note', body.final_note);
      if (Object.keys(fields).length || accuracy == null) throw invalid(fields);
      const final = { accuracy, precision, recall, note, recorded_at: now() };
      commitments = commitments.map((c) => (c.id === commitmentId ? { ...c, final } : c));
      return commitmentsResult();
    }
  };
}
