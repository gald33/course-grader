type AvatarProps = {
  name: string;
  size?: number;
  className?: string;
};

const PALETTE = [
  '#3f3f46',
  '#52525b',
  '#334155',
  '#44403c',
  '#1e3a5f',
  '#3b2f4a',
  '#14532d',
  '#4a2c2a'
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
      className={`grid place-items-center rounded-full font-medium text-ink ring-2 ring-paper ${className ?? ''}`}
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
