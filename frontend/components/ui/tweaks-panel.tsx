'use client';

import { ReactNode, useState } from 'react';

type TweaksPanelProps = {
  label?: string;
  children: ReactNode;
};

export function TweaksPanel({ label = 'Tweaks', children }: TweaksPanelProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="fixed bottom-6 right-6 z-40">
      {open ? (
        <div className="w-[280px] rounded-lg border border-border bg-card p-4 shadow-lift">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-display text-base">{label}</span>
            <button
              onClick={() => setOpen(false)}
              className="text-sm text-ink-3 hover:text-ink"
              aria-label="Close tweaks panel"
            >
              ×
            </button>
          </div>
          <div className="space-y-3">{children}</div>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="rounded-full border border-border bg-card px-3.5 py-2 text-sm text-ink-2 shadow-card hover:text-ink"
        >
          ⌥ {label}
        </button>
      )}
    </div>
  );
}

type TweakRadioProps<T extends string> = {
  label: string;
  hint?: string;
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
};

export function TweakRadio<T extends string>({ label, hint, value, onChange, options }: TweakRadioProps<T>) {
  return (
    <div>
      <div className="mb-1 text-[12px] font-medium text-ink-2">{label}</div>
      <div className="grid grid-flow-col gap-1 rounded-md border border-border bg-paper-2 p-1">
        {options.map((o) => {
          const selected = value === o.value;
          return (
            <button
              key={o.value}
              onClick={() => onChange(o.value)}
              className={`rounded px-2 py-1 text-[12px] transition ${
                selected ? 'bg-card text-ink shadow-soft' : 'text-ink-3 hover:text-ink'
              }`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
      {hint ? <div className="mt-1 text-[11px] text-ink-3">{hint}</div> : null}
    </div>
  );
}
