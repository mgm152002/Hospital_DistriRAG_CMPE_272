import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { describeError } from "../copy/errors";

function Countdown({ seconds }: { seconds: number }) {
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  return <span>{left > 0 ? ` Try again in ${left} s.` : " You can try again now."}</span>;
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-rule bg-card/50 px-6 py-10 text-center">
      <p className="text-base font-semibold">{title}</p>
      {children && <p className="mt-1 text-sm text-ink-soft">{children}</p>}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  let message = error instanceof Error ? error.message : String(error);
  if (error instanceof ApiError) {
    message = error.status === 404 ? "This page or document doesn't exist, or your role can't see it."
      : error.status === 403 ? describeError("forbidden")
      : error.status >= 500 ? describeError(error.code) || "The service is having trouble. Try again shortly."
      : error.detail;
  }
  return (
    <div role="alert" className="rounded-xl border border-failed/30 bg-alarm-wash px-4 py-3 text-sm text-failed">
      {message}
      {error instanceof ApiError && error.status === 429 && <Countdown seconds={error.retryAfter ?? 5} />}
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading" className="space-y-2">
      {Array.from({ length: lines }, (_, i) => <div key={i} className="h-4 animate-pulse rounded-lg bg-rule/70" />)}
    </div>
  );
}
