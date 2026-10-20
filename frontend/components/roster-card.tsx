'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';

import { BilingualName } from '@/components/ui/bilingual-name';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { apiGet, apiPatch, apiPost, errorMessage } from '@/lib/api';

type RosterRow = {
  student_id: number;
  national_id: string;
  name: string;
  email: string | null;
  has_account: boolean;
  is_test: boolean;
  withdrawn_at: string | null;
  team_name: string | null;
};

const EMPTY = { national_id: '', name: '', email: '' };

/** Add, fix, withdraw or reinstate one student without re-importing the roster. */
export function RosterCard({
  courseId,
  setToast,
  refresh
}: {
  courseId: number;
  setToast: (m: string) => void;
  refresh: () => Promise<void>;
}) {
  const base = `/api/courses/${courseId}/students`;
  const [rows, setRows] = useState<RosterRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(EMPTY);
  const [editing, setEditing] = useState<{ id: number; name: string; email: string } | null>(null);
  const [filter, setFilter] = useState('');

  const load = useCallback(async () => setRows(await apiGet<RosterRow[]>(base)), [base]);
  useEffect(() => {
    void load().catch((e) => setToast(errorMessage(e)));
  }, [load, setToast]);

  const act = async (fn: () => Promise<string>) => {
    setBusy(true);
    try {
      setToast(await fn());
      await Promise.all([load(), refresh()]);
      return true;
    } catch (e) {
      setToast(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    const ok = await act(async () => {
      await apiPost(base, { ...adding, email: adding.email.trim() || null });
      return `${adding.name.trim()} added`;
    });
    if (ok) setAdding(EMPTY);
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    const ok = await act(async () => {
      await apiPatch(`${base}/${editing.id}`, { name: editing.name, email: editing.email.trim() || null });
      return 'Student updated';
    });
    if (ok) setEditing(null);
  };

  const withdraw = (s: RosterRow) => {
    if (
      !window.confirm(
        `Withdraw ${s.name}? They are kept for history but leave their team${s.team_name ? ` (${s.team_name})` : ''}, ` +
          'owe no more reviews and drop out of the gradebook. You can reinstate them later.'
      )
    )
      return;
    void act(async () => {
      await apiPost(`${base}/${s.student_id}/withdraw`);
      return `${s.name} withdrawn`;
    });
  };

  const reinstate = (s: RosterRow) =>
    void act(async () => {
      await apiPost(`${base}/${s.student_id}/reinstate`);
      return `${s.name} reinstated — put them on a team in Peer review`;
    });

  if (!rows) return null;
  const q = filter.trim().toLowerCase();
  const shown = rows.filter(
    (s) => !q || s.name.toLowerCase().includes(q) || s.national_id.includes(q) || (s.email ?? '').includes(q)
  );
  const withdrawn = rows.filter((s) => s.withdrawn_at).length;

  return (
    <Card className="grid gap-3">
      <div>
        <div className="font-display text-lg">Students</div>
        <div className="text-[13px] leading-relaxed text-ink-3">
          {rows.length - withdrawn} enrolled{withdrawn ? ` · ${withdrawn} withdrawn` : ''}. Add a late student, fix a name
          or email (students sign in with it), or withdraw someone — no re-import needed. A name or email fix applies in
          every course the student is in.
        </div>
      </div>

      <form onSubmit={add} className="grid gap-2" style={{ gridTemplateColumns: '140px 1fr 1fr auto' }}>
        <Input
          required
          placeholder="ID number"
          value={adding.national_id}
          onChange={(e) => setAdding({ ...adding, national_id: e.target.value })}
          className="h-9"
        />
        <Input
          required
          placeholder="Name"
          value={adding.name}
          onChange={(e) => setAdding({ ...adding, name: e.target.value })}
          className="h-9"
        />
        <Input
          type="email"
          placeholder="Email (optional)"
          value={adding.email}
          onChange={(e) => setAdding({ ...adding, email: e.target.value })}
          className="h-9"
        />
        <Button type="submit" size="sm" disabled={busy}>
          Add student
        </Button>
      </form>

      <details>
        <summary className="cursor-pointer text-[13px] text-ink-2">Edit or withdraw a student</summary>
        <Input
          placeholder="Search by name, ID or email"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="mt-2 h-9"
        />
        <div className="mt-2 max-h-[420px] overflow-auto">
          <table className="w-full border-collapse text-[13px]">
            <tbody>
              {shown.map((s) =>
                editing?.id === s.student_id ? (
                  <tr key={s.student_id} className="border-b border-line-soft last:border-b-0">
                    <td colSpan={5} className="py-1.5">
                      <form onSubmit={save} className="flex items-center gap-2">
                        <span className="w-[100px] font-mono text-[12px] text-ink-3">{s.national_id}</span>
                        <Input
                          required
                          value={editing.name}
                          onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                          className="h-8"
                        />
                        <Input
                          type="email"
                          placeholder="Email"
                          value={editing.email}
                          onChange={(e) => setEditing({ ...editing, email: e.target.value })}
                          className="h-8"
                        />
                        <Button type="submit" size="sm" disabled={busy}>
                          Save
                        </Button>
                        <button type="button" className="text-ink-3 hover:underline" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </form>
                      {s.has_account ? (
                        <div className="mt-1 text-[12px] text-ink-3">
                          This student has an account: changing the email changes their sign-in address too.
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ) : (
                  <tr
                    key={s.student_id}
                    className={`border-b border-line-soft last:border-b-0 ${s.withdrawn_at ? 'text-ink-3' : ''}`}
                  >
                    <td className="py-1.5 pr-3">
                      <BilingualName name={s.name} />
                    </td>
                    <td className="py-1.5 pr-3 font-mono text-[12px] text-ink-3">{s.national_id}</td>
                    <td className="py-1.5 pr-3 font-mono text-[12px] text-ink-3">{s.email ?? '—'}</td>
                    <td className="py-1.5 pr-3">
                      {s.withdrawn_at ? (
                        <span className="pill pill-warn">withdrawn {new Date(s.withdrawn_at).toLocaleDateString()}</span>
                      ) : s.is_test ? (
                        <span className="pill pill-info">test student</span>
                      ) : (
                        <span className="text-ink-3">{s.team_name ?? 'no team'}</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap py-1.5 text-right">
                      <button
                        className="text-forest hover:underline"
                        disabled={busy}
                        onClick={() => setEditing({ id: s.student_id, name: s.name, email: s.email ?? '' })}
                      >
                        Edit
                      </button>
                      {' · '}
                      {s.withdrawn_at ? (
                        <button className="text-forest hover:underline" disabled={busy} onClick={() => reinstate(s)}>
                          Reinstate
                        </button>
                      ) : (
                        <button className="text-terracotta hover:underline" disabled={busy} onClick={() => withdraw(s)}>
                          Withdraw
                        </button>
                      )}
                    </td>
                  </tr>
                )
              )}
            </tbody>
          </table>
        </div>
      </details>
    </Card>
  );
}
