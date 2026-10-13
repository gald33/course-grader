'use client';

import { usePathname } from 'next/navigation';
import { FormEvent, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { AUTH_REQUIRED_EVENT, apiFetch, setInstructorToken } from '@/lib/api';

/** Asks for the instructor token when the backend runs with INSTRUCTOR_TOKEN.
 * Without it (localhost-only setup) this never shows. Student pages (/r/…)
 * are skipped — they authenticate with their own link. */
export function InstructorAuthGate() {
  const pathname = usePathname();
  const isStudentPage = pathname?.startsWith('/r/') ?? false;
  const [needed, setNeeded] = useState(false);
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isStudentPage) return;
    const onRequired = () => setNeeded(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, onRequired);
    apiFetch('/api/auth/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (s?.required && !s.authenticated) setNeeded(true);
      })
      .catch(() => undefined);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onRequired);
  }, [isStudentPage]);

  if (isStudentPage || !needed) return null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const res = await apiFetch('/api/auth/instructor-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token.trim() })
    });
    if (!res.ok) {
      setError('That token was not accepted.');
      return;
    }
    setInstructorToken(token.trim());
    window.location.reload();
  };

  return (
    <div className="fixed inset-0 z-[100] grid place-items-center bg-ink/40 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-border bg-card p-6 shadow-lift">
        <div className="label-eyebrow mb-1">Instructor access</div>
        <h2 className="font-display text-[22px]">Enter instructor token</h2>
        <p className="mt-1 text-[13px] text-ink-3">
          This server is reachable by students, so instructor pages are locked with the <code>INSTRUCTOR_TOKEN</code>{' '}
          from the backend environment.
        </p>
        <Input
          className="mt-4"
          type="password"
          autoFocus
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="Instructor token"
        />
        {error ? <div className="mt-2 text-[13px] text-bad">{error}</div> : null}
        <div className="mt-4 flex justify-end">
          <Button type="submit" disabled={!token.trim()}>
            Unlock
          </Button>
        </div>
      </form>
    </div>
  );
}
