'use client';

import type { ReactNode } from 'react';

/** One line saying what a page is for, with the long explanation folded away
 * behind "How this works". The explanation is for a first visit, not for every
 * visit, so it starts closed. */
export function HowItWorks({ summary, children }: { summary: ReactNode; children?: ReactNode }) {
  if (!children) {
    return <p className="text-[14px] text-ink-2">{summary}</p>;
  }
  return (
    <details className="group text-[14px] text-ink-2">
      <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2 [&::-webkit-details-marker]:hidden">
        <span>{summary}</span>
        <span className="text-[13px] text-forest hover:underline">
          <span className="group-open:hidden">How this works ▸</span>
          <span className="hidden group-open:inline">Hide ▾</span>
        </span>
      </summary>
      <div className="mt-2 max-w-3xl rounded-md border border-line-soft bg-card px-4 py-3 text-[13px] leading-relaxed text-ink-2">
        {children}
      </div>
    </details>
  );
}
