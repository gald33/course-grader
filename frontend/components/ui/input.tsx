import * as React from 'react';

import { cn } from '@/lib/utils';

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={cn(
        'flex h-10 w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-ink outline-none transition-colors',
        'focus:border-forest focus:ring-2 focus:ring-forest-tint',
        className
      )}
      {...props}
    />
  );
});
Input.displayName = 'Input';

export { Input };
