import { Check, X } from "lucide-react";

/** Numbered steps joined by a line; finished steps show a tick.
 *  Labels never truncate: connectors flex to fill the space, and on narrow
 *  screens only the current step keeps a visible label. */
export function Stepper({ steps, current, failed = false }: { steps: string[]; current: number; failed?: boolean }) {
  return (
    <ol className="flex w-full items-center gap-2 text-xs">
      {steps.map((step, i) => {
        const state = i < current ? "done" : i === current ? "current" : "todo";
        const dot = state === "done" ? "btn-primary"
          : state === "current" ? (failed ? "bg-failed text-white" : "border-2 border-scrub bg-scrub-wash text-scrub-deep")
          : "border border-rule bg-card text-ink-soft";
        return (
          <li key={step} aria-current={state === "current" ? "step" : undefined}
              className={`flex items-center gap-2 ${i < steps.length - 1 ? "flex-1" : "shrink-0"}`}>
            <span className={`grid size-6 shrink-0 place-items-center rounded-full text-[0.7rem] font-semibold ${dot}`}>
              {state === "done" ? <Check aria-hidden size={13} strokeWidth={3} />
                : state === "current" && failed ? <X aria-hidden size={13} strokeWidth={3} /> : i + 1}
            </span>
            <span className={`whitespace-nowrap font-medium ${state === "todo" ? "text-ink-soft" : "text-ink"} ${state === "current" ? "" : "max-sm:sr-only"}`}>{step}</span>
            {i < steps.length - 1 && (
              <span aria-hidden className={`mx-1 h-px min-w-3 flex-1 ${i < current ? "bg-scrub" : "bg-rule"}`} />
            )}
          </li>
        );
      })}
    </ol>
  );
}
