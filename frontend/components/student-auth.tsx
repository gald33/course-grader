'use client';

/* Shared pieces of the student sign-in pages (Hebrew, RTL). Calls go to
 * /api/student-auth/* on the same origin (proxied to the backend), so the
 * login cookie is first-party. */

export type Destinations = {
  name: string;
  courses: { course_id: number; name: string; url: string }[];
  redirect: string | null;
};

const ERRORS: Record<string, string> = {
  invalid_credentials: 'כתובת הדוא״ל או הסיסמה שגויים.',
  not_enrolled: 'החשבון הזה לא רשום באף קורס. פנו למרצה.',
  weak_password: 'הסיסמה חלשה מדי. בחרו סיסמה ארוכה יותר.',
  link_expired: 'הקישור פג תוקף או שכבר נעשה בו שימוש. בקשו קישור חדש.',
  not_configured: 'הכניסה לחשבונות עדיין לא הופעלה. פנו למרצה.'
};

export async function studentAuthCall<T = unknown>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      cache: 'no-store'
    });
  } catch {
    throw new Error('אין חיבור לשרת. נסו שוב.');
  }
  if (!res.ok) {
    let code = '';
    try {
      code = (await res.json())?.detail?.code ?? '';
    } catch {
      /* not JSON */
    }
    throw new Error(ERRORS[code] ?? 'משהו השתבש. נסו שוב.');
  }
  return res.json();
}

export function AuthCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div dir="rtl" lang="he" className="min-h-screen">
      <main className="mx-auto w-full max-w-[420px] px-4 pt-16">
        <div className="rounded-lg border border-border bg-card p-6 shadow-card">
          <h1 className="font-hebrew text-[24px] leading-tight">{title}</h1>
          <div className="mt-4">{children}</div>
        </div>
      </main>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1 text-[14px]">
      <span className="font-semibold">{label}</span>
      {children}
    </label>
  );
}

export function SubmitButton({ busy, children }: { busy: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="h-11 rounded-md bg-forest px-5 text-[15px] font-semibold text-paper disabled:opacity-50"
    >
      {busy ? '…' : children}
    </button>
  );
}
