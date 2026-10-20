/* Step completion, computed from evidence exactly as the server does it
 * (backend/app/services/lessons.py: compute_steps, experiment_complete,
 * required_progress). The server's numbers are authoritative; this copy lets
 * the instructor preview (which saves nothing) and the player show the same
 * checklist without a round trip.
 *
 * Rules: `answered` = at least one submitted answer (right or wrong; a reveal
 * is not an answer); `ack` = the self-reported key is in progress.acks;
 * `experiments` = at least min_complete non-deleted complete records;
 * `commitment` = at least one saved commitment. A step is completed when it
 * has rules and all of them are done. Viewing a step only ever makes it
 * "viewed". Optional steps never count toward the required totals. */

import type {
  CompletionRule,
  Experiment,
  LessonContent,
  Progress,
  QuestionState,
  StepStatus
} from '@/components/lessons/types';

/** The evidence completion is computed from. A LessonPayload fits as is. */
export type CompletionState = {
  progress: Pick<Progress, 'viewed' | 'acks'> | null;
  questions: Record<string, Pick<QuestionState, 'attempts'> | undefined>;
  // Instructor views include soft-deleted records (with deleted_at); they never count.
  experiments: readonly { complete: boolean; deleted_at?: string | null }[];
  commitments: readonly unknown[];
};

type ExperimentValues = Pick<
  Experiment,
  'depth_kind' | 'depth' | 'training_examples' | 'train_accuracy' | 'validation_accuracy' | 'baseline_validation' | 'observation'
>;

/** Settings, all three results and an observation are recorded. */
export function experimentComplete(e: ExperimentValues): boolean {
  const settings = e.depth_kind === 'unlimited' || (e.depth_kind === 'limited' && e.depth != null);
  return (
    settings &&
    e.training_examples != null &&
    e.train_accuracy != null &&
    e.validation_accuracy != null &&
    e.baseline_validation != null &&
    e.observation.trim() !== ''
  );
}

function completeExperiments(state: CompletionState): number {
  return state.experiments.filter((e) => !e.deleted_at && e.complete).length;
}

export function ruleDone(rule: CompletionRule, state: CompletionState): boolean {
  switch (rule.type) {
    case 'answered':
      return (state.questions[rule.question]?.attempts ?? 0) > 0;
    case 'ack':
      return state.progress?.acks.includes(rule.key) ?? false;
    case 'experiments':
      return completeExperiments(state) >= rule.min_complete;
    case 'commitment':
      return state.commitments.length > 0;
    default:
      return false;
  }
}

export function computeSteps(content: Pick<LessonContent, 'steps'>, state: CompletionState): Record<string, StepStatus> {
  const viewed = new Set(state.progress?.viewed ?? []);
  const steps: Record<string, StepStatus> = {};
  for (const step of content.steps) {
    const rules = step.completion;
    const done = rules.filter((rule) => ruleDone(rule, state)).length;
    steps[step.key] = {
      viewed: viewed.has(step.key),
      completed: rules.length > 0 && done === rules.length,
      done,
      total: rules.length
    };
  }
  return steps;
}

/** Required (non-optional) steps completed, out of all required steps. */
export function requiredProgress(
  content: Pick<LessonContent, 'steps'>,
  steps: Record<string, StepStatus>
): { done: number; total: number } {
  const required = content.steps.filter((s) => !s.optional);
  return { done: required.filter((s) => steps[s.key]?.completed).length, total: required.length };
}

/** Optional extensions completed; shown separately, never in the required total. */
export function optionalCompleted(content: Pick<LessonContent, 'steps'>, steps: Record<string, StepStatus>): number {
  return content.steps.filter((s) => s.optional && steps[s.key]?.completed).length;
}
