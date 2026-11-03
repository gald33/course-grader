'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';

/* Tabs inside one course page, kept in ?tab= beside ?section= so a tab can be
 * linked, refresh stays on it and back/forward move between tabs. The first
 * tab is the bare URL. */

function readTab<T extends string>(keys: readonly T[]): T {
  const v = new URLSearchParams(window.location.search).get('tab');
  return (keys as readonly string[]).includes(v ?? '') ? (v as T) : keys[0];
}

export function useUrlTab<T extends string>(keys: readonly T[]): [T, (t: T) => void] {
  const [tab, setTabState] = useState<T>(keys[0]);
  const keyList = keys.join('|');
  useEffect(() => {
    const list = keyList.split('|') as T[];
    const read = () => setTabState(readTab(list));
    read();
    window.addEventListener('popstate', read);
    return () => window.removeEventListener('popstate', read);
  }, [keyList]);
  const setTab = useCallback(
    (t: T) => {
      const url = new URL(window.location.href);
      if (t === keyList.split('|')[0]) url.searchParams.delete('tab');
      else url.searchParams.set('tab', t);
      if (url.href !== window.location.href) window.history.pushState(window.history.state, '', url);
      setTabState(t);
    },
    [keyList]
  );
  return [tab, setTab];
}

export function SubTabs<T extends string>({
  tabs,
  active,
  onChange,
  label
}: {
  tabs: readonly { key: T; label: string; badge?: ReactNode }[];
  active: T;
  onChange: (t: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 border-b border-border">
      {tabs.map((t) => {
        const on = t.key === active;
        return (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={on}
            onClick={() => onChange(t.key)}
            className={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-2 text-[14px] transition ${
              on ? 'border-forest font-medium text-ink' : 'border-transparent text-ink-3 hover:text-ink'
            }`}
          >
            {t.label}
            {t.badge != null ? <span className="nav-count tnum">{t.badge}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
