const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

const TOKEN_KEY = 'cg-instructor-token';
export const AUTH_REQUIRED_EVENT = 'cg:auth-required';

export function getInstructorToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setInstructorToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

/** fetch() against the backend with the instructor credentials attached.
 * Only matters when the backend sets INSTRUCTOR_TOKEN; otherwise a no-op. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getInstructorToken();
  if (token) headers.set('X-Instructor-Token', token);
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: 'include' });
  if (res.status === 401 && typeof window !== 'undefined') {
    window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
  }
  return res;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function apiGet<T>(path: string): Promise<T> {
  return jsonOrThrow<T>(await apiFetch(path, { cache: 'no-store' }));
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return jsonOrThrow<T>(
    await apiFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined
    })
  );
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return jsonOrThrow<T>(
    await apiFetch(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
  );
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return jsonOrThrow<T>(
    await apiFetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
  );
}

export async function apiDelete<T>(path: string): Promise<T> {
  return jsonOrThrow<T>(await apiFetch(path, { method: 'DELETE' }));
}

export function apiBase(): string {
  return API_BASE;
}

/** Pull a readable message out of a FastAPI error body. */
export function errorMessage(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(raw);
    const detail = parsed?.detail;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return detail.message;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  } catch {
    /* not JSON */
  }
  return raw;
}
