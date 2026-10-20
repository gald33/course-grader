'use client';

import { FormEvent, useEffect, useState } from 'react';

import { AuthCard, Field, SubmitButton, studentAuthCall, type Destinations } from '@/components/student-auth';

/* Student sign-in: email (as given to the college) + password. The first
 * password is the national ID number and must be replaced at first login.
 * Hebrew, RTL, phone-first. */

type LoginResult = Destinations | { must_change_password: true };

const inputClass = 'h-11 w-full rounded-md border border-border bg-white px-3 text-left';

// ?next= — where a student page sent us (e.g. a lesson after the session
// expired). Only this site's student links: a path under /r/<token>, never
// another origin (no scheme, no //, no backslashes or control characters)
// and no dot segments that would climb out of /r/.
const SAFE_NEXT = /^\/r\/[A-Za-z0-9_-]+(\/.*)?$/;

function safeNext(): string | null {
  const raw = new URLSearchParams(window.location.search).get('next');
  if (
    !raw ||
    !SAFE_NEXT.test(raw) ||
    raw.includes('//') ||
    raw.includes('\\') ||
    /\.\.|%2e/i.test(raw) ||
    /[\u0000-\u001f\u007f]/.test(raw)
  ) {
    return null;
  }
  return raw;
}

export default function StudentLoginPage() {
  const [mode, setMode] = useState<'login' | 'change' | 'forgot'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [choices, setChoices] = useState<Destinations['courses'] | null>(null);

  const go = (d: Destinations) => {
    // Follow ?next= only into this student's own links: a link someone else
    // shared would only answer "this link belongs to another account" again.
    const next = safeNext();
    // (SAFE_NEXT already limits next to /r/<token> or /r/<token>/…)
    const own = next !== null && d.courses.some((c) => next === c.url || next.startsWith(`${c.url}/`));
    if (next && own) window.location.assign(next);
    else if (d.redirect) window.location.assign(d.redirect);
    else setChoices(d.courses);
  };

  useEffect(() => {
    if (new URLSearchParams(window.location.search).has('forgot')) setMode('forgot');
    // Already signed in: skip the form.
    studentAuthCall<Destinations>('/api/student-auth/me')
      .then(go)
      .catch(() => undefined);
  }, []);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const login = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const result = await studentAuthCall<LoginResult>('/api/student-auth/login', { email, password });
      if ('must_change_password' in result) setMode('change');
      else go(result);
    });
  };

  const change = (e: FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 8) return setError('הסיסמה צריכה לכלול לפחות 8 תווים.');
    if (newPassword !== confirm) return setError('הסיסמאות אינן תואמות.');
    void run(async () => {
      go(
        await studentAuthCall<Destinations>('/api/student-auth/change-password', {
          email,
          current_password: password,
          new_password: newPassword
        })
      );
    });
  };

  if (choices) {
    return (
      <AuthCard title="בחירת קורס">
        {choices.length === 0 ? (
          <p className="text-[15px] text-ink-2">החשבון שלך עדיין לא משויך לקורס. פנו למרצה.</p>
        ) : (
          <div className="grid gap-2">
            {choices.map((c) => (
              <a key={c.course_id} href={c.url} className="rounded-md border border-border bg-paper px-4 py-3 text-[15px]">
                {c.name}
              </a>
            ))}
          </div>
        )}
      </AuthCard>
    );
  }

  const errorBox = error ? (
    <p role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-[14px] text-bad">
      {error}
    </p>
  ) : null;

  if (mode === 'forgot') {
    return (
      <AuthCard title="שכחתי סיסמה">
        <p className="text-[15px] leading-relaxed text-ink-2">
          פנו למרצה ובקשו לאפס את הסיסמה. אחרי האיפוס נכנסים שוב עם מספר תעודת הזהות ובוחרים סיסמה חדשה.
        </p>
        <button className="mt-4 text-[14px] text-forest underline" onClick={() => setMode('login')}>
          חזרה לכניסה
        </button>
      </AuthCard>
    );
  }

  if (mode === 'change') {
    return (
      <AuthCard title="בחירת סיסמה חדשה">
        <p className="mb-4 text-[14px] leading-relaxed text-ink-2">
          זו הכניסה הראשונה שלך. בחרו סיסמה אישית (לא מספר תעודת הזהות); מעכשיו נכנסים איתה.
        </p>
        <form onSubmit={change} className="grid gap-3">
          <Field label="סיסמה חדשה (לפחות 8 תווים)">
            <input dir="ltr" type="password" autoComplete="new-password" required value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)} className={inputClass} />
          </Field>
          <Field label="אימות סיסמה">
            <input dir="ltr" type="password" autoComplete="new-password" required value={confirm}
              onChange={(e) => setConfirm(e.target.value)} className={inputClass} />
          </Field>
          {errorBox}
          <SubmitButton busy={busy}>שמירה וכניסה</SubmitButton>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="כניסה לסטודנטים">
      <form onSubmit={login} className="grid gap-3">
        <Field label="דוא״ל">
          <input dir="ltr" type="email" autoComplete="username" required value={email}
            onChange={(e) => setEmail(e.target.value)} className={inputClass} />
        </Field>
        <Field label="סיסמה">
          <input dir="ltr" type="password" autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} className={inputClass} />
        </Field>
        <p className="text-[13px] text-ink-3">בכניסה הראשונה הסיסמה היא מספר תעודת הזהות שלך (9 ספרות).</p>
        {errorBox}
        <SubmitButton busy={busy}>כניסה</SubmitButton>
      </form>
      <button
        className="mt-4 text-[14px] text-forest underline"
        onClick={() => {
          setError(null);
          setMode('forgot');
        }}
      >
        שכחתי סיסמה
      </button>
    </AuthCard>
  );
}
