'use client';

/* Renders lesson content blocks. Every Block type in types.ts has a case;
 * anything else renders nothing. Content is data: text goes through
 * InlineText (never as HTML), links point only at lesson assets, the student's
 * own course page, or the instructor-configured Colab URL. */

import { useEffect, useId, useRef, useState } from 'react';

import { CommitmentPanel } from '@/components/lessons/commitment';
import { ExperimentLog } from '@/components/lessons/experiments';
import { InlineText, Ltr, Paragraphs, plainInline } from '@/components/lessons/inline';
import type { LessonApi } from '@/components/lessons/lesson-player';
import { QuestionCard } from '@/components/lessons/questions';
import { LessonSummary } from '@/components/lessons/summary';
import { ActualTree, ManualTree, SplitIllustration } from '@/components/lessons/trees';
import type { Block, SectionLabel } from '@/components/lessons/types';

export function BlockList({ blocks, api }: { blocks: Block[]; api: LessonApi }) {
  return (
    <div className="grid grid-cols-1 gap-4">
      {blocks.map((b, i) => (
        <BlockView key={i} block={b} api={api} />
      ))}
    </div>
  );
}

function BlockView({ block, api }: { block: Block; api: LessonApi }) {
  switch (block.type) {
    case 'text':
      return <Paragraphs items={block.body} className="text-[15px]" />;
    case 'section':
      return <SectionBlock block={block} api={api} />;
    case 'callout':
      return <CalloutBlock block={block} />;
    case 'expander':
      return (
        <details className="rounded-lg border border-line-soft bg-paper-2 px-4 py-3">
          <summary className="cursor-pointer text-[15px] font-semibold text-forest">
            <InlineText text={block.title} />
          </summary>
          <div className="mt-3">
            <BlockList blocks={block.blocks} api={api} />
          </div>
        </details>
      );
    case 'list': {
      const items = block.items.map((item, i) => (
        <li key={i} className="ps-1">
          <InlineText text={item} />
        </li>
      ));
      return block.ordered ? (
        <ol className="grid grid-cols-1 list-decimal gap-1.5 ps-6 text-[15px] leading-relaxed">{items}</ol>
      ) : (
        <ul className="grid grid-cols-1 list-disc gap-1.5 ps-6 text-[15px] leading-relaxed">{items}</ul>
      );
    }
    case 'table':
      return <TableBlock block={block} />;
    case 'code':
      return <CodeBlock block={block} />;
    case 'download':
      return <DownloadBlock block={block} api={api} />;
    case 'prompt':
      return <PromptBlock block={block} />;
    case 'colab':
      return <ColabBlock block={block} api={api} />;
    case 'link':
      return <LinkBlock block={block} api={api} />;
    case 'manual_tree':
      return <ManualTree block={block} />;
    case 'split_illustration':
      return <SplitIllustration block={block} />;
    case 'actual_tree': {
      const asset = api.content.assets[block.asset];
      return <ActualTree block={block} path={asset?.path ?? null} assetLabel={asset?.label} />;
    }
    case 'question': {
      const q = api.content.questions[block.question];
      return q ? <QuestionCard question={q} api={api} /> : null;
    }
    case 'experiment_log':
      return <ExperimentLog block={block} api={api} />;
    case 'commitment':
      return <CommitmentPanel api={api} />;
    case 'summary':
      return <LessonSummary api={api} />;
    case 'ack':
      return <AckBlock block={block} api={api} />;
    default:
      return null;
  }
}

/* ---------------- Structure ---------------- */

const SECTION: Record<SectionLabel, { text: string; pill: string; border: string }> = {
  understand: { text: 'מבינים', pill: 'pill-forest', border: 'border-forest-soft' },
  try: { text: 'מנסים', pill: 'pill-terra', border: 'border-terracotta-soft' },
  check: { text: 'בודקים', pill: 'pill-info', border: 'border-info-soft' }
};

function SectionBlock({ block, api }: { block: Extract<Block, { type: 'section' }>; api: LessonApi }) {
  const id = useId();
  const s = SECTION[block.label] ?? SECTION.understand;
  return (
    <section aria-labelledby={id} className={`rounded-lg border bg-card p-4 shadow-soft ${s.border}`}>
      <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`pill ${s.pill} font-semibold`}>{s.text}</span>
        <h3 id={id} className="font-hebrew text-[19px] leading-snug">
          {block.title ? <InlineText text={block.title} /> : <span className="sr-only">{s.text}</span>}
        </h3>
      </div>
      <BlockList blocks={block.blocks} api={api} />
    </section>
  );
}

const CALLOUT = {
  info: { icon: 'i', box: 'border-info-soft bg-info-soft/40', icon_bg: 'bg-info', label: 'מידע' },
  warn: { icon: '!', box: 'border-warn-soft bg-warn-soft/40', icon_bg: 'bg-warn', label: 'שימו לב' },
  note: { icon: '✎', box: 'border-terracotta-soft bg-terracotta-tint', icon_bg: 'bg-terracotta', label: 'הערה' }
} as const;

function CalloutBlock({ block }: { block: Extract<Block, { type: 'callout' }> }) {
  const c = CALLOUT[block.tone] ?? CALLOUT.info;
  return (
    <aside role="note" aria-label={block.title ? plainInline(block.title) : c.label} className={`flex gap-3 rounded-lg border p-4 ${c.box}`}>
      <span aria-hidden className={`grid h-7 w-7 shrink-0 place-items-center rounded-full font-display text-[15px] text-paper ${c.icon_bg}`}>
        {c.icon}
      </span>
      <div className="min-w-0 text-[15px]">
        {block.title ? (
          <p className="mb-1 font-semibold">
            <InlineText text={block.title} />
          </p>
        ) : null}
        <Paragraphs items={block.body} />
      </div>
    </aside>
  );
}

function TableBlock({ block }: { block: Extract<Block, { type: 'table' }> }) {
  const id = useId();
  // A table of identifiers and numbers only reads in the file's own order.
  const allLtr = block.columns.length > 0 && block.columns.every((c) => c.ltr);
  return (
    <figure className="grid grid-cols-1 gap-1.5">
      {block.caption ? (
        <figcaption id={id} className="text-[14px] font-semibold text-ink-2">
          <InlineText text={block.caption} />
        </figcaption>
      ) : null}
      <div
        dir={allLtr ? 'ltr' : undefined}
        className="overflow-x-auto rounded-md border border-border bg-card"
        role="region"
        tabIndex={0}
        aria-label={block.caption ? plainInline(block.caption) : 'טבלה'}
      >
        <table dir={allLtr ? 'ltr' : undefined} aria-labelledby={block.caption ? id : undefined} className="w-full border-collapse text-[14px]">
          <thead>
            <tr>
              {block.columns.map((c, i) => (
                <th
                  key={i}
                  scope="col"
                  dir={c.ltr && !allLtr ? 'ltr' : undefined}
                  className="whitespace-nowrap bg-paper-2 px-3 py-2 text-start font-semibold"
                >
                  <InlineText text={c.label} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, r) => (
              <tr key={r} className="border-t border-line-soft">
                {row.map((cell, j) => (
                  <td
                    key={j}
                    dir={block.columns[j]?.ltr && !allLtr ? 'ltr' : undefined}
                    className={`px-3 py-2 align-top leading-relaxed ${block.columns[j]?.ltr ? 'tnum whitespace-nowrap' : ''}`}
                  >
                    <InlineText text={cell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}

function CodeBlock({ block }: { block: Extract<Block, { type: 'code' }> }) {
  const lines = block.code.replace(/\n$/, '').split('\n');
  const marked = new Set(block.highlight_lines ?? []);
  return (
    <figure className="grid grid-cols-1 gap-1.5">
      {block.caption ? (
        <figcaption className="text-[14px] text-ink-2">
          <InlineText text={block.caption} />
        </figcaption>
      ) : null}
      <pre
        dir="ltr"
        tabIndex={0}
        aria-label={block.caption ? plainInline(block.caption) : 'קוד'}
        className="relative overflow-x-auto rounded-md bg-ink py-3 text-[13px] leading-relaxed text-paper"
      >
        <code className="block min-w-max font-mono">
          {lines.map((line, i) => {
            const hl = marked.has(i + 1);
            return (
              <span key={i} className={`block pe-4 ${hl ? 'bg-honey/25 font-semibold' : ''}`}>
                <span aria-hidden className={`inline-block w-7 select-none text-center ${hl ? 'text-honey' : 'text-ink-3'}`}>
                  {hl ? '✎' : i + 1}
                </span>
                {line || ' '}
                {hl ? <span className="sr-only"> (שורה לעריכה)</span> : null}
              </span>
            );
          })}
        </code>
      </pre>
      {marked.size ? (
        <p className="text-[12px] text-ink-3">
          השורות שמסומנות ב-<span aria-hidden>✎</span> הן השורות שעורכים.
        </p>
      ) : null}
    </figure>
  );
}

/* ---------------- Assets, prompts, Colab, links ---------------- */

function DownloadBlock({ block, api }: { block: Extract<Block, { type: 'download' }>; api: LessonApi }) {
  const asset = api.content.assets[block.asset];
  if (!asset) return <p className="text-[14px] text-bad">הקובץ חסר בשיעור.</p>;
  return (
    <div className="grid grid-cols-1 gap-2 rounded-lg border border-border bg-card p-3">
      <a
        href={asset.path}
        download={asset.filename}
        className="inline-flex min-h-[44px] items-center gap-2 justify-self-start rounded-md bg-forest px-4 py-2 text-[15px] font-semibold text-paper"
      >
        <span aria-hidden>⬇</span>
        <InlineText text={block.label} />
      </a>
      <div className="text-[13px] leading-relaxed text-ink-2">
        <Ltr className="font-mono text-[12px]">{asset.filename}</Ltr>
        {block.description ? (
          <>
            {' '}
            · <InlineText text={block.description} />
          </>
        ) : null}
      </div>
    </div>
  );
}

/** Copy with the async Clipboard API, else a hidden textarea + execCommand. */
function legacyCopy(text: string): boolean {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.top = '0';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

function selectContents(el: HTMLElement | null) {
  if (!el) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel?.removeAllRanges();
  sel?.addRange(range);
}

const HEBREW = /[֐-׿]/;

function PromptBlock({ block }: { block: Extract<Block, { type: 'prompt' }> }) {
  const [status, setStatus] = useState<'idle' | 'copied' | 'manual'>('idle');
  const textRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (status !== 'copied') return;
    const t = window.setTimeout(() => setStatus('idle'), 5000);
    return () => window.clearTimeout(t);
  }, [status]);

  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('no clipboard');
      await navigator.clipboard.writeText(block.text);
      setStatus('copied');
    } catch {
      if (legacyCopy(block.text)) setStatus('copied');
      else {
        selectContents(textRef.current);
        setStatus('manual');
      }
    }
  };

  return (
    <section aria-labelledby={titleId} className="grid grid-cols-1 gap-2 rounded-lg border border-forest-soft bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 id={titleId} className="font-hebrew text-[16px]">
          <InlineText text={block.title} />
        </h4>
        <button
          type="button"
          onClick={copy}
          className="inline-flex h-10 items-center rounded-md border border-forest px-4 text-[14px] font-semibold text-forest hover:bg-forest-tint"
        >
          {status === 'copied' ? '✓ הועתק' : 'העתקת הבקשה'}
        </button>
      </div>
      <p aria-live="polite" className="min-h-[1.25em] text-[13px]">
        {status === 'copied' ? (
          <span className="text-ok">✓ הועתק. עכשיו הדביקו בשיחה עם הצ׳טבוט.</span>
        ) : status === 'manual' ? (
          <span className="text-warn">ההעתקה האוטומטית לא זמינה כאן. הטקסט סומן – העתיקו אותו ידנית (Ctrl+C, או ״העתקה״ בטלפון).</span>
        ) : null}
      </p>
      {/* Each line keeps its own direction: Hebrew lines RTL, code / CSV lines LTR. */}
      <div
        ref={textRef}
        role="region"
        tabIndex={0}
        aria-label={`הטקסט של ${plainInline(block.title)}`}
        className="max-h-80 overflow-y-auto rounded-md border border-line-soft bg-paper px-3 py-2 text-[14px] leading-relaxed"
      >
        {block.text.split('\n').map((line, i) => (
          <div
            key={i}
            dir={HEBREW.test(line) ? 'rtl' : 'ltr'}
            className={`min-h-[1.5em] whitespace-pre-wrap break-words ${HEBREW.test(line) ? '' : 'font-mono text-[13px]'}`}
          >
            {line}
          </div>
        ))}
      </div>
      {block.note ? (
        <p className="text-[13px] text-ink-2">
          <InlineText text={block.note} />
        </p>
      ) : null}
    </section>
  );
}

const COLAB_HOSTS = ['colab.research.google.com', 'drive.google.com'];

function safeColabUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && COLAB_HOSTS.includes(u.hostname) ? u.toString() : null;
  } catch {
    return null;
  }
}

function ColabBlock({ block, api }: { block: Extract<Block, { type: 'colab' }>; api: LessonApi }) {
  const notebook = api.content.assets[block.notebook_asset];
  const colab = safeColabUrl(api.colabUrl);
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className="grid grid-cols-1 gap-3 rounded-lg border border-info-soft bg-card p-4">
      <h4 id={titleId} className="font-hebrew text-[17px]">
        עובדים בקולאב{block.section ? <>: <InlineText text={block.section} /></> : null}
      </h4>
      {colab ? (
        <div className="grid grid-cols-1 gap-1.5">
          <a
            href={colab}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-[44px] items-center justify-self-start rounded-md bg-forest px-4 text-[15px] font-semibold text-paper"
          >
            פתיחה בקולאב ↗<span className="sr-only"> (נפתח בלשונית חדשה)</span>
          </a>
          <p className="text-[13px] text-ink-2">אם הכפתור לא נפתח, השתמשו בהורדה ובהעלאה שבהמשך.</p>
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-2">
        <p className="text-[14px] font-semibold">{colab ? 'או: הורדה והעלאה לקולאב' : 'פתיחת המחברת: הורדה והעלאה לקולאב'}</p>
        <ol className="grid grid-cols-1 list-decimal gap-1.5 ps-6 text-[15px] leading-relaxed">
          {block.instructions.map((item, i) => (
            <li key={i} className="ps-1">
              <InlineText text={item} />
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2">
          {notebook ? (
            <a
              href={notebook.path}
              download={notebook.filename}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-forest px-4 text-[14px] font-semibold text-forest hover:bg-forest-tint"
            >
              <span aria-hidden>⬇</span> הורדת המחברת
              <Ltr className="font-mono text-[12px] font-normal">{notebook.filename}</Ltr>
            </a>
          ) : (
            <span className="text-[14px] text-bad">קובץ המחברת חסר בשיעור.</span>
          )}
          <a
            href="https://colab.research.google.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-[44px] items-center gap-1 rounded-md border border-border bg-paper px-4 text-[14px]"
          >
            פתיחת <Ltr>colab.research.google.com</Ltr> ↗<span className="sr-only"> (נפתח בלשונית חדשה)</span>
          </a>
        </div>
      </div>
      <p role="note" className="flex items-start gap-2 rounded-md bg-forest-tint px-3 py-2 text-[15px] font-semibold text-forest">
        <span aria-hidden>↩</span>
        <span>
          <InlineText text={block.return_note} />
        </span>
      </p>
    </section>
  );
}

function LinkBlock({ block, api }: { block: Extract<Block, { type: 'link' }>; api: LessonApi }) {
  const peer = block.target === 'peer_review';
  const href = api.token ? (peer ? `/r/${api.token}` : `/r/${api.token}/lessons`) : null;
  return (
    <div className="grid grid-cols-1 gap-1 rounded-lg border border-border bg-card p-3">
      {href && !api.preview ? (
        <a
          href={href}
          target={peer ? '_blank' : undefined}
          rel={peer ? 'noopener noreferrer' : undefined}
          className="inline-flex min-h-[44px] items-center justify-self-start rounded-md border border-forest px-4 text-[15px] font-semibold text-forest hover:bg-forest-tint"
        >
          <InlineText text={block.label} />
          {peer ? (
            <>
              {' '}
              ↗<span className="sr-only"> (נפתח בלשונית חדשה)</span>
            </>
          ) : null}
        </a>
      ) : (
        <span className="text-[15px] font-semibold text-ink-3">
          <InlineText text={block.label} /> <span className="text-[13px] font-normal">(בתצוגה המקדימה הקישור לא פעיל)</span>
        </span>
      )}
      {block.description ? (
        <p className="text-[13px] text-ink-2">
          <InlineText text={block.description} />
        </p>
      ) : null}
    </div>
  );
}

/* ---------------- Self-reported actions ---------------- */

function AckBlock({ block, api }: { block: Extract<Block, { type: 'ack' }>; api: LessonApi }) {
  const id = useId();
  const checked = api.acked(block.key);
  const onServer = !!api.progress?.acks.includes(block.key);
  const unsaved = checked !== onServer;
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-start gap-3">
        <input
          id={id}
          type="checkbox"
          checked={checked}
          onChange={(e) => api.setAck(block.key, e.target.checked)}
          aria-describedby={block.description ? `${id}-desc` : undefined}
          className="mt-1 h-5 w-5 shrink-0 accent-forest"
        />
        <div className="min-w-0">
          <label htmlFor={id} className="cursor-pointer text-[15px] font-semibold">
            <InlineText text={block.label} />
          </label>
          <span className="ms-1 text-[12px] text-ink-3">(סימון עצמי)</span>
          {block.description ? (
            <p id={`${id}-desc`} className="text-[13px] text-ink-2">
              <InlineText text={block.description} />
            </p>
          ) : null}
        </div>
      </div>
      <p aria-live="polite" className="mt-1 min-h-[1.25em] ps-8 text-[12px]">
        {api.preview ? null : unsaved ? (
          api.saveFailed ? (
            <span className="text-bad">⚠ הסימון עוד לא נשמר – נשמר במכשיר וננסה שוב</span>
          ) : (
            <span className="text-ink-3">שומר…</span>
          )
        ) : onServer ? (
          <span className="text-ok">✓ נשמר</span>
        ) : null}
      </p>
    </div>
  );
}
