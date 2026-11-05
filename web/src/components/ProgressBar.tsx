export function ProgressBar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}
         className="h-1.5 w-full overflow-hidden rounded-full bg-rule/70">
      <div className="h-full rounded-full bg-working transition-[width] duration-500" style={{ width: `${pct}%` }} />
    </div>
  );
}
