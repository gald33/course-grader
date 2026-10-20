/* Shared contract for guided lessons: the content schema (authored as JSON in
 * backend/app/lessons/content/, validated by backend/app/lessons/schema.py),
 * the student payload from /api/r/<token>/lessons/<slug>, and the backend
 * adapter the player talks to (student API or the instructor's no-save
 * preview). Keep in sync with the Pydantic models. */

/* ---------------- Content ---------------- */

/** Inline text. Supports **bold**, `code` (an LTR-isolated identifier,
 * formula or CSV name) and [[ltr text]] (LTR-isolated, not monospace).
 * Never HTML. */
export type Inline = string;

/** מבינים / מנסים / בודקים */
export type SectionLabel = 'understand' | 'try' | 'check';

export type TreeNode = {
  id: number;
  is_leaf: boolean;
  feature: string | null; // 'visits_30d' | 'days_since_purchase'
  threshold: number | null; // go left when value <= threshold
  left: number | null;
  right: number | null;
  prediction: 0 | 1;
  training_examples?: number;
  class_counts?: [number, number]; // [no, yes]
};

export type ManualCustomer = { id: string; label: Inline; visits_30d: number; days_since_purchase: number };

export type Block =
  | { type: 'text'; body: Inline[] }
  | { type: 'section'; label: SectionLabel; title?: Inline; blocks: Block[] }
  | { type: 'callout'; tone: 'info' | 'warn' | 'note'; title?: Inline; body: Inline[] }
  | { type: 'expander'; title: Inline; blocks: Block[] }
  | { type: 'list'; ordered?: boolean; items: Inline[] }
  | { type: 'table'; caption?: Inline; columns: { label: Inline; ltr?: boolean }[]; rows: Inline[][] }
  | { type: 'code'; caption?: Inline; code: string; highlight_lines?: number[] }
  | { type: 'download'; asset: string; label: Inline; description?: Inline }
  | { type: 'prompt'; title: Inline; text: string; note?: Inline }
  | { type: 'colab'; notebook_asset: string; section?: Inline; instructions: Inline[]; return_note: Inline }
  | { type: 'link'; target: 'peer_review' | 'lesson_list'; label: Inline; description?: Inline }
  | {
      type: 'manual_tree';
      caption?: Inline;
      feature_labels: Record<string, Inline>;
      root: number;
      nodes: TreeNode[];
      customers: ManualCustomer[];
    }
  | {
      type: 'split_illustration';
      caption?: Inline;
      feature_label: Inline;
      points: { value: number; label: 0 | 1 }[];
      candidate_thresholds: number[];
    }
  | {
      type: 'actual_tree';
      asset: string; // the exported model JSON (decision-tree-actual.json)
      caption?: Inline;
      examples: { visits_30d: number; days_since_purchase: number }[];
    }
  | { type: 'question'; question: string }
  | {
      type: 'experiment_log';
      min_complete: number;
      suggested_runs: { depth_kind: DepthKind; depth: number | null; training_examples: number; note: Inline }[];
    }
  | { type: 'commitment' }
  | { type: 'summary' }
  | { type: 'ack'; key: string; label: Inline; description?: Inline };

export type CompletionRule =
  | { type: 'answered'; question: string }
  | { type: 'ack'; key: string }
  | { type: 'experiments'; min_complete: number }
  | { type: 'commitment' };

export type LessonStep = {
  key: string;
  letter: string; // A..G, or a short marker for the optional extension
  title: Inline;
  goal: Inline; // the guiding question of the step
  optional?: boolean; // optional steps never count toward required progress
  blocks: Block[];
  completion: CompletionRule[];
  next_hint?: Inline;
};

export type ChoiceOption = { id: string; text: Inline };

type QuestionBase = {
  key: string;
  step: string; // the step key the question belongs to
  mode: 'practice' | 'check'; // practice: unlimited tries, feedback at once; check: individual first answer before feedback
  prompt: Inline;
  context?: Inline;
};

export type SingleChoiceQuestion = QuestionBase & {
  type: 'single_choice';
  options: ChoiceOption[];
  explain?: 'none' | 'optional' | 'required'; // a short written reason alongside the choice
  explain_prompt?: Inline;
};

export type FreeTextQuestion = QuestionBase & {
  type: 'free_text';
  min_chars?: number;
  placeholder?: Inline;
};

export type Question = SingleChoiceQuestion | FreeTextQuestion;

/** Answer keys: present only in the authored fixture and instructor payloads,
 * never in anything a student receives. */
export type ChoiceAnswerKey = {
  correct: string[];
  feedback: Record<string, Inline>; // per option
  misconceptions: Record<string, string>; // per wrong option: short instructor-facing tag
  explanation: Inline;
};
export type FreeTextAnswerKey = { sample_reasoning: Inline[]; rubric: Inline[] };

export type Asset = { path: string; filename: string; mime: string; label: Inline; sha256: string };

export type LessonContent = {
  schema_version: 1;
  slug: string;
  title: string;
  guiding_question: Inline;
  course_code: string;
  date?: string;
  intro?: Inline;
  assets: Record<string, Asset>;
  steps: LessonStep[];
  questions: Record<string, Question>;
};

/* ---------------- Student state (server payload) ---------------- */

export type Answer = { choice?: string; text?: string };

export type Feedback = {
  correct: boolean | null; // null for free text: recorded, not graded
  message?: Inline; // specific to the chosen option
  explanation?: Inline; // when correct, revealed, or after a check answer
  correct_options?: string[]; // only when correct, revealed, or after a check answer
  sample_reasoning?: Inline[]; // free text, after submission
  rubric?: Inline[];
};

export type QuestionState = {
  attempts: number; // submitted answers (reveals not counted)
  revealed: boolean;
  first: { answer: Answer; correct: boolean | null; submitted_at: string } | null;
  latest: { answer: Answer; correct: boolean | null; submitted_at: string; attempt_number: number } | null;
  feedback: Feedback | null;
};

export type StepStatus = { viewed: boolean; completed: boolean; done: number; total: number };

export type Progress = {
  revision: number;
  current_step_key: string | null;
  viewed: string[];
  acks: string[];
  drafts: Record<string, string>;
  started_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
};

export type DepthKind = 'limited' | 'unlimited';

export type Experiment = {
  run_uuid: string;
  revision: number;
  depth_kind: DepthKind | null;
  depth: number | null; // only when depth_kind === 'limited'
  training_examples: number | null;
  // Fractions 0..1 in the API; the UI shows and accepts percentages 0..100.
  train_accuracy: number | null;
  validation_accuracy: number | null;
  baseline_validation: number | null;
  hypothesis: string;
  observation: string;
  explanation: string;
  provenance: 'student_entered';
  complete: boolean; // settings + all three results + observation present
  created_at: string;
  updated_at: string;
};

export type Commitment = {
  id: number;
  run_uuid: string | null;
  depth_kind: DepthKind;
  depth: number | null;
  training_examples: number;
  justification: string;
  committed_at: string;
  after_final_seen: boolean; // made after a final-test result had already been recorded
  final: {
    accuracy: number;
    precision: number | null;
    recall: number | null;
    note: string;
    recorded_at: string;
  } | null;
};

export type LessonPayload = {
  mode: 'student' | 'preview';
  lesson: { id: number; slug: string; title: string; status: 'draft' | 'published' | 'archived' };
  version: { id: number; number: number; content_hash: string; published_at: string | null };
  content: LessonContent; // answer keys stripped
  colab_url: string | null;
  asset_base: string; // e.g. "/lessons/lesson-2/v1" (asset paths are relative to the site root already)
  student: { name: string } | null;
  course: { name: string; code: string };
  progress: Progress | null; // null until the first save
  steps: Record<string, StepStatus>;
  questions: Record<string, QuestionState>;
  experiments: Experiment[];
  commitments: Commitment[];
};

/* ---------------- Requests ---------------- */

export type ProgressPatch = {
  expected_revision: number; // 0 before the first save
  current_step_key?: string;
  viewed_add?: string[];
  acks_add?: string[];
  acks_remove?: string[];
  drafts?: Record<string, string | null>; // null deletes the draft
};

export type ExperimentInput = {
  expected_revision: number | null; // null to create
  depth_kind: DepthKind | null;
  depth: number | null;
  training_examples: number | null;
  train_accuracy_pct: number | null; // 0..100
  validation_accuracy_pct: number | null;
  baseline_validation_pct: number | null;
  hypothesis: string;
  observation: string;
  explanation: string;
};

export type CommitmentInput = {
  request_id: string;
  run_uuid: string | null;
  depth_kind: DepthKind;
  depth: number | null;
  training_examples: number;
  justification: string;
};

export type FinalInput = {
  final_accuracy_pct: number;
  final_precision_pct: number | null;
  final_recall_pct: number | null;
  final_note: string;
};

export type AttemptInput = { request_id: string; question_key: string; answer: Answer };

/* ---------------- Responses ---------------- */

export type ProgressResult = { progress: Progress; steps: Record<string, StepStatus> };
export type AttemptResult = {
  question_key: string;
  question: QuestionState;
  steps: Record<string, StepStatus>;
  completed_at: string | null;
};
export type ExperimentsResult = {
  experiments: Experiment[];
  steps: Record<string, StepStatus>;
  completed_at: string | null;
};
export type CommitmentsResult = {
  commitments: Commitment[];
  steps: Record<string, StepStatus>;
  completed_at: string | null;
};

/** Errors carry the API's detail.code: 'stale' (with `current`), 'invalid_values'
 * (with `fields`), 'not_signed_in', 'wrong_account', 'withdrawn', 'network', ... */
export class LessonApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public detail: Record<string, unknown> = {}
  ) {
    super(message);
  }
}

/** What the player talks to. The student adapter calls the API; the
 * instructor preview keeps everything in memory and saves nothing. */
export interface LessonBackend {
  mode: 'student' | 'preview';
  load(): Promise<LessonPayload>;
  patchProgress(body: ProgressPatch): Promise<ProgressResult>;
  submitAttempt(body: AttemptInput): Promise<AttemptResult>;
  reveal(questionKey: string, requestId: string): Promise<AttemptResult>;
  saveExperiment(runUuid: string, body: ExperimentInput): Promise<ExperimentsResult>;
  deleteExperiment(runUuid: string, expectedRevision: number): Promise<ExperimentsResult>;
  commit(body: CommitmentInput): Promise<CommitmentsResult>;
  recordFinal(commitmentId: number, body: FinalInput): Promise<CommitmentsResult>;
}
