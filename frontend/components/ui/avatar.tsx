type AvatarProps = {
  name: string;
  size?: number;
  className?: string;
};

const PALETTE = [
  '#6b8a6e',
  '#a36b51',
  '#6b6e8a',
  '#8a6b6e',
  '#5d7a8a',
  '#8a8a6b',
  '#4f6b5d',
  '#a36b8a'
];

function deterministicColor(name: string) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

function initialsFor(name: string) {
  const parts = (name || '?').trim().split(/\s+/).slice(0, 2);
  return (
    parts
      .map((p) => p.replace(/[^A-Za-zא-ת]/, '')[0] || '')
      .join('')
      .toUpperCase() || '?'
  );
}

export function Avatar({ name, size = 30, className }: AvatarProps) {
  return (
    <div
      className={`grid place-items-center rounded-full font-semibold text-card ${className ?? ''}`}
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.4),
        background: deterministicColor(name),
        flex: 'none'
      }}
    >
      {initialsFor(name)}
    </div>
  );
}

export function AvatarStack({
  names,
  max = 3,
  size = 28
}: {
  names: string[];
  max?: number;
  size?: number;
}) {
  const shown = names.slice(0, max);
  const rest = names.length - shown.length;
  return (
    <div className="flex">
      {shown.map((n, i) => (
        <div key={i} style={{ marginLeft: i === 0 ? 0 : -8 }} className="rounded-full ring-2 ring-card">
          <Avatar name={n} size={size} />
        </div>
      ))}
      {rest > 0 ? (
        <div
          className="grid place-items-center rounded-full bg-paper-2 text-ink-2 ring-2 ring-card"
          style={{ width: size, height: size, fontSize: Math.round(size * 0.35), marginLeft: -8 }}
        >
          +{rest}
        </div>
      ) : null}
    </div>
  );
}
