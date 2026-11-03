import * as React from 'react';

import { cn } from '@/lib/utils';

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={cn(
        'flex h-9 w-full rounded-[8px] border border-border bg-card px-3 py-2 text-[13px] text-ink outline-none transition-colors placeholder:text-ink-3',
        'focus:border-forest/60 focus:ring-2 focus:ring-forest/20',
        className
      )}
      {...props}
    />
  );
});
Input.displayName = 'Input';

export { Input };
