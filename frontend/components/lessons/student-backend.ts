/* The player's backend for a signed-in student: same-origin calls to
 * /api/r/<token>/lessons/... (proxied to the API, so the cg_student cookie is
 * first-party). Writes carry X-CG-Student: 1, which the API requires (a custom
 * header forces a CORS preflight, so another site can't write with the
 * student's cookie). Every failure becomes a LessonApiError; a request that
 * never got an answer is code 'network', so callers know a retry is safe. */

import {
  LessonApiError,
  type AttemptInput,
  type AttemptResult,
  type CommitmentInput,
  type CommitmentsResult,
  type ExperimentInput,
  type ExperimentsResult,
  type FinalInput,
  type LessonBackend,
  type LessonPayload,
  type ProgressPatch,
  type ProgressResult
} from '@/components/lessons/types';

export type StudentLessonSummary = {
  slug: string;
  title: string;
  guiding_question: string;
  status: 'not_started' | 'in_progress' | 'completed';
  required_done: number;
  required_total: number;
  current_step_key: string | null;
};

const NETWORK_ERROR = 'אין חיבור לשרת. מה שכתבת נשמר במכשיר – נסו שוב.';

// Codes whose server message is English (or missing); the lesson service's
// own errors already carry Hebrew messages.
const MESSAGES: Record<string, string> = {
  not_signed_in: 'צריך להתחבר כדי לשמור את ההתקדמות.',
  wrong_account: 'הקישור הזה שייך לחשבון של סטודנט/ית אחר/ת.',
  withdrawn: 'ההרשמה שלך לקורס בוטלה, ולכן אי אפשר לשמור שינויים.',
  bad_request_origin: 'הבקשה נחסמה. רעננו את הדף ונסו שוב.',
  invalid_link: 'הקישור אינו תקין. פנו למרצה לקבלת קישור חדש.',
  lesson_not_found: 'השיעור לא נמצא, או שעדיין לא פורסם.'
};

async function request<T>(path: string, method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE' = 'GET', body?: unknown): Promise<T> {
  const write = method !== 'GET';
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: write ? { 'Content-Type': 'application/json', 'X-CG-Student': '1' } : undefined,
      body: body === undefined ? undefined : JSON.stringify(body)
    });
  } catch {
    throw new LessonApiError('network', NETWORK_ERROR, 0);
  }
  if (!res.ok) {
    let code = res.status >= 500 ? 'network' : 'error';
    let message = res.status >= 500 ? NETWORK_ERROR : 'משהו השתבש. נסו שוב.';
    let detail: Record<string, unknown> = {};
    try {
      const parsed = await res.json();
      if (parsed?.detail && typeof parsed.detail === 'object' && !Array.isArray(parsed.detail)) {
        detail = parsed.detail as Record<string, unknown>;
        if (typeof detail.code === 'string') code = detail.code;
        message = MESSAGES[code] ?? (typeof detail.message === 'string' ? detail.message : message);
      }
    } catch {
      /* not JSON */
    }
    throw new LessonApiError(code, message, res.status, detail);
  }
  try {
    return (await res.json()) as T;
  } catch {
    // The write may have landed even though the answer got cut off.
    throw new LessonApiError('network', NETWORK_ERROR, res.status);
  }
}

export function studentLessonBackend(token: string, slug: string): LessonBackend {
  const base = `/api/r/${encodeURIComponent(token)}/lessons/${encodeURIComponent(slug)}`;
  return {
    mode: 'student',
    load: () => request<LessonPayload>(base),
    patchProgress: (body: ProgressPatch) => request<ProgressResult>(`${base}/progress`, 'PATCH', body),
    submitAttempt: (body: AttemptInput) => request<AttemptResult>(`${base}/attempts`, 'POST', body),
    reveal: (questionKey: string, requestId: string) =>
      request<AttemptResult>(`${base}/questions/${encodeURIComponent(questionKey)}/reveal`, 'POST', { request_id: requestId }),
    saveExperiment: (runUuid: string, body: ExperimentInput) =>
      request<ExperimentsResult>(`${base}/experiments/${encodeURIComponent(runUuid)}`, 'PUT', body),
    deleteExperiment: (runUuid: string, expectedRevision: number) =>
      request<ExperimentsResult>(
        `${base}/experiments/${encodeURIComponent(runUuid)}?expected_revision=${encodeURIComponent(expectedRevision)}`,
        'DELETE'
      ),
    commit: (body: CommitmentInput) => request<CommitmentsResult>(`${base}/commitments`, 'POST', body),
    recordFinal: (commitmentId: number, body: FinalInput) =>
      request<CommitmentsResult>(`${base}/commitments/${encodeURIComponent(commitmentId)}/final`, 'PATCH', body)
  };
}

export async function listStudentLessons(token: string): Promise<StudentLessonSummary[]> {
  const data = await request<{ lessons: StudentLessonSummary[] }>(`/api/r/${encodeURIComponent(token)}/lessons`);
  return data.lessons;
}

/** A random UUID for request ids and run ids. crypto.randomUUID needs a
 * secure context (https or localhost); getRandomValues works everywhere. */
export function newUuid(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
