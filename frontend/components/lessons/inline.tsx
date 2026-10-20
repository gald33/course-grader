/* Inline lesson markup, rendered as React elements (never as HTML):
 *   **bold**      → <strong>
 *   `code`        → an LTR-isolated monospace identifier, formula or file name
 *   [[ltr text]]  → LTR-isolated text (English UI labels, URLs), not monospace
 * Anything else is plain text, so content JSON can't inject markup. An
 * unclosed backtick or [[ is shown as typed. */

import { Fragment } from 'react';

type Segment = { kind: 'text' | 'code' | 'ltr'; text: string; bold: boolean };

// A short LTR run (a menu label, an identifier) is kept on one line: split
// across lines inside Hebrew, its words would read out of order. Longer runs
// may still wrap so they never push the page sideways on a phone.
const NOWRAP_MAX = 28; // fits a file name like lesson2-customer-data.csv

export function parseInline(source: string): Segment[] {
  const out: Segment[] = [];
  let buf = '';
  let bold = false;
  const flush = () => {
    if (buf) out.push({ kind: 'text', text: buf, bold });
    buf = '';
  };
  let i = 0;
  while (i < source.length) {
    if (source.startsWith('**', i)) {
      flush();
      bold = !bold;
      i += 2;
      continue;
    }
    if (source[i] === '`') {
      const end = source.indexOf('`', i + 1);
      if (end > i) {
        flush();
        out.push({ kind: 'code', text: source.slice(i + 1, end), bold });
        i = end + 1;
        continue;
      }
    }
    if (source.startsWith('[[', i)) {
      const end = source.indexOf(']]', i + 2);
      if (end > i) {
        flush();
        out.push({ kind: 'ltr', text: source.slice(i + 2, end), bold });
        i = end + 2;
        continue;
      }
    }
    buf += source[i];
    i += 1;
  }
  flush();
  return out;
}

/** The text without markup, for aria-labels, titles and short summaries. */
export function plainInline(source: string): string {
  return parseInline(source)
    .map((s) => s.text)
    .join('');
}

export function InlineText({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return (
    <>
      {parseInline(text).map((s, i) => {
        const nowrap = s.text.length <= NOWRAP_MAX ? 'whitespace-nowrap' : 'break-words';
        const inner =
          s.kind === 'code' ? (
            <bdi dir="ltr" className={nowrap}>
              <code className="rounded bg-paper-2 px-1 py-px font-mono text-[0.9em]">{s.text}</code>
            </bdi>
          ) : s.kind === 'ltr' ? (
            <bdi dir="ltr" className={nowrap}>
              {s.text}
            </bdi>
          ) : (
            s.text
          );
        return <Fragment key={i}>{s.bold ? <strong className="font-semibold">{inner}</strong> : inner}</Fragment>;
      })}
    </>
  );
}

/** A list of Inline paragraphs. */
export function Paragraphs({ items, className = '' }: { items: string[] | undefined; className?: string }) {
  if (!items?.length) return null;
  return (
    <div className={`grid grid-cols-1 gap-2 leading-relaxed ${className}`}>
      {items.map((p, i) => (
        <p key={i}>
          <InlineText text={p} />
        </p>
      ))}
    </div>
  );
}

/** A number (or any identifier-like text) kept left-to-right inside Hebrew. */
export function Ltr({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <bdi dir="ltr" className={className}>
      {children}
    </bdi>
  );
}
