import * as React from 'react';

import { cn } from '@/lib/utils';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'outline' | 'soft' | 'warm' | 'ghost' | 'link';
  size?: 'default' | 'sm' | 'lg';
};

const variantClasses: Record<NonNullable<ButtonProps['variant']>, string> = {
  default: 'bg-forest text-paper font-semibold shadow-[inset_0_1px_0_rgba(255,255,255,0.3)] hover:bg-forest/90',
  soft: 'bg-forest-tint text-forest hover:bg-forest-soft',
  warm: 'bg-terracotta text-paper font-semibold shadow-[inset_0_1px_0_rgba(255,255,255,0.25)] hover:bg-terracotta/90',
  outline: 'border border-border bg-card text-ink shadow-soft hover:bg-paper-2 hover:border-ink-4',
  ghost: 'bg-transparent text-ink-2 hover:bg-paper-2 hover:text-ink',
  link: 'bg-transparent text-forest hover:underline px-1 py-0'
};

const sizeClasses: Record<NonNullable<ButtonProps['size']>, string> = {
  default: 'h-9 px-3.5 text-[13px]',
  sm: 'h-7 px-2.5 text-[12px]',
  lg: 'h-11 px-5 text-[14px]'
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center gap-2 rounded-[8px] font-medium transition disabled:cursor-not-allowed disabled:opacity-40 whitespace-nowrap',
          variantClasses[variant],
          sizeClasses[size],
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';
