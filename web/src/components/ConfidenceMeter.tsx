import { ChevronDown } from "lucide-react";
import { useState } from "react";

const TONE = {
  High: ["text-ready", "bg-ready", "bg-ready/12"],
  Medium: ["text-waiting", "bg-waiting", "bg-waiting/12"],
  Low: ["text-failed", "bg-failed", "bg-failed/12"],
} as const;

export function ConfidenceMeter({ score, band, parts }:
  { score: number; band: "High" | "Medium" | "Low"; parts: { r: number; c: number; a: number } }) {
  const [open, setOpen] = useState(false);
  const [text, bar, wash] = TONE[band];
  return (
    <div className="rounded-2xl border border-rule bg-card p-4 shadow-sm">
      <div className="flex items-center gap-3">
        <span className={`text-2xl font-semibold tabular-nums tracking-tight ${text}`}>{score}</span>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${wash} ${text}`}>{band} confidence</span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-rule/70" aria-hidden>
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${score}%` }} />
      </div>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
              className="-ml-2 mt-2 inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-ink-soft hover:bg-bubble hover:text-ink">
        How this is scored
        <ChevronDown aria-hidden size={14} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-xs text-ink-soft">
          <dt>Retrieval strength (50%)</dt><dd className="tabular-nums text-ink">{parts.r.toFixed(2)}</dd>
          <dt>Citations verified (30%)</dt><dd className="tabular-nums text-ink">{parts.c.toFixed(2)}</dd>
          <dt>Sources agreeing (20%)</dt><dd className="tabular-nums text-ink">{parts.a.toFixed(2)}</dd>
        </dl>
      )}
    </div>
  );
}
