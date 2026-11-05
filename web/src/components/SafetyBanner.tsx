import { Info, Siren } from "lucide-react";

export function SafetyBanner({ variant = "info", children }:
  { variant?: "info" | "emergency" | "warning"; children: React.ReactNode }) {
  if (variant === "emergency") {
    return (
      <div role="alert" className="flex gap-3 rounded-xl border border-failed/50 bg-alarm-wash px-4 py-3 font-semibold text-failed">
        <Siren aria-hidden className="shrink-0" />
        <div>{children}</div>
      </div>
    );
  }
  const tone = variant === "warning" ? "border-waiting text-waiting" : "border-rule text-ink-soft";
  return (
    <div role="note" className={`flex gap-2 rounded-xl border-l-4 bg-card px-3.5 py-2.5 text-sm ${tone}`}>
      <Info aria-hidden size={18} className="mt-0.5 shrink-0" />
      <div>{children}</div>
    </div>
  );
}
