'use client';

import { useEffect, useState } from 'react';

import { apiBase, apiFetch } from '@/lib/api';

type Artifact = {
  id: number;
  kind: string;
  filename: string;
  mime_type: string | null;
  size_bytes: number;
};

const KIND_LABEL: Record<string, string> = {
  project_report_pdf: 'Report PDF',
  submission_file: 'Submission file',
  code_file: 'Code',
  data_file: 'Data',
  snapshot_ipynb: 'Snapshot notebook',
  executed_html: 'Executed HTML',
  executed_notebook: 'Executed notebook',
  executed_ipynb: 'Executed notebook',
  run_logs: 'Run log',
  log: 'Run log',
  originality_pdf: 'Originality PDF'
};

export const PRIMARY_KINDS = new Set([
  'submission_file',
  'project_report_pdf',
  'code_file',
  'snapshot_ipynb'
]);
export const AUXILIARY_KINDS = new Set(['data_file']);

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fileIcon(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  if (ext === 'pdf') return '📄';
  if (ext === 'docx' || ext === 'doc') return '📝';
  if (ext === 'ipynb') return '📓';
  if (ext === 'csv' || ext === 'tsv') return '🗒';
  if (ext === 'xlsx' || ext === 'xls') return '🟩';
  if (ext === 'pptx' || ext === 'ppt') return '🟧';
  if (ext === 'zip') return '🗜';
  return '📎';
}

function ext(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? '';
}

/** Pick the file the grader most likely wants to read, in priority order. */
export function pickPrimary(artifacts: Artifact[]): Artifact | null {
  if (artifacts.length === 0) return null;
  // Restrict to "primary" submission artifacts — auxiliary data files shouldn't
  // hijack the main viewer.
  const primaries = artifacts.filter((a) => PRIMARY_KINDS.has(a.kind));
  const pool = primaries.length > 0 ? primaries : artifacts;
  const prio = ['pdf', 'docx', 'doc', 'ipynb', 'pptx', 'xlsx', 'csv', 'txt', 'md', 'html'];
  const reportPdf = pool.find((a) => a.kind === 'project_report_pdf');
  if (reportPdf) return reportPdf;
  for (const e of prio) {
    const found = pool.find((a) => ext(a.filename) === e);
    if (found) return found;
  }
  return pool[0];
}

/** Inline file viewer that adapts to file type — PDF embed, DOCX via mammoth, IPYNB cells, fallback hero. */
export function FileViewer({ artifact }: { artifact: Artifact }) {
  const e = ext(artifact.filename);
  let body: JSX.Element;
  if (e === 'pdf') body = <PdfView artifact={artifact} />;
  else if (e === 'docx') body = <DocxView artifact={artifact} />;
  else if (e === 'ipynb') body = <NotebookView artifact={artifact} />;
  else if (e === 'html') body = <HtmlView artifact={artifact} />;
  else if (e === 'png' || e === 'jpg' || e === 'jpeg' || e === 'gif' || e === 'webp') body = <ImageView artifact={artifact} />;
  else if (e === 'csv' || e === 'tsv' || e === 'txt' || e === 'md') body = <TextView artifact={artifact} />;
  else body = <DownloadHero artifact={artifact} />;

  return (
    <div className="flex h-full flex-col">
      <FileHeader artifact={artifact} />
      <div className="min-h-0 flex-1 overflow-hidden">{body}</div>
    </div>
  );
}

function FileHeader({ artifact }: { artifact: Artifact }) {
  const e = ext(artifact.filename);
  return (
    <div
      className="flex items-center gap-2.5 border-b border-border bg-paper-2/60 px-3.5 py-2"
      style={{ minHeight: 40 }}
    >
      <span aria-hidden className="text-base">
        {fileIcon(artifact.filename)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5">
          <span className="truncate text-[13px] font-medium text-ink" title={artifact.filename}>
            {artifact.filename}
          </span>
          {e ? (
            <span className="rounded border border-border bg-card px-1.5 py-px text-[10px] font-medium uppercase tracking-wider text-ink-3">
              .{e}
            </span>
          ) : null}
        </div>
        <div className="text-[11px] text-ink-3">
          {KIND_LABEL[artifact.kind] || artifact.kind} · {formatBytes(artifact.size_bytes)}
        </div>
      </div>
      <a
        href={`${apiBase()}/api/artifacts/${artifact.id}?inline=1`}
        target="_blank"
        rel="noreferrer"
        className="rounded-md border border-border bg-card px-2 py-1 text-[12px] text-ink-2 hover:border-ink-4 hover:text-ink"
        title="Open in new tab"
      >
        Open ↗
      </a>
      <a
        href={`${apiBase()}/api/artifacts/${artifact.id}`}
        download={artifact.filename}
        className="rounded-md bg-forest px-2.5 py-1 text-[12px] font-medium text-paper hover:bg-[#244c41]"
        title={`Download ${artifact.filename}`}
      >
        ⬇ Download
      </a>
    </div>
  );
}

function PdfView({ artifact }: { artifact: Artifact }) {
  const url = `${apiBase()}/api/artifacts/${artifact.id}?inline=1`;
  return (
    <iframe
      title={artifact.filename}
      src={url}
      className="h-full w-full bg-white"
      style={{ border: 'none' }}
    />
  );
}

function ImageView({ artifact }: { artifact: Artifact }) {
  const url = `${apiBase()}/api/artifacts/${artifact.id}?inline=1`;
  return (
    <div className="grid h-full w-full place-items-center bg-paper-2 p-4">
      <img alt={artifact.filename} src={url} className="max-h-full max-w-full object-contain" />
    </div>
  );
}

function HtmlView({ artifact }: { artifact: Artifact }) {
  const url = `${apiBase()}/api/artifacts/${artifact.id}?inline=1`;
  return (
    <iframe
      title={artifact.filename}
      sandbox="allow-same-origin"
      src={url}
      className="h-full w-full bg-white"
      style={{ border: 'none' }}
    />
  );
}

function TextView({ artifact }: { artifact: Artifact }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/artifacts/${artifact.id}?inline=1`)
      .then((r) => r.text())
      .then((t) => {
        if (!cancelled) setText(t);
      })
      .catch(() => setText('— failed to load —'));
    return () => {
      cancelled = true;
    };
  }, [artifact.id]);

  // Detect RTL (Hebrew/Arabic) so we render plain text the way it was written.
  const isRtl = !!text && /[֐-׿؀-ۿ]/.test(text.slice(0, 400));
  const e = ext(artifact.filename);
  const isCsvLike = e === 'csv' || e === 'tsv';

  if (text != null && isCsvLike) {
    return <CsvTableView text={text} delimiter={e === 'tsv' ? '\t' : ','} />;
  }

  return (
    <div className="h-full overflow-auto bg-white">
      <div
        className="mx-auto max-w-[820px] px-10 py-8"
        style={{
          fontFamily: e === 'md' ? 'Newsreader, Georgia, serif' : 'var(--font-mono)',
          fontSize: 13.5,
          lineHeight: 1.65,
          color: 'var(--ink)',
          direction: isRtl ? 'rtl' : 'ltr',
          textAlign: isRtl ? 'right' : 'left'
        }}
      >
        <pre className="whitespace-pre-wrap" style={{ fontFamily: 'inherit' }}>
          {text ?? 'Loading…'}
        </pre>
      </div>
    </div>
  );
}

function CsvTableView({ text, delimiter }: { text: string; delimiter: string }) {
  // Lightweight, quote-aware CSV parser — fine for grading-time previews.
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        field += ch;
      }
    } else {
      if (ch === '"') inQuotes = true;
      else if (ch === delimiter) {
        row.push(field);
        field = '';
      } else if (ch === '\n') {
        row.push(field);
        rows.push(row);
        row = [];
        field = '';
      } else if (ch === '\r') {
        // skip
      } else field += ch;
    }
  }
  if (field !== '' || row.length) {
    row.push(field);
    rows.push(row);
  }
  if (rows.length === 0) return <div className="p-6 text-ink-3">empty</div>;
  const [header, ...body] = rows;
  const truncated = body.length > 200;
  const visible = body.slice(0, 200);
  return (
    <div className="h-full overflow-auto bg-white">
      <div className="px-6 py-4 text-[11px] uppercase tracking-wider text-ink-3">
        {body.length} rows × {header.length} columns
        {truncated ? <span className="ml-2 text-warn">· showing first 200</span> : null}
      </div>
      <table className="w-full border-collapse text-[12.5px]">
        <thead>
          <tr className="bg-paper-2">
            {header.map((h, i) => (
              <th
                key={i}
                className="border border-border px-2 py-1.5 text-left font-medium"
                style={{ position: 'sticky', top: 0, background: 'var(--paper-2)' }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((r, i) => (
            <tr key={i} className={i % 2 ? 'bg-paper-2/40' : ''}>
              {r.map((cell, j) => (
                <td key={j} className="border border-border px-2 py-1 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DocxView({ artifact }: { artifact: Artifact }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setHtml(null);
    setError(null);
    (async () => {
      try {
        const res = await apiFetch(`/api/artifacts/${artifact.id}?inline=1`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buf = await res.arrayBuffer();
        // Dynamic import so mammoth only ships when needed
        const mammoth = (await import('mammoth')).default;
        const { value } = await mammoth.convertToHtml({ arrayBuffer: buf });
        if (!cancelled) setHtml(value);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || 'Failed to render');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [artifact.id]);

  if (error) {
    return (
      <div className="grid h-full place-items-center p-6 text-center">
        <div>
          <div className="font-display text-lg text-ink">Couldn't render this Word document</div>
          <div className="mt-1 text-sm text-ink-3">{error}</div>
          <a
            className="mt-3 inline-block text-forest underline"
            href={`${apiBase()}/api/artifacts/${artifact.id}`}
            download={artifact.filename}
          >
            Download {artifact.filename}
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-white">
      <div
        className="docx-render mx-auto max-w-[760px] px-12 py-10"
        style={{
          fontFamily: 'Newsreader, Georgia, serif',
          fontSize: 15,
          lineHeight: 1.6,
          color: 'var(--ink)',
          direction: 'rtl',
          textAlign: 'right'
        }}
        // Mammoth output is sanitized by mammoth itself (it whitelists tags)
        dangerouslySetInnerHTML={{ __html: html ?? '<p style="color: var(--ink-3)">Rendering…</p>' }}
      />
    </div>
  );
}

type NotebookCell = {
  cell_type: 'markdown' | 'code' | string;
  source: string | string[];
  outputs?: Array<{ output_type: string; text?: string | string[]; data?: Record<string, unknown> }>;
};

function NotebookView({ artifact }: { artifact: Artifact }) {
  const [cells, setCells] = useState<NotebookCell[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setCells(null);
    setError(null);
    apiFetch(`/api/artifacts/${artifact.id}?inline=1`)
      .then((r) => r.text())
      .then((txt) => {
        const parsed = JSON.parse(txt);
        if (!cancelled) setCells(parsed.cells || []);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [artifact.id]);

  if (error) {
    return (
      <div className="grid h-full place-items-center p-6 text-center">
        <div>
          <div className="font-display text-lg text-ink">Couldn't read this notebook</div>
          <div className="mt-1 text-sm text-ink-3">{error}</div>
        </div>
      </div>
    );
  }
  if (!cells) {
    return <div className="grid h-full place-items-center text-ink-3">Loading notebook…</div>;
  }

  const sourceOf = (s: string | string[]) => (Array.isArray(s) ? s.join('') : s);

  return (
    <div className="h-full overflow-auto bg-white p-6 font-mono text-[13px]">
      {cells.map((c, i) => {
        const src = sourceOf(c.source);
        if (c.cell_type === 'markdown') {
          return (
            <div
              key={i}
              className="mb-4 leading-relaxed"
              style={{ fontFamily: 'var(--font-display)', fontSize: 14 }}
            >
              {src.split('\n').map((line, j) => {
                if (line.startsWith('# ')) return <h2 key={j} className="text-xl font-semibold mt-2 mb-2">{line.slice(2)}</h2>;
                if (line.startsWith('## ')) return <h3 key={j} className="text-base font-semibold mt-2 mb-1">{line.slice(3)}</h3>;
                if (!line.trim()) return <div key={j} className="h-2" />;
                return <p key={j} style={{ fontFamily: 'var(--font-sans)' }}>{line}</p>;
              })}
            </div>
          );
        }
        // code cell
        return (
          <div key={i} className="mb-4">
            <div className="flex">
              <div className="w-10 flex-none pr-2 pt-3 text-right text-[11px] text-ink-4">In [{i}]</div>
              <pre className="flex-1 whitespace-pre-wrap rounded bg-paper-2 p-3 text-[12.5px]">{src}</pre>
            </div>
            {(c.outputs ?? []).map((o, k) => {
              const txt = sourceOf(o.text ?? '');
              if (!txt) return null;
              return (
                <div key={k} className="flex">
                  <div className="w-10 flex-none" />
                  <pre className="flex-1 whitespace-pre-wrap p-2 text-[12.5px] text-ink-2">{txt}</pre>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function DownloadHero({ artifact }: { artifact: Artifact }) {
  return (
    <div className="grid h-full place-items-center bg-paper-2/40 p-8 text-center">
      <div className="max-w-md">
        <div className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl bg-card text-3xl shadow-soft">
          {fileIcon(artifact.filename)}
        </div>
        <div className="font-display text-lg text-ink">{artifact.filename}</div>
        <div className="mt-1 text-sm text-ink-3">
          {KIND_LABEL[artifact.kind] || artifact.kind} · {formatBytes(artifact.size_bytes)}
        </div>
        <div className="mt-4 flex justify-center gap-2">
          <a
            className="inline-flex items-center justify-center rounded-md bg-forest px-3.5 py-2 text-sm font-medium text-paper transition hover:bg-[#244c41]"
            href={`${apiBase()}/api/artifacts/${artifact.id}`}
            download={artifact.filename}
          >
            ⬇ Download
          </a>
          <a
            className="inline-flex items-center justify-center rounded-md border border-border bg-card px-3.5 py-2 text-sm text-ink-2 hover:border-ink-4 hover:text-ink"
            href={`${apiBase()}/api/artifacts/${artifact.id}?inline=1`}
            target="_blank"
            rel="noreferrer"
          >
            Open ↗
          </a>
        </div>
      </div>
    </div>
  );
}

export function ArtifactList({ artifacts, primaryId }: { artifacts: Artifact[]; primaryId?: number }) {
  return (
    <div className="grid gap-2">
      {artifacts.map((a) => (
        <div
          key={a.id}
          className={`grid items-center gap-3 rounded-md border border-border p-3 ${
            a.id === primaryId ? 'bg-forest-tint' : 'bg-paper-2/40'
          }`}
          style={{ gridTemplateColumns: '32px 1fr auto auto' }}
        >
          <span className="text-xl" aria-hidden>
            {fileIcon(a.filename)}
          </span>
          <div className="min-w-0">
            <div className="truncate text-[14px] text-ink" title={a.filename}>
              {a.filename}
            </div>
            <div className="text-[11px] text-ink-3">
              {KIND_LABEL[a.kind] || a.kind} · {formatBytes(a.size_bytes)}
              {a.id === primaryId ? ' · primary' : ''}
            </div>
          </div>
          <a
            className="text-[13px] text-forest hover:underline"
            href={`${apiBase()}/api/artifacts/${a.id}?inline=1`}
            target="_blank"
            rel="noreferrer"
          >
            Open
          </a>
          <a
            className="text-[13px] text-forest hover:underline"
            href={`${apiBase()}/api/artifacts/${a.id}`}
            download={a.filename}
          >
            Download
          </a>
        </div>
      ))}
    </div>
  );
}
