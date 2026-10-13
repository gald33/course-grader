'use client';

import { FormEvent, useEffect, useState } from 'react';

import { AuthCard, Field, SubmitButton, studentAuthCall, type Destinations } from '@/components/student-auth';

/* Student sign-in: email (as given to the college) + password chosen from
 * the invite email. Hebrew, RTL, phone-first. */

export default function StudentLoginPage() {
  const [mode, setMode] = useState<'login' | 'forgot' | 'sent'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [choices, setChoices] = useState<Destinations['courses'] | null>(null);

  const go = (d: Destinations) => {
    if (d.redirect) window.location.assign(d.redirect);
    else setChoices(d.courses);
  };

  useEffect(() => {
    if (new URLSearchParams(window.location.search).has('forgot')) setMode('forgot');
    // Already signed in: skip the form.
    studentAuthCall<Destinations>('/api/student-auth/me')
      .then(go)
      .catch(() => undefined);
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === 'forgot') {
        await studentAuthCall('/api/student-auth/forgot', { email });
        setMode('sent');
      } else {
        go(await studentAuthCall<Destinations>('/api/student-auth/login', { email, password }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
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

  if (mode === 'sent') {
    return (
      <AuthCard title="בדקו את תיבת הדואר">
        <p className="text-[15px] leading-relaxed text-ink-2">
          אם הכתובת רשומה בקורס, נשלח אליה קישור לבחירת סיסמה חדשה. הקישור בתוקף לזמן מוגבל.
        </p>
        <button className="mt-4 text-[14px] text-forest underline" onClick={() => setMode('login')}>
          חזרה לכניסה
        </button>
      </AuthCard>
    );
  }

  return (
    <AuthCard title={mode === 'forgot' ? 'איפוס סיסמה' : 'כניסה לסטודנטים'}>
      <form onSubmit={submit} className="grid gap-3">
        <Field label="דוא״ל">
          <input
            dir="ltr"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="h-11 w-full rounded-md border border-border bg-white px-3 text-left"
          />
        </Field>
        {mode === 'login' ? (
          <Field label="סיסמה">
            <input
              dir="ltr"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-11 w-full rounded-md border border-border bg-white px-3 text-left"
            />
          </Field>
        ) : (
          <p className="text-[14px] text-ink-3">נשלח אליך קישור לבחירת סיסמה חדשה.</p>
        )}
        {error ? (
          <p role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-[14px] text-bad">
            {error}
          </p>
        ) : null}
        <SubmitButton busy={busy}>{mode === 'forgot' ? 'שליחת קישור' : 'כניסה'}</SubmitButton>
      </form>
      <button
        className="mt-4 text-[14px] text-forest underline"
        onClick={() => {
          setError(null);
          setMode(mode === 'forgot' ? 'login' : 'forgot');
        }}
      >
        {mode === 'forgot' ? 'חזרה לכניסה' : 'שכחתי סיסמה'}
      </button>
    </AuthCard>
  );
}
