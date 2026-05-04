'use client';

type DotScaleProps = {
  value: number | null | undefined;
  onChange: (v: number) => void;
  size?: number;
};

const colorFor = (n: number) => {
  if (n <= 1) return 'var(--bad)';
  if (n <= 2) return 'var(--warn)';
  if (n <= 3) return '#d9a441'; // honey
  return 'var(--ok)';
};

export function DotScale({ value, onChange, size = 20 }: DotScaleProps) {
  return (
    <div
      className="inline-flex items-center gap-1 rounded outline-none focus-visible:ring-2 focus-visible:ring-forest"
      tabIndex={0}
      role="group"
      onKeyDown={(e) => {
        if (/^[0-5]$/.test(e.key)) {
          e.preventDefault();
          onChange(parseInt(e.key, 10));
        } else if (e.key === 'ArrowRight' && (value ?? -1) < 5) {
          e.preventDefault();
          onChange(Math.min(5, (value ?? -1) + 1));
        } else if (e.key === 'ArrowLeft' && (value ?? 0) > 0) {
          e.preventDefault();
          onChange(Math.max(0, (value ?? 1) - 1));
        }
      }}
    >
      {[0, 1, 2, 3, 4, 5].map((n) => {
        const filled = value != null && n <= value;
        const isActive = value === n;
        return (
          <button
            key={n}
            type="button"
            title={`Score ${n}`}
            onClick={() => onChange(n)}
            className="rounded-full p-0 transition-[background,box-shadow] duration-150"
            style={{
              width: size,
              height: size,
              border: 'none',
              cursor: 'pointer',
              background: filled ? colorFor(n) : 'transparent',
              boxShadow: isActive ? `0 0 0 2px var(--card), 0 0 0 3.5px var(--ink)` : 'none',
              outline: filled ? '1px solid transparent' : '1px solid var(--ink-4)',
              fontSize: 10,
              color: filled ? '#fff' : 'transparent',
              fontWeight: 600
            }}
          >
            {n}
          </button>
        );
      })}
    </div>
  );
}
