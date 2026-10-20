'use client';

import { FormEvent, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { MyGradesCard, type Grades } from '@/components/my-grades';

/* Student-facing peer review page (Hebrew, RTL, mobile-first). Rendered for
 * students at /r/<token> (talking to /api/r/<token> on the same origin), and
 * read-only for the instructor's "view as student" preview. */

// True in the instructor preview: everything renders, nothing can be saved.
const PreviewCtx = createContext(false);

type Criterion = { key: string; label: string; description: string; weight: number; counts?: boolean; max?: number | null };
const counts = (c: Criterion) => c.counts !== false;
type ScalePoint = { value: number; label: string };
type Prompt = { key: string; label: string; required: boolean };
type Rubric = {
  id: number;
  kind: string;
  version: number;
  criteria: Criterion[];
  scale: ScalePoint[];
  prompts: Prompt[];
  instructions: string;
};
type MyReview = { scores: Record<string, number>; responses: Record<string, string>; updated_at: string | null };
type PresentationItem = {
  id: number;
  team_name: string;
  project_title: string;
  demo_url: string;
  link_status: LinkStatus;
  link_detail: string;
  session_number: number | null;
  held_on: string | null;
  is_today: boolean;
  own_team: boolean;
  obligation: 'expected' | 'exempt' | null;
  accepting: boolean;
  my_review: MyReview | null;
  my_share: number | null;
};
type LinkStatus = 'ok' | 'warning' | 'broken' | '';
type RoundView = {
  id: number;
  number: number;
  kind: 'progress' | 'final';
  title: string;
  practice: boolean;
  link_required: boolean;
  status: 'scheduling' | 'reviewing' | 'closed';
  released: boolean;
  my_presentation: {
    id: number;
    session_number: number | null;
    held_on: string | null;
    demo_url: string;
    link_status: LinkStatus;
    link_detail: string;
    materials_text: string;
    has_slides: boolean;
    editable: boolean;
  } | null;
  selection: {
    open: boolean;
    deadline: string | null;
    locked: boolean;
    my_session: number | null;
    sessions: { number: number; held_on: string | null; capacity: number; taken: number }[];
  } | null;
  reviewing: {
    deadline: string | null;
    rubric: Rubric;
    presentations: PresentationItem[];
    progress: { expected: number; completed: number; outstanding: number[] };
  } | null;
  results: {
    valid_reviews: number;
    share: number | null;
    relative: number | null;
    criterion_means: Record<string, number>;
    prompts: Prompt[];
    feedback: { source: 'peer' | 'ai'; responses: Record<string, string> }[];
  } | null;
};
export type Home = {
  student: { name: string };
  course: { name: string; code: string };
  team: { id: number; name: string; project_title: string; join_code: string | null; members: string[] } | null;
  teams_policy: { open: boolean; max_size: number | null; deadline: string | null };
  today: string;
  rounds: RoundView[];
  grades: Grades;
  lessons?: { slug: string; title: string }[];
};
type Draft = { scores: Record<string, number>; responses: Record<string, string> };

const ERRORS: Record<string, string> = {
  window_closed: 'הביקורת על ההצגה הזו סגורה כרגע.',
  deadline_passed: 'המועד האחרון להגשת ביקורות עבר.',
  own_team: 'אי אפשר לבקר את הצוות שלך.',
  not_eligible: 'לא שובצת לבקר את ההצגה הזו.',
  invalid_score: 'יש לדרג כל קריטריון בסולם שמוצג.',
  missing_score: 'יש לדרג את כל הקריטריונים.',
  missing_response: 'יש למלא את כל שדות הטקסט המסומנים כחובה.',
  response_too_long: 'הטקסט ארוך מדי.',
  selection_closed: 'בחירת המועדים סגורה.',
  capacity_full: 'המפגש הזה מלא. בחרו מפגש אחר.',
  not_your_team: 'אפשר לבחור מועד רק עבור הצוות שלך.',
  locked: 'המרצה קבע/ה את מועד ההצגה של הצוות.',
  invalid_session: 'המפגש לא שייך לסבב הזה.',
  invalid_link: 'הקישור אינו תקין. פנו למרצה לקבלת קישור חדש.',
  invalid_url: 'הקישור חייב להתחיל ב-http:// או https://',
  not_pdf: 'יש להעלות קובץ PDF.',
  too_large: 'הקובץ גדול מדי (עד 20MB).',
  team_name_taken: 'כבר יש צוות בשם הזה. בחרו שם אחר.',
  invalid_team: 'יש לתת לצוות שם.',
  bad_code: 'לא נמצא צוות עם הקוד הזה. בדקו את הקוד עם חברי הצוות.',
  team_full: 'הצוות הזה כבר מלא.',
  already_in_team: 'כבר יש לך צוות. כדי לעבור צוות צריך קודם לעזוב אותו.',
  teams_locked: 'הרכב הצוותים נעול. לשינוי צוות פנו למרצה.'
};
const NETWORK_ERROR = 'אין חיבור לשרת. מה שכתבת נשמר במכשיר – נסו שוב.';

class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: 'no-store', ...init });
  } catch {
    throw new ApiError('network', NETWORK_ERROR);
  }
  if (!res.ok) {
    let code = res.status >= 500 ? 'network' : 'error';
    let message = res.status >= 500 ? NETWORK_ERROR : 'משהו השתבש. נסו שוב.';
    try {
      const body = await res.json();
      code = body?.detail?.code ?? code;
      message = ERRORS[code] ?? body?.detail?.message ?? message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(code, message);
  }
  return res.json();
}

function draftKey(token: string, presentationId: number) {
  return `cg-review-draft:${token}:${presentationId}`;
}
function loadDraft(token: string, presentationId: number): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(token, presentationId));
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null;
  }
}
function saveDraft(token: string, presentationId: number, draft: Draft | null) {
  try {
    if (draft) localStorage.setItem(draftKey(token, presentationId), JSON.stringify(draft));
    else localStorage.removeItem(draftKey(token, presentationId));
  } catch {
    /* storage unavailable — the form still works, just without the safety net */
  }
}

function weightedTotal(scores: Record<string, number>, criteria: Criterion[]): number | null {
  let num = 0;
  let den = 0;
  // Only counted criteria (the final score) make up the grade; the rest are remarks.
  for (const c of criteria) {
    if (!counts(c)) continue;
    const v = scores[c.key];
    if (v == null) return null;
    num += c.weight * v;
    den += c.weight;
  }
  return den > 0 ? num / den : null;
}

function roundLabel(r: { kind: string; number: number; practice?: boolean }) {
  if (r.practice) return 'סבב תרגול';
  return r.kind === 'final' ? 'הצגות גמר' : `סבב התקדמות ${r.number}`;
}
function sessionLabel(n: number | null, heldOn: string | null) {
  if (n == null) return 'טרם נקבע מועד';
  if (!heldOn) return `מפגש ${n}`;
  const d = new Date(`${heldOn}T12:00:00`);
  return `מפגש ${n} · ${d.toLocaleDateString('he-IL', { weekday: 'short', day: 'numeric', month: 'numeric' })}`;
}
function formatDeadline(iso: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleString('he-IL', { weekday: 'short', day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function countdown(ms: number) {
  const mins = Math.max(0, Math.floor(ms / 60000));
  const d = Math.floor(mins / 1440);
  const h = Math.floor((mins % 1440) / 60);
  const m = mins % 60;
  if (d) return `${d} ימים ו-${h} שעות`;
  if (h) return `${h} שעות ו-${m} דקות`;
  return `${m} דקות`;
}
function pct(v: number | null | undefined, digits = 1) {
  return v == null ? '—' : `${(v * 100).toFixed(digits)}%`;
}

function pickDefaultRound(rounds: RoundView[]): number | null {
  const by = (s: RoundView['status']) => rounds.filter((r) => r.status === s);
  const pick = by('reviewing')[0] ?? by('scheduling')[0] ?? [...rounds].reverse().find((r) => r.released) ?? rounds[rounds.length - 1];
  return pick ? pick.id : null;
}

export function loadStudentHome(token: string): Promise<Home> {
  return call<Home>(`/api/r/${token}`);
}

export function StudentView({
  token,
  loader,
  preview = false,
  banner
}: {
  token: string;
  loader: () => Promise<Home>;
  preview?: boolean;
  banner?: React.ReactNode;
}) {
  const [home, setHome] = useState<Home | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [roundId, setRoundId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await loader();
      setHome(data);
      setLoadError(null);
      setRoundId((current) => (current && data.rounds.some((r) => r.id === current) ? current : pickDefaultRound(data.rounds)));
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
    // The loader identity changes with the previewed student.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError && !home) {
    return (
      <Shell banner={banner}>
        <div className="rounded-lg border border-bad-soft bg-card p-5 text-[15px]">{loadError}</div>
      </Shell>
    );
  }
  if (!home) {
    return (
      <Shell banner={banner}>
        <div className="py-16 text-center text-ink-3">טוען…</div>
      </Shell>
    );
  }
  const round = home.rounds.find((r) => r.id === roundId) ?? null;

  return (
    <PreviewCtx.Provider value={preview}>
    <Shell banner={banner}>
      <header className="pb-4 pt-2">
        <div className="text-[12px] tracking-wide text-ink-3">{home.course.name}</div>
        <h1 className="font-hebrew text-[26px] leading-tight">שלום, {home.student.name}</h1>
        <div className="mt-1 text-[14px] text-ink-2">
          {home.team ? (
            <>
              הצוות שלך: <strong className="font-semibold">{home.team.name}</strong>
              {home.team.project_title ? ` · ${home.team.project_title}` : ''}
            </>
          ) : null}
        </div>
      </header>

      {!preview && home.lessons?.length ? <LessonsCard token={token} lessons={home.lessons} /> : null}

      <MyGradesCard grades={home.grades} />

      <TeamCard token={token} home={home} onUpdate={setHome} />

      <AnonymityNote />

      {home.rounds.length === 0 ? (
        <div className="mt-4 rounded-lg border border-border bg-card p-5 text-[15px] text-ink-2">
          אין כרגע סבב הצגות פתוח. כשהמרצה תפתח סבב, הוא יופיע כאן.
        </div>
      ) : (
        <>
          <nav className="-mx-4 mt-4 flex gap-2 overflow-x-auto px-4 pb-1" aria-label="סבבים">
            {home.rounds.map((r) => (
              <button
                key={r.id}
                onClick={() => setRoundId(r.id)}
                className={`shrink-0 rounded-full border px-3.5 py-1.5 text-[14px] ${
                  r.id === roundId ? 'border-forest bg-forest text-paper' : 'border-border bg-card text-ink-2'
                }`}
              >
                {roundLabel(r)}
                {r.status === 'reviewing' ? ' · פתוח' : ''}
              </button>
            ))}
          </nav>
          {round ? <RoundPanel key={round.id} token={token} round={round} team={home.team} onUpdate={setHome} /> : null}
        </>
      )}
    </Shell>
    </PreviewCtx.Provider>
  );
}

/* ---------------- Guided lessons entry point ---------------- */

function LessonsCard({ token, lessons }: { token: string; lessons: { slug: string; title: string }[] }) {
  return (
    <section className="mb-3 rounded-lg border border-forest-soft bg-card p-4 shadow-soft">
      <h2 className="font-hebrew text-[18px]">למידה בשיעור</h2>
      <div className="mt-2 grid gap-2">
        {lessons.map((l) => (
          <a
            key={l.slug}
            href={`/r/${token}/lessons/${encodeURIComponent(l.slug)}`}
            className="flex min-h-[48px] items-center justify-between gap-3 rounded-md border border-border bg-paper px-4 text-[15px] text-ink no-underline hover:border-forest"
          >
            <span>{l.title}</span>
            <span className="shrink-0 text-[14px] font-semibold text-forest">לשיעור ←</span>
          </a>
        ))}
      </div>
    </section>
  );
}

/* ---------------- Team: create, join with a code, leave ---------------- */

function TeamCard({ token, home, onUpdate }: { token: string; home: Home; onUpdate: (h: Home) => void }) {
  const preview = useContext(PreviewCtx);
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { team } = home;
  // Tick each minute so the countdown moves and the panel locks at the
  // deadline; the server enforces the lock on its own clock regardless.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!home.teams_policy.deadline) return;
    const id = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(id);
  }, [home.teams_policy.deadline]);
  const deadlineMs = home.teams_policy.deadline ? new Date(home.teams_policy.deadline).getTime() : null;
  const policy = { ...home.teams_policy, open: home.teams_policy.open && (deadlineMs == null || now < deadlineMs) };
  const deadlineNote =
    deadlineMs != null ? (
      policy.open ? (
        <p className="mt-2 text-[13px] text-ink-2">
          אפשר לשנות צוות עד {formatDeadline(home.teams_policy.deadline)} (עוד {countdown(deadlineMs - now)}). אחרי זה
          הרכב הצוותים יינעל.
        </p>
      ) : now >= deadlineMs ? (
        <p className="mt-2 text-[13px] text-ink-3">
          הרכב הצוותים ננעל ב-{formatDeadline(home.teams_policy.deadline)}. לשינוי צוות פנו למרצה.
        </p>
      ) : null
    ) : null;

  const post = async (path: string, body?: object) => {
    setBusy(true);
    setError(null);
    try {
      onUpdate(
        await call<Home>(`/api/r/${token}/team${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: body ? JSON.stringify(body) : undefined
        })
      );
      setName('');
      setTitle('');
      setCode('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (team) {
    return (
      <details className="mb-3 rounded-lg border border-border bg-card px-4 py-3 text-[14px] shadow-soft">
        <summary className="cursor-pointer text-ink-2">
          חברי הצוות ({team.members.length}){policy.open && team.join_code ? ' · קוד הצטרפות' : ''}
          {policy.open && deadlineMs != null ? ` · ננעל בעוד ${countdown(deadlineMs - now)}` : ''}
        </summary>
        <ul className="mt-2 grid gap-0.5">
          {team.members.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
        {policy.open ? deadlineNote : null}
        {policy.open ? (
          <fieldset disabled={preview || busy} className="mt-3 grid gap-2">
            {team.join_code ? (
              <p>
                קוד ההצטרפות לצוות:{' '}
                <button
                  type="button"
                  dir="ltr"
                  className="rounded bg-paper-2 px-2 py-0.5 font-mono text-[16px] font-semibold tracking-widest"
                  onClick={() => navigator.clipboard?.writeText(team.join_code ?? '')}
                  title="העתקה"
                >
                  {team.join_code}
                </button>{' '}
                <span className="text-ink-3">– שלחו אותו לחברי הצוות כדי שיצטרפו.</span>
              </p>
            ) : null}
            <button
              type="button"
              className="justify-self-start text-[13px] text-bad hover:underline"
              onClick={() => window.confirm('לעזוב את הצוות?') && post('/leave')}
            >
              עזיבת הצוות
            </button>
          </fieldset>
        ) : (
          deadlineNote ?? <p className="mt-2 text-[13px] text-ink-3">הרכב הצוותים נעול. לשינוי צוות פנו למרצה.</p>
        )}
        {error ? <p className="mt-2 text-bad">{error}</p> : null}
      </details>
    );
  }

  if (!policy.open) {
    return (
      <div className="mb-3 rounded-lg border border-border bg-card px-4 py-3 text-[14px] text-ink-2">
        עדיין לא שובצת לצוות. המרצה קובע/ת את הצוותים – פנו אליו/ה אם צריך.
        {deadlineNote}
      </div>
    );
  }

  return (
    <section className="mb-3 rounded-lg border border-forest-soft bg-card p-4 shadow-soft">
      <h2 className="font-hebrew text-[18px]">עדיין אין לך צוות</h2>
      <p className="mt-1 text-[13px] text-ink-3">
        פתחו צוות חדש ושלחו את קוד ההצטרפות לחברי הצוות, או הצטרפו לצוות קיים עם הקוד שקיבלתם
        {policy.max_size ? ` (עד ${policy.max_size} חברים בצוות)` : ''}.
      </p>
      {deadlineNote}
      <fieldset disabled={preview || busy} className="mt-3 grid gap-4 sm:grid-cols-2">
        <form
          className="grid content-start gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (code.trim()) void post('/join', { code });
          }}
        >
          <span className="text-[14px] font-semibold">הצטרפות לצוות קיים</span>
          <input
            dir="ltr"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="קוד הצטרפות"
            maxLength={16}
            className="h-11 rounded-md border border-border bg-white px-3 text-center font-mono tracking-widest"
          />
          <button type="submit" className="h-11 rounded-md bg-forest px-4 text-[15px] font-semibold text-paper">
            הצטרפות
          </button>
        </form>
        <form
          className="grid content-start gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) void post('', { name, project_title: title });
          }}
        >
          <span className="text-[14px] font-semibold">פתיחת צוות חדש</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="שם הצוות"
            maxLength={255}
            className="h-11 rounded-md border border-border bg-white px-3"
          />
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="שם הפרויקט (אפשר גם אחר כך)"
            maxLength={255}
            className="h-11 rounded-md border border-border bg-white px-3"
          />
          <button type="submit" className="h-11 rounded-md border border-forest px-4 text-[15px] font-semibold text-forest">
            פתיחת צוות
          </button>
        </form>
      </fieldset>
      {error ? <p className="mt-2 text-[14px] text-bad">{error}</p> : null}
    </section>
  );
}

function Shell({ children, banner }: { children: React.ReactNode; banner?: React.ReactNode }) {
  return (
    <div dir="rtl" lang="he" className="min-h-screen">
      {banner}
      <main className="mx-auto w-full max-w-[640px] px-4 pb-24 pt-4">{children}</main>
    </div>
  );
}

function AnonymityNote() {
  return (
    <details className="rounded-lg border border-forest-soft bg-forest-tint px-4 py-3 text-[14px] text-ink-2">
      <summary className="cursor-pointer font-semibold text-forest">🔒 מי רואה את הביקורות שלך?</summary>
      <p className="mt-2 leading-relaxed">
        הביקורות אנונימיות לסטודנטים ולצוותים המציגים: הצוות יראה רק ציונים מצטברים ואת הטקסטים, בלי שמות ובלי סדר
        הגשה. המרצה רואה מי כתב כל ביקורת – כדי לעקוב אחר ההשתתפות שלך ולטפל בתוכן לא הולם. אף סטודנט לא רואה ביקורות
        של אחרים או ציונים בזמן אמת.
      </p>
    </details>
  );
}

function RoundPanel({
  token,
  round,
  team,
  onUpdate
}: {
  token: string;
  round: RoundView;
  team: Home['team'];
  onUpdate: (h: Home) => void;
}) {
  return (
    <div className="mt-4 grid gap-4">
      {round.practice ? (
        <div className="rounded-lg border border-terracotta-soft bg-terracotta-tint px-4 py-3 text-[14px] leading-relaxed">
          <strong>סבב תרגול – לא נכלל בציון.</strong> זו הזדמנות להתנסות בטופס הביקורת. אפשר לבקר כל צוות אחר בסבב.
        </div>
      ) : null}
      {round.link_required && round.my_presentation && round.my_presentation.link_status !== 'ok' ? (
        <div className="rounded-lg border border-bad/40 bg-bad/5 px-4 py-3 text-[14px] leading-relaxed">
          <strong>
            {round.my_presentation.demo_url ? 'הקישור של הצוות לא עובד כמו שצריך.' : 'הצוות עוד לא הגיש קישור לאתר.'}
          </strong>{' '}
          {round.my_presentation.link_detail ? `${round.my_presentation.link_detail}. ` : ''}
          המבקרים צריכים קישור לאתר פעיל כדי להתנסות בו. אפשר לעדכן אותו למטה, ב״ההצגה של הצוות שלך״.
        </div>
      ) : null}
      {round.selection ? <SelectionCard token={token} round={round} hasTeam={!!team} onUpdate={onUpdate} /> : null}
      {round.results ? <ResultsCard round={round} /> : null}
      {round.reviewing ? <ReviewingSection token={token} round={round} onUpdate={onUpdate} /> : null}
      {round.my_presentation && round.my_presentation.editable ? (
        <MaterialsCard token={token} round={round} team={team} onUpdate={onUpdate} />
      ) : null}
      {round.status === 'closed' && !round.released ? (
        <div className="rounded-lg border border-border bg-card p-4 text-[14px] text-ink-2">
          הסבב נסגר. התוצאות והמשוב יפורסמו אחרי שהמרצה ישחרר אותם.
        </div>
      ) : null}
    </div>
  );
}

/* ---------------- Session selection ---------------- */

function SelectionCard({
  token,
  round,
  hasTeam,
  onUpdate
}: {
  token: string;
  round: RoundView;
  hasTeam: boolean;
  onUpdate: (h: Home) => void;
}) {
  const sel = round.selection!;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const preview = useContext(PreviewCtx);
  const canChoose = !preview && hasTeam && sel.open && !sel.locked && round.my_presentation;

  const choose = async (n: number) => {
    if (!round.my_presentation) return;
    setBusy(true);
    setError(null);
    try {
      onUpdate(
        await call<Home>(`/api/r/${token}/presentations/${round.my_presentation.id}/session`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_number: n })
        })
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-soft">
      <h2 className="font-hebrew text-[20px]">בחירת מועד הצגה</h2>
      <p className="mt-1 text-[14px] text-ink-2">
        {sel.locked
          ? 'המרצה קבע/ה את מועד ההצגה של הצוות שלך.'
          : sel.open
            ? 'כל חבר/ת צוות יכול/ה לבחור מועד עבור הצוות. אפשר לשנות עד המועד האחרון.'
            : 'בחירת המועדים נסגרה. צוותים שלא בחרו ישובצו על ידי המרצה.'}
        {sel.deadline ? ` מועד אחרון: ${formatDeadline(sel.deadline)}.` : ''}
      </p>
      <div className="mt-3 grid gap-2">
        {sel.sessions.map((s) => {
          const mine = sel.my_session === s.number;
          const full = s.taken >= s.capacity && !mine;
          return (
            <button
              key={s.number}
              disabled={!canChoose || busy || full || mine}
              onClick={() => choose(s.number)}
              className={`flex min-h-[48px] items-center justify-between rounded-md border px-4 text-[15px] transition ${
                mine ? 'border-forest bg-forest-tint font-semibold text-forest' : 'border-border bg-paper'
              } disabled:cursor-default ${full ? 'opacity-50' : ''}`}
            >
              <span>{sessionLabel(s.number, s.held_on)}</span>
              <span className="text-[13px] text-ink-3">
                {mine ? '✓ המועד שלכם' : full ? 'מלא' : `${s.capacity - s.taken} מקומות פנויים`}
              </span>
            </button>
          );
        })}
      </div>
      {error ? <p className="mt-2 text-[14px] text-bad">{error}</p> : null}
    </section>
  );
}

/* ---------------- Reviewing ---------------- */

function ReviewingSection({ token, round, onUpdate }: { token: string; round: RoundView; onUpdate: (h: Home) => void }) {
  const preview = useContext(PreviewCtx);
  const rv = round.reviewing!;
  const rubric = rv.rubric;
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});

  useEffect(() => {
    if (preview) return; // previews never read or write a student's device drafts
    const loaded: Record<number, Draft> = {};
    for (const p of rv.presentations) {
      const d = loadDraft(token, p.id);
      if (d) loaded[p.id] = d;
    }
    setDrafts(loaded);
    // Drafts are read once per round; later edits flow through setDraft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, round.id]);

  const setDraft = (id: number, d: Draft | null) => {
    if (preview) return;
    saveDraft(token, id, d);
    setDrafts((prev) => {
      const next = { ...prev };
      if (d) next[id] = d;
      else delete next[id];
      return next;
    });
  };

  // Live normalised shares: saved reviews, overridden by complete local drafts.
  const live = useMemo(() => {
    const totals: Record<number, { total: number; draft: boolean }> = {};
    for (const p of rv.presentations) {
      const d = drafts[p.id];
      const dt = d ? weightedTotal(d.scores, rubric.criteria) : null;
      if (dt != null && p.accepting) totals[p.id] = { total: dt, draft: true };
      else if (p.my_review) {
        const t = weightedTotal(p.my_review.scores, rubric.criteria);
        if (t != null) totals[p.id] = { total: t, draft: false };
      }
    }
    const sum = Object.values(totals).reduce((a, b) => a + b.total, 0);
    const out: Record<number, { total: number; share: number; draft: boolean }> = {};
    for (const [id, v] of Object.entries(totals)) out[Number(id)] = { ...v, share: sum > 0 ? v.total / sum : 0 };
    return out;
  }, [drafts, rv.presentations, rubric.criteria]);

  const groups = useMemo(() => {
    const sorted = [...rv.presentations].sort(
      (a, b) => Number(b.is_today) - Number(a.is_today) || (a.session_number ?? 99) - (b.session_number ?? 99) || a.id - b.id
    );
    const out: { label: string; today: boolean; items: PresentationItem[] }[] = [];
    for (const p of sorted) {
      const label = p.is_today ? `היום · ${sessionLabel(p.session_number, p.held_on)}` : sessionLabel(p.session_number, p.held_on);
      const last = out[out.length - 1];
      if (last && last.label === label) last.items.push(p);
      else out.push({ label, today: p.is_today, items: [p] });
    }
    return out;
  }, [rv.presentations]);

  const { expected, completed, outstanding } = rv.progress;
  const firstOpen = rv.presentations.find((p) => p.accepting && !p.my_review)?.id ?? null;
  const [expanded, setExpanded] = useState<number | null>(firstOpen);
  const outstandingNames = rv.presentations.filter((p) => outstanding.includes(p.id));

  return (
    <>
      <section className="rounded-lg border border-border bg-card p-4 shadow-soft">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-hebrew text-[20px]">ביקורת על ההצגות</h2>
          <span className="tnum text-[14px] text-ink-2">
            {completed}/{expected} הוגשו
          </span>
        </div>
        <div className="progress-bar mt-2" aria-hidden>
          <span style={{ width: `${expected ? (completed / expected) * 100 : 0}%` }} />
        </div>
        {outstandingNames.length > 0 ? (
          <p className="mt-2 text-[14px] text-ink-2">
            נשארו: {outstandingNames.map((p) => p.team_name).join(', ')}
          </p>
        ) : expected > 0 ? (
          <p className="mt-2 text-[14px] text-ok">✓ הגשת את כל הביקורות הנדרשות בסבב הזה.</p>
        ) : null}
        {rv.deadline ? <p className="mt-1 text-[13px] text-ink-3">מועד אחרון לעריכה: {formatDeadline(rv.deadline)}</p> : null}
        {rubric.instructions ? (
          <p className="mt-3 rounded-md bg-terracotta-tint px-3 py-2 text-[14px] leading-relaxed text-ink">{rubric.instructions}</p>
        ) : null}
        <p className="mt-2 text-[13px] text-ink-3">
          אפשר למלא תוך כדי ההצגה או אחרי שניסיתם את המוצר, ולערוך עד שהביקורת נסגרת.
        </p>
      </section>

      {Object.keys(live).length > 0 ? <MySharesCard round={round} live={live} /> : null}

      {groups.map((g) => (
        <section key={g.label} className="grid gap-2">
          <h3 className={`px-1 text-[14px] font-semibold ${g.today ? 'text-forest' : 'text-ink-3'}`}>{g.label}</h3>
          {g.items.map((p) => (
            <PresentationCard
              key={p.id}
              token={token}
              p={p}
              rubric={rubric}
              linkRequired={round.link_required}
              draft={drafts[p.id] ?? null}
              setDraft={(d) => setDraft(p.id, d)}
              share={live[p.id]}
              expanded={expanded === p.id}
              toggle={() => setExpanded((cur) => (cur === p.id ? null : p.id))}
              onSaved={(h) => {
                onUpdate(h);
                const next = h.rounds
                  .find((r) => r.id === round.id)
                  ?.reviewing?.presentations.find((x) => x.accepting && !x.my_review && x.id !== p.id);
                setExpanded(next ? next.id : null);
              }}
            />
          ))}
        </section>
      ))}
    </>
  );
}

function MySharesCard({ round, live }: { round: RoundView; live: Record<number, { total: number; share: number; draft: boolean }> }) {
  const rows = round.reviewing!.presentations.filter((p) => live[p.id]);
  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-soft">
      <h2 className="font-hebrew text-[18px]">הציונים שלך בסבב</h2>
      <p className="mt-1 text-[13px] leading-relaxed text-ink-3">
        הציונים שנתת מנורמלים כך שסכומם 100%: מה שנחשב הוא היחס בין הצוותים, לא הגובה המוחלט. גם השיפוט שלך נמדד – לפי
        ההתאמה בין הדירוג שלך לדירוג הכולל של הכיתה.
      </p>
      <div className="mt-3 grid gap-1.5">
        {rows.map((p) => {
          const v = live[p.id];
          return (
            <div key={p.id} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 text-[14px]">
              <div className="truncate">
                {p.team_name}
                {v.draft ? <span className="text-[12px] text-warn"> · טיוטה</span> : null}
              </div>
              <div className="tnum text-ink-3">{v.total.toFixed(2)}</div>
              <div className="flex w-[110px] items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-paper-2">
                  <div className="h-full rounded-full bg-forest" style={{ width: `${Math.min(100, v.share * 100)}%` }} />
                </div>
                <span className="tnum w-[44px] text-left font-semibold">{pct(v.share, 0)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function statusPill(p: PresentationItem, draft: Draft | null) {
  if (p.own_team) return <span className="pill pill-info">הצוות שלך</span>;
  if (p.obligation === 'exempt' && !p.my_review) return <span className="pill">פטור</span>;
  if (p.my_review && !draft) return <span className="pill pill-ok">✓ נשלח</span>;
  if (draft && p.accepting) return <span className="pill pill-warn">טיוטה לא נשלחה</span>;
  if (p.accepting) return <span className="pill pill-forest">פתוח לביקורת</span>;
  if (p.obligation == null) return null;
  return <span className="pill">{p.my_review ? '✓ נשלח · סגור' : 'עוד לא נפתח'}</span>;
}

function PresentationCard({
  token,
  p,
  rubric,
  draft,
  setDraft,
  share,
  expanded,
  toggle,
  onSaved,
  linkRequired = false
}: {
  token: string;
  p: PresentationItem;
  rubric: Rubric;
  draft: Draft | null;
  setDraft: (d: Draft | null) => void;
  linkRequired?: boolean;
  share?: { share: number; draft: boolean };
  expanded: boolean;
  toggle: () => void;
  onSaved: (h: Home) => void;
}) {
  const canOpen = !p.own_team && (p.accepting || p.my_review);
  return (
    <article
      className={`rounded-lg border bg-card shadow-soft ${p.accepting && !p.my_review ? 'border-forest-soft' : 'border-border'} ${
        p.own_team ? 'opacity-70' : ''
      }`}
    >
      <button
        className="flex w-full items-start justify-between gap-3 p-4 text-right disabled:cursor-default"
        onClick={toggle}
        disabled={!canOpen}
        aria-expanded={expanded}
      >
        <div className="min-w-0">
          <div className="text-[16px] font-semibold">{p.team_name}</div>
          {p.project_title ? <div className="text-[14px] text-ink-2">{p.project_title}</div> : null}
          {share ? <div className="mt-1 text-[12px] text-ink-3">החלק שנתת: {pct(share.share)}</div> : null}
        </div>
        <div className="shrink-0">{statusPill(p, draft)}</div>
      </button>
      {p.demo_url ? (
        <div className="-mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pb-3">
          <a
            href={p.demo_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-10 items-center rounded-md border border-forest px-4 text-[14px] font-semibold text-forest hover:bg-forest hover:text-paper"
          >
            {linkRequired ? 'פתיחת האתר של הצוות ↗' : 'פתיחת ההדגמה / ה-MVP ↗'}
          </a>
          <LinkStatusNote status={p.link_status} detail={p.link_detail} />
        </div>
      ) : linkRequired && !p.own_team ? (
        <div className="-mt-1 px-4 pb-3 text-[13px] text-ink-3">הצוות עוד לא הגיש קישור לאתר.</div>
      ) : null}
      {expanded && canOpen ? (
        <ReviewForm token={token} p={p} rubric={rubric} draft={draft} setDraft={setDraft} onSaved={onSaved} />
      ) : null}
    </article>
  );
}

function LinkStatusNote({ status, detail }: { status: LinkStatus; detail: string }) {
  if (!status) return null;
  const tone = status === 'ok' ? 'text-ok' : status === 'warning' ? 'text-warn' : 'text-bad';
  const text = status === 'ok' ? 'האתר נבדק ונפתח ✓' : `⚠ ${detail}`;
  return <span className={`text-[13px] ${tone}`}>{text}</span>;
}

function NumberScore({
  value,
  max,
  onChange
}: {
  value: number | undefined;
  max: number;
  onChange: (v: number | null) => void;
}) {
  return (
    <div className="mt-2 flex items-center gap-3">
      <input
        type="number"
        inputMode="decimal"
        min={0}
        max={max}
        step="any"
        dir="ltr"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        placeholder={`0–${max}`}
        aria-label={`ציון מ-0 עד ${max}`}
        className="h-12 w-28 rounded-md border border-border bg-white px-3 text-center text-[20px] font-semibold"
      />
      <span className="text-[14px] text-ink-3">מתוך {max}</span>
    </div>
  );
}

function ReviewForm({
  token,
  p,
  rubric,
  draft,
  setDraft,
  onSaved
}: {
  token: string;
  p: PresentationItem;
  rubric: Rubric;
  draft: Draft | null;
  setDraft: (d: Draft | null) => void;
  onSaved: (h: Home) => void;
}) {
  const base: Draft = draft ?? {
    scores: p.my_review?.scores ?? {},
    responses: p.my_review?.responses ?? {}
  };
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const preview = useContext(PreviewCtx);
  const readOnly = !p.accepting || preview;

  const update = (next: Draft) => {
    setError(null);
    setDraft(next);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const missing = rubric.criteria.filter((c) => counts(c) && base.scores[c.key] == null);
    if (missing.length) {
      setError(ERRORS.missing_score);
      return;
    }
    const outOfRange = rubric.criteria.find((c) => {
      const v = base.scores[c.key];
      return c.max != null && v != null && (v < 0 || v > c.max);
    });
    if (outOfRange) {
      setError(`הציון ב״${outOfRange.label}״ צריך להיות בין 0 ל-${outOfRange.max}.`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const h = await call<Home>(`/api/r/${token}/reviews/${p.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(base)
      });
      setDraft(null);
      onSaved(h);
    } catch (err) {
      // Keep the input: the draft stays in local storage and in the form.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-5 border-t border-line-soft p-4">
      {[...rubric.criteria.filter(counts), ...rubric.criteria.filter((c) => !counts(c))].map((c, i, all) => {
        const value = base.scores[c.key];
        const label = rubric.scale.find((s) => s.value === value)?.label;
        const firstRemark = !counts(c) && (i === 0 || counts(all[i - 1]));
        return (
          <div key={c.key}>
            {firstRemark ? (
              <p className="mb-3 border-t border-line-soft pt-3 text-[13px] text-ink-3">
                הערות לצוות (רשות) – לא נכנסות לציון, רק עוזרות לצוות להשתפר.
              </p>
            ) : null}
          <fieldset disabled={readOnly} className={counts(c) ? 'rounded-md bg-forest-tint p-3' : ''}>
            <legend className="text-[15px] font-semibold">
              {c.label}
              {counts(c) ? <span className="text-terracotta"> *</span> : <span className="text-[12px] font-normal text-ink-3"> (רשות)</span>}
            </legend>
            {c.description ? <p className="mt-0.5 text-[13px] text-ink-3">{c.description}</p> : null}
            {c.max != null ? (
              <NumberScore
                value={value}
                max={c.max}
                onChange={(v) => {
                  const scores = { ...base.scores };
                  if (v == null) delete scores[c.key];
                  else scores[c.key] = v;
                  update({ ...base, scores });
                }}
              />
            ) : (
            <>
            <div className="mt-2 grid gap-1.5" style={{ gridTemplateColumns: `repeat(${rubric.scale.length}, minmax(0, 1fr))` }}>
              {rubric.scale.map((s) => (
                <button
                  type="button"
                  key={s.value}
                  aria-pressed={value === s.value}
                  aria-label={`${s.value} – ${s.label}`}
                  onClick={() => update({ ...base, scores: { ...base.scores, [c.key]: s.value } })}
                  className={`h-11 rounded-md border text-[16px] font-semibold transition ${
                    value === s.value ? 'border-forest bg-forest text-paper' : 'border-border bg-paper text-ink-2'
                  }`}
                >
                  {s.value}
                </button>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-[12px] text-ink-3">
              <span>{rubric.scale[0]?.label}</span>
              <span className="font-semibold text-ink-2">{label ?? ''}</span>
              <span>{rubric.scale[rubric.scale.length - 1]?.label}</span>
            </div>
            </>
            )}
          </fieldset>
          </div>
        );
      })}
      {rubric.prompts.map((pr) => (
        <label key={pr.key} className="grid gap-1.5">
          <span className="text-[15px] font-semibold">
            {pr.label}
            <span className="text-[12px] font-normal text-ink-3"> (רשות)</span>
          </span>
          <textarea
            dir="auto"
            readOnly={readOnly}
            value={base.responses[pr.key] ?? ''}
            onChange={(e) => update({ ...base, responses: { ...base.responses, [pr.key]: e.target.value } })}
            rows={3}
            maxLength={4000}
            className="w-full rounded-md border border-border bg-white px-3 py-2 text-[15px] outline-none focus:border-forest focus:ring-2 focus:ring-forest-tint"
          />
        </label>
      ))}
      {error ? (
        <p role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-[14px] text-bad">
          {error}
        </p>
      ) : null}
      {readOnly ? (
        <p className="text-[13px] text-ink-3">{preview ? 'תצוגה מקדימה – אי אפשר לשלוח מכאן.' : 'הביקורת סגורה לעריכה.'}</p>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <span className="text-[12px] text-ink-3">{draft ? 'הטיוטה נשמרת במכשיר עד השליחה' : ''}</span>
          <button
            type="submit"
            disabled={saving}
            className="h-11 shrink-0 whitespace-nowrap rounded-md bg-forest px-5 text-[15px] font-semibold text-paper disabled:opacity-50"
          >
            {saving ? 'שולח…' : p.my_review ? 'עדכון הביקורת' : 'שליחת הביקורת'}
          </button>
        </div>
      )}
    </form>
  );
}

/* ---------------- Results ---------------- */

function ResultsCard({ round }: { round: RoundView }) {
  const r = round.results!;
  const criteria = round.reviewing?.rubric.criteria ?? [];
  const scaleMax = Math.max(...(round.reviewing?.rubric.scale.map((s) => s.value) ?? [5]));
  return (
    <section className="rounded-lg border border-forest bg-card p-4 shadow-card">
      <h2 className="font-hebrew text-[20px]">התוצאות של הצוות שלך</h2>
      {r.share == null ? (
        <p className="mt-2 text-[14px] text-ink-2">להצגה של הצוות עדיין אין ציון (לא התקבלו ביקורות תקפות).</p>
      ) : (
        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
          <Stat label="ביקורות תקפות" value={String(r.valid_reviews)} />
          <Stat label="חלק מסך הציונים" value={pct(r.share)} />
          <Stat label="ביחס לממוצע" value={r.relative == null ? '—' : `×${r.relative.toFixed(2)}`} />
        </div>
      )}
      {criteria.length && Object.keys(r.criterion_means).length ? (
        <div className="mt-4 grid gap-2">
          <p className="text-[13px] text-ink-3">ממוצע ההערות שקיבלתם (לא נכנס לציון):</p>
          {criteria.map((c) => {
            const v = r.criterion_means[c.key];
            if (v == null) return null;
            return (
              <div key={c.key} className="text-[14px]">
                <div className="flex justify-between gap-2">
                  <span>{c.label}</span>
                  <span className="tnum font-semibold">{v.toFixed(2)}</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-paper-2">
                  <div
                    className="h-full rounded-full bg-forest"
                    style={{ width: `${Math.min(100, (v / (c.max ?? scaleMax)) * 100)}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
      {r.feedback.length ? (
        <div className="mt-5">
          <h3 className="text-[15px] font-semibold">משוב (אנונימי)</h3>
          <ul className="mt-2 grid gap-2">
            {r.feedback.map((f, i) => (
              <li key={i} className="rounded-md border border-line-soft bg-paper px-3 py-2 text-[14px] leading-relaxed">
                {f.source === 'ai' ? <div className="mb-1 text-[12px] font-semibold text-info">בודק/ת AI</div> : null}
                {r.prompts.map((p) =>
                  f.responses[p.key] ? (
                    <p key={p.key}>
                      <span className="text-ink-3">{p.label} </span>
                      <span dir="auto">{f.responses[p.key]}</span>
                    </p>
                  ) : null
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-paper-2 px-2 py-2.5">
      <div className="tnum font-display text-[20px]">{value}</div>
      <div className="text-[12px] text-ink-3">{label}</div>
    </div>
  );
}

/* ---------------- Team materials ---------------- */

function MaterialsCard({
  token,
  round,
  team,
  onUpdate
}: {
  token: string;
  round: RoundView;
  team: Home['team'];
  onUpdate: (h: Home) => void;
}) {
  const preview = useContext(PreviewCtx);
  const mp = round.my_presentation!;
  const [title, setTitle] = useState(team?.project_title ?? '');
  const [demo, setDemo] = useState(mp.demo_url);
  const [text, setText] = useState(mp.materials_text);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setStatus(null);
    try {
      if (team && title.trim() !== team.project_title) {
        await call<Home>(`/api/r/${token}/team`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_title: title })
        });
      }
      onUpdate(
        await call<Home>(`/api/r/${token}/presentations/${mp.id}/materials`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ demo_url: demo, materials_text: text })
        })
      );
      setStatus('נשמר ✓');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (file.size > 20 * 1024 * 1024) {
      setError(ERRORS.too_large);
      return;
    }
    setStatus('מעלה…');
    try {
      const target = await call<{ direct: boolean; url?: string; key?: string }>(
        `/api/r/${token}/presentations/${mp.id}/slides/upload-url`,
        { method: 'POST' }
      );
      if (target.direct) {
        // Straight to storage: hosted request bodies are capped (~4.5 MB).
        const put = await fetch(target.url!, {
          method: 'PUT',
          body: file,
          headers: { 'Content-Type': 'application/pdf', 'x-upsert': 'true' }
        });
        if (!put.ok) throw new ApiError('upload', 'ההעלאה נכשלה. נסו שוב.');
        onUpdate(
          await call<Home>(`/api/r/${token}/presentations/${mp.id}/slides/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: target.key, filename: file.name })
          })
        );
      } else {
        const fd = new FormData();
        fd.append('file', file);
        onUpdate(await call<Home>(`/api/r/${token}/presentations/${mp.id}/slides`, { method: 'POST', body: fd }));
      }
      setStatus('המצגת הועלתה ✓');
    } catch (err) {
      setStatus(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <details
      className="rounded-lg border border-border bg-card p-4 shadow-soft"
      open={round.link_required && mp.link_status !== 'ok' ? true : undefined}
    >
      <summary className="cursor-pointer font-hebrew text-[18px]">
        ההצגה של הצוות שלך · {sessionLabel(mp.session_number, mp.held_on)}
      </summary>
      <form onSubmit={save} className="mt-3 grid gap-3">
        <fieldset disabled={preview} className="grid gap-3">
        <p className="text-[13px] text-ink-3">
          הפרטים מוצגים למבקרים, והתיאור והמצגת משמשים גם את בודק ה-AI של הסבב.
        </p>
        <label className="grid gap-1 text-[14px]">
          <span className="font-semibold">שם הפרויקט</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className="h-11 rounded-md border border-border bg-white px-3" />
        </label>
        <label className="grid gap-1 text-[14px]">
          <span className="font-semibold">
            {round.link_required ? 'קישור לאתר הפעיל (חובה)' : 'קישור להדגמה / MVP (רשות)'}
          </span>
          <input
            dir="ltr"
            type="url"
            inputMode="url"
            placeholder="https://"
            value={demo}
            onChange={(e) => setDemo(e.target.value)}
            className="h-11 rounded-md border border-border bg-white px-3 text-left"
          />
          {mp.demo_url && demo === mp.demo_url ? <LinkStatusNote status={mp.link_status} detail={mp.link_detail} /> : null}
          {round.link_required ? (
            <span className="text-[12px] text-ink-3">
              קישור שאחרים יכולים לפתוח בלי להתחבר – לא קישור לקוד, לשיחה או לקובץ. נבדוק אותו בשמירה.
            </span>
          ) : null}
        </label>
        <label className="grid gap-1 text-[14px]">
          <span className="font-semibold">תיאור קצר: הבעיה, המשתמש/ת, מה הודגם ומה נבדק</span>
          <textarea dir="auto" rows={4} value={text} onChange={(e) => setText(e.target.value)} className="rounded-md border border-border bg-white px-3 py-2" />
        </label>
        <label className="grid gap-1 text-[14px]">
          <span className="font-semibold">מצגת (PDF){mp.has_slides ? ' · הועלתה ✓' : ''}</span>
          <input type="file" accept="application/pdf" onChange={(e) => upload(e.target.files?.[0])} className="text-[13px]" />
        </label>
        {error ? <p className="text-[14px] text-bad">{error}</p> : null}
        <div className="flex items-center justify-between">
          <span className="text-[13px] text-ok">{status}</span>
          <button type="submit" className="h-11 rounded-md bg-forest px-5 text-[15px] font-semibold text-paper">
            שמירה
          </button>
        </div>
      </fieldset>
      </form>
    </details>
  );
}
