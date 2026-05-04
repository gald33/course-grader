import * as React from 'react';

import { cn } from '@/lib/utils';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'outline' | 'soft' | 'warm' | 'ghost' | 'link';
  size?: 'default' | 'sm' | 'lg';
};

const variantClasses: Record<NonNullable<ButtonProps['variant']>, string> = {
  default: 'bg-forest text-paper hover:bg-[#244c41]',
  soft: 'bg-forest-tint text-forest hover:bg-forest-soft',
  warm: 'bg-terracotta text-card hover:bg-[#b86846]',
  outline: 'border border-border bg-card text-ink hover:bg-paper-2 hover:border-ink-4',
  ghost: 'bg-transparent text-ink-2 hover:bg-paper-2 hover:text-ink',
  link: 'bg-transparent text-forest hover:underline px-1 py-0'
};

const sizeClasses: Record<NonNullable<ButtonProps['size']>, string> = {
  default: 'px-3.5 py-2 text-sm',
  sm: 'px-2.5 py-1 text-[13px]',
  lg: 'px-5 py-3 text-[15px]'
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center gap-2 rounded-md font-medium transition disabled:cursor-not-allowed disabled:opacity-40 whitespace-nowrap',
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
