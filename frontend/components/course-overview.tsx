'use client';

import { useEffect, useState } from 'react';

import { apiGet } from '@/lib/api';
import { courseSectionHref, type CourseSection } from '@/lib/course-sections';

/* The course's landing page: only what needs the instructor now, each item a
 * link to the page that handles it, then a few figures. Every source is read
 * on its own; one that can't be read is named as "not checked", never shown
 * as zero. */

export type SubmissionCounts = {
  total: number;
  graded: number;
  missingFiles: number;
  readyToRun: number;
  noColabUrl: number;
  failed: number;
  flagged: number;
};

type KeyCount = { missing: string[] } | null;
type Lesson = { id: number; title: string; status: 'draft' | 'published' | 'archived'; draft_version: unknown; answer_keys?: { live: KeyCount } };
type Round = {
  number: number;
  kind: 'progress' | 'final';
  title: string;
  status: 'draft' | 'scheduling' | 'reviewing' | 'closed';
  selection_deadline: string | null;
  review_deadline: string | null;
  released_at: string | null;
};
type Teams = {
  settings: { teams_open: boolean; teams_locked: boolean; teams_deadline: string | null };
  students: { team_id: number | null; is_test?: boolean }[];
};
type Accounts = { configured: boolean; students: { email: string | null; has_account: boolean; is_test: boolean }[] };
type Releases = { components: { key: string; released: boolean }[] };

type Sources = {
  lessons?: Lesson[] | null;
  rounds?: Round[] | null;
  teams?: Teams | null;
  accounts?: Accounts | null;
  releases?: Releases | null;
};

type Item = { urgent: boolean; text: string; section: CourseSection; tab?: string; action: string };

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : null;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const roundName = (r: Round) => r.title || (r.kind === 'final' ? 'Final round' : `Round ${r.number}`);

function itemsFrom(students: number, subs: SubmissionCounts, s: Sources): Item[] {
  const out: Item[] = [];
  if (students === 0) {
    out.push({ urgent: true, text: 'No students yet. Upload the roster first; teams, accounts and grades all need it.', section: 'students', action: 'Upload roster' });
  }

  // Things students are waiting on.
  for (const r of s.rounds ?? []) {
    if (r.status === 'closed' && !r.released_at) {
      out.push({ urgent: true, text: `${roundName(r)} is closed, but its results aren't released to students.`, section: 'peer', action: 'Open peer review' });
    } else if (r.status === 'reviewing') {
      const by = day(r.review_deadline);
      out.push({ urgent: false, text: `${roundName(r)} is open for reviews${by ? ` until ${by}` : ''}.`, section: 'peer', tab: undefined, action: 'See participation' });
    } else if (r.status === 'scheduling') {
      const by = day(r.selection_deadline);
      out.push({ urgent: false, text: `${roundName(r)}: teams are picking presentation slots${by ? ` until ${by}` : ''}.`, section: 'peer', action: 'Open schedule' });
    }
  }
  for (const l of s.lessons ?? []) {
    const missing = l.status === 'published' ? l.answer_keys?.live?.missing.length ?? 0 : 0;
    if (missing > 0) {
      out.push({ urgent: true, text: `“${l.title}” is live, but ${plural(missing, 'question has', 'questions have')} no answer key, so students get no feedback on them.`, section: 'lessons', action: 'Load answer keys' });
    }
  }
  if (s.teams) {
    const unteamed = s.teams.students.filter((x) => !x.team_id && !x.is_test).length;
    if (unteamed > 0) {
      out.push(
        s.teams.settings.teams_locked
          ? { urgent: true, text: `${plural(unteamed, 'student has', 'students have')} no team, and teams are locked.`, section: 'teams', action: 'Place them' }
          : { urgent: false, text: `${plural(unteamed, 'student has', 'students have')} no team yet${s.teams.settings.teams_deadline ? ` (teams lock ${day(s.teams.settings.teams_deadline)})` : ''}.`, section: 'teams', action: 'Open teams' }
      );
    }
  }
  if (s.accounts?.configured) {
    const real = s.accounts.students.filter((x) => !x.is_test);
    const noAccount = real.filter((x) => x.email && !x.has_account).length;
    const noEmail = real.filter((x) => !x.email).length;
    if (noAccount > 0) out.push({ urgent: false, text: `${plural(noAccount, 'student has', 'students have')} no sign-in account yet.`, section: 'students', tab: 'accounts', action: 'Create accounts' });
    if (noEmail > 0) out.push({ urgent: false, text: `${plural(noEmail, 'student has', 'students have')} no email, so can't get an account.`, section: 'students', action: 'Fix the roster' });
  }

  // Grading work.
  if (subs.failed > 0) out.push({ urgent: true, text: `${plural(subs.failed, 'notebook run')} failed.`, section: 'queue', action: 'Open queue' });
  if (subs.missingFiles > 0) out.push({ urgent: false, text: `${plural(subs.missingFiles, 'submission is', 'submissions are')} missing files.`, section: 'queue', action: 'Open queue' });
  if (subs.noColabUrl > 0) out.push({ urgent: false, text: `${plural(subs.noColabUrl, 'submission has', 'submissions have')} no Colab URL to run.`, section: 'queue', action: 'Add URLs' });
  if (subs.readyToRun > 0) out.push({ urgent: false, text: `${plural(subs.readyToRun, 'submission is', 'submissions are')} ready to run.`, section: 'queue', action: 'Run them' });
  if (subs.flagged > 0) out.push({ urgent: false, text: `${plural(subs.flagged, 'submission has', 'submissions have')} an originality mismatch to look at.`, section: 'queue', action: 'Review' });
  const toGrade = subs.total - subs.graded;
  if (toGrade > 0) out.push({ urgent: false, text: `${plural(toGrade, 'submission')} still to grade.`, section: 'queue', action: 'Grade' });

  return out.sort((a, b) => Number(b.urgent) - Number(a.urgent));
}

export function CourseOverview({
  courseId,
  students,
  submissions,
  go
}: {
  courseId: number;
  students: number;
  submissions: SubmissionCounts;
  go: (section: CourseSection, tab?: string) => void;
}) {
  const [sources, setSources] = useState<Sources | null>(null);

  useEffect(() => {
    const base = `/api/courses/${courseId}`;
    const read = <T,>(path: string) => apiGet<T>(`${base}${path}`).catch(() => null);
    void Promise.all([
      read<Lesson[]>('/lessons'),
      read<{ rounds: Round[] }>('/peer/overview'),
      read<Teams>('/peer/teams'),
      read<Accounts>('/accounts'),
      read<Releases>('/grade-releases')
    ]).then(([lessons, peer, teams, accounts, releases]) =>
      setSources({ lessons, rounds: peer ? peer.rounds : null, teams, accounts, releases })
    );
  }, [courseId]);

  if (!sources) return <div className="pt-6 text-ink-3">Loading…</div>;

  const items = itemsFrom(students, submissions, sources);
  const unchecked = [
    sources.lessons == null && 'lessons',
    sources.rounds == null && 'peer review',
    sources.teams == null && 'teams',
    sources.accounts == null && 'sign-in accounts',
    sources.releases == null && 'grade releases'
  ].filter(Boolean) as string[];

  const live = sources.lessons?.filter((l) => l.status === 'published').length;
  const released = sources.releases?.components.filter((c) => c.released).length;
  const current = sources.rounds?.find((r) => r.status === 'reviewing' || r.status === 'scheduling');

  const link = (section: CourseSection, tab?: string) => ({
    href: courseSectionHref(courseId, section, tab),
    onClick: (e: React.MouseEvent) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      e.preventDefault();
      go(section, tab);
    }
  });

  return (
    <div className="grid gap-6 pt-6">
      <section aria-labelledby="needs-you" className="grid gap-2">
        <h2 id="needs-you" className="font-display text-[22px]">
          Needs your attention
        </h2>
        {items.length === 0 ? (
          <p className="rounded-lg border border-border bg-card px-5 py-4 text-[15px] text-ok">✓ Nothing needs you right now.</p>
        ) : (
          <ul className="divide-y divide-line-soft overflow-hidden rounded-lg border border-border bg-card shadow-soft">
            {items.map((it, i) => (
              <li key={i} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <span
                  aria-label={it.urgent ? 'Urgent' : undefined}
                  className={`inline-block h-2 w-2 shrink-0 rounded-full ${it.urgent ? 'bg-terracotta' : 'bg-ink-4'}`}
                />
                <span className="min-w-0 flex-1 text-[15px] text-ink">{it.text}</span>
                <a {...link(it.section, it.tab)} className="shrink-0 text-[14px] font-medium text-forest no-underline hover:underline">
                  {it.action} →
                </a>
              </li>
            ))}
          </ul>
        )}
        {unchecked.length ? <p className="text-[12px] text-ink-3">Not checked (couldn't be read): {unchecked.join(', ')}.</p> : null}
      </section>

      <section aria-labelledby="at-a-glance" className="grid gap-2">
        <h2 id="at-a-glance" className="font-display text-[22px]">
          At a glance
        </h2>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
          <Glance label="Students" value={String(students)} {...link('students')} />
          <Glance label="Graded" value={`${submissions.graded} of ${submissions.total}`} {...link('queue')} />
          <Glance label="Lessons live" value={live == null ? 'not checked' : `${live} of ${sources.lessons!.length}`} {...link('lessons', 'lessons')} />
          <Glance
            label="Peer review"
            value={sources.rounds == null ? 'not checked' : current ? `${roundName(current)}: ${current.status}` : sources.rounds.length ? 'no round open' : 'not set up'}
            {...link('peer')}
          />
          <Glance
            label="Grades released"
            value={released == null ? 'not checked' : `${released} of ${sources.releases!.components.length} parts`}
            {...link('gradebook', 'release')}
          />
        </div>
      </section>
    </div>
  );
}

function Glance({ label, value, href, onClick }: { label: string; value: string; href: string; onClick: (e: React.MouseEvent) => void }) {
  return (
    <a href={href} onClick={onClick} className="block rounded-lg border border-border bg-card px-4 py-3 text-ink no-underline shadow-soft transition hover:border-ink-4">
      <div className="label-eyebrow">{label}</div>
      <div className="mt-1 font-display text-[20px] leading-tight">{value}</div>
    </a>
  );
}
