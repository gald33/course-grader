// Detects whether a single name string contains Hebrew characters and renders
// it with the .he-name styling for that segment. Falls back to plain text.

const HEBREW_RE = /[֐-׿]/;

export function isHebrew(s: string): boolean {
  return HEBREW_RE.test(s);
}

export function BilingualName({ name, size = 13 }: { name: string; size?: number }) {
  const trimmed = (name || '').trim();
  if (!trimmed) return <span style={{ fontSize: size, color: 'var(--ink-3)' }}>—</span>;
  if (isHebrew(trimmed)) {
    return (
      <span className="he-name" style={{ fontSize: size + 1 }}>
        {trimmed}
      </span>
    );
  }
  return <span style={{ fontSize: size }}>{trimmed}</span>;
}

// When you have separate Hebrew + English strings, render them side by side.
export function NamePair({
  he,
  en,
  size = 13
}: {
  he?: string;
  en?: string;
  size?: number;
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      {he ? (
        <span className="he-name" style={{ fontSize: size + 1 }}>
          {he}
        </span>
      ) : null}
      {en ? (
        <span style={{ fontSize: size - 1, color: 'var(--ink-3)' }}>{en}</span>
      ) : null}
    </span>
  );
}
