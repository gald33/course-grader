'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';

import { AuthCard, Field, SubmitButton, studentAuthCall, type Destinations } from '@/components/student-auth';

/* Landing page for the invite and password-reset emails. Supabase redirects
 * here with the session in the URL fragment (#access_token=…&type=invite);
 * the student chooses a password and is signed in. */

type LinkState = { token: string; type: string } | { error: string } | null;

function readLink(): LinkState {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  if (params.get('error') || params.get('error_description')) {
    return { error: params.get('error_code') ?? params.get('error') ?? 'error' };
  }
  const token = params.get('access_token');
  return token ? { token, type: params.get('type') ?? 'invite' } : null;
}

export default function AuthCallbackPage() {
  const [link, setLink] = useState<LinkState | undefined>(undefined);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Read the fragment once: effects can run twice (React strict mode), and
  // the second run would find the address bar already cleaned.
  const captured = useRef<LinkState | undefined>(undefined);

  useEffect(() => {
    if (captured.current === undefined) {
      captured.current = readLink();
      // Keep the one-time token out of the address bar and browser history.
      window.history.replaceState(null, '', window.location.pathname);
    }
    setLink(captured.current);
  }, []);

  if (link === undefined) return <AuthCard title="רגע…">{null}</AuthCard>;

  if (link === null || 'error' in link) {
    return (
      <AuthCard title="הקישור אינו בתוקף">
        <p className="text-[15px] leading-relaxed text-ink-2">
          הקישור פג תוקף או שכבר נעשה בו שימוש. אפשר לבקש קישור חדש לבחירת סיסמה.
        </p>
        <a href="/login?forgot=1" className="mt-4 inline-block text-[14px] text-forest underline">
          שליחת קישור חדש
        </a>
      </AuthCard>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password.length < 8) return setError('הסיסמה צריכה לכלול לפחות 8 תווים.');
    if (password !== confirm) return setError('הסיסמאות אינן תואמות.');
    setBusy(true);
    setError(null);
    try {
      const d = await studentAuthCall<Destinations>('/api/student-auth/set-password', {
        access_token: link.token,
        password
      });
      window.location.assign(d.redirect ?? '/login');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <AuthCard title={link.type === 'recovery' ? 'בחירת סיסמה חדשה' : 'ברוכים הבאים! בחרו סיסמה'}>
      <p className="mb-4 text-[14px] leading-relaxed text-ink-2">
        מעכשיו נכנסים עם כתובת הדוא״ל והסיסמה שתבחרו כאן.
      </p>
      <form onSubmit={submit} className="grid gap-3">
        <Field label="סיסמה (לפחות 8 תווים)">
          <input
            dir="ltr"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="h-11 w-full rounded-md border border-border bg-white px-3 text-left"
          />
        </Field>
        <Field label="אימות סיסמה">
          <input
            dir="ltr"
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="h-11 w-full rounded-md border border-border bg-white px-3 text-left"
          />
        </Field>
        {error ? (
          <p role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-[14px] text-bad">
            {error}
          </p>
        ) : null}
        <SubmitButton busy={busy}>שמירה וכניסה</SubmitButton>
      </form>
    </AuthCard>
  );
}
