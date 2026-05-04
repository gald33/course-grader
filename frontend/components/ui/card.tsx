import { cn } from '@/lib/utils';

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-card text-ink shadow-soft',
        'p-[22px]',
        className
      )}
      {...props}
    />
  );
}
