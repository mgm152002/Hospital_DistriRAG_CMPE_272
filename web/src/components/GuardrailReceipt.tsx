import { Check, ChevronDown, ShieldAlert, ShieldCheck } from "lucide-react";
import type { Receipt } from "../api/types";

const LABELS: Record<string, string> = {
  policy_lookup: "Policy lookup", clinical_reference: "Clinical reference", diagnostic_support: "Diagnostic support",
  diagnosis_request: "Diagnosis request (declined)", patient_order: "Patient-specific order (declined)",
  emergency: "Emergency", out_of_scope: "Out of scope",
};

function lines(r: Receipt): [boolean, string][] {
  const out: [boolean, string][] = [[true, `Question type: ${LABELS[r.classification ?? ""] ?? "Unknown"}`]];
  out.push([!r.phi_redacted, r.phi_redacted ? "Patient-identifying details removed before processing"
                                            : "No patient-identifying details found"]);
  out.push([r.checks.injection === "pass", r.checks.injection === "pass" ? "No injected instructions in sources"
                                                                          : "Prompt-injection text removed from a source"]);
  if (r.checks.citations !== "n/a") out.push([r.checks.citations === "pass", `Citations: ${r.checks.citations}`]);
  if (r.checks.clinical !== "n/a") out.push([r.checks.clinical === "pass", r.checks.clinical === "pass"
    ? "No diagnosis or patient-specific order in the answer" : "Answer blocked: it stated a diagnosis or order"]);
  const withheld = Object.entries(r.passages_withheld).map(([k, n]) => `${n} ${k}`).join(", ");
  if (withheld) out.push([false, `Withheld from external provider: ${withheld}`]);
  out.push([true, r.external ? `Answered by ${r.provider} (external, policy-checked)`
                             : r.provider === "none" ? "No model configured; passages only"
                             : "Answered by local model; nothing left the network"]);
  if (r.cached) out.push([true, "Served from the answer cache"]);
  return out;
}

export function GuardrailReceipt({ receipt }: { receipt: Receipt }) {
  const concerns = lines(receipt).filter(([ok]) => !ok).length;
  return (
    <details className="group rounded-2xl border border-rule bg-card px-4 py-3 text-sm shadow-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold [&::-webkit-details-marker]:hidden">
        <ShieldCheck aria-hidden size={16} className="shrink-0 text-scrub" />Guardrail receipt{" "}
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${concerns === 0 ? "bg-ready/12 text-ready" : "bg-waiting/12 text-waiting"}`}>
          {concerns === 0 ? "all checks passed" : `${concerns} to note`}
        </span>
        <ChevronDown aria-hidden size={14} className="ml-auto text-ink-soft transition-transform group-open:rotate-180" />
      </summary>
      <ul className="mt-3 space-y-1.5 border-t border-rule pt-3">
        {lines(receipt).map(([ok, text]) => (
          <li key={text} className="flex gap-2">
            {ok ? <Check aria-hidden size={16} className="mt-0.5 shrink-0 text-ready" />
                : <ShieldAlert aria-hidden size={16} className="mt-0.5 shrink-0 text-waiting" />}
            <span>{text}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs tabular-nums text-ink-soft">{receipt.latency_ms} ms</p>
    </details>
  );
}
