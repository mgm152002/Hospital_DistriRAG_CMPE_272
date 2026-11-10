import { ClassificationBadge, StatusBadge, VersionStamp } from "../components/Badge";
import { Button } from "../components/Button";
import { ConfidenceMeter } from "../components/ConfidenceMeter";
import { GuardrailReceipt } from "../components/GuardrailReceipt";
import { ProgressBar } from "../components/ProgressBar";
import { SafetyBanner } from "../components/SafetyBanner";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { Stepper } from "../components/Stepper";

/** Every design-system component in every state (spec E10-2). */
export default function DesignPage() {
  return (
    <div className="max-w-4xl space-y-8 p-8">
      <h1 className="text-[1.6rem] font-semibold tracking-tight">Design system</h1>
      <section className="space-y-3">
        <h2 className="text-lg font-bold">Status and classification</h2>
        <div className="flex flex-wrap gap-2">
          {(["PENDING_APPROVAL", "QUEUED", "PROCESSING", "READY", "SUPERSEDED", "FAILED", "REJECTED"] as const)
            .map((s) => <StatusBadge key={s} status={s} />)}
        </div>
        <div className="flex flex-wrap gap-2">
          {(["public", "internal", "confidential", "restricted"] as const).map((c) => <ClassificationBadge key={c} value={c} />)}
        </div>
        <div className="flex gap-3"><VersionStamp version={2} /><VersionStamp version={1} superseded /></div>
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-bold">Actions</h2>
        <div className="flex gap-3"><Button>Approve</Button><Button variant="quiet">Cancel</Button>
          <Button variant="danger">Delete document</Button><Button disabled>Disabled</Button></div>
      </section>
      <section className="grid gap-4 md:grid-cols-3">
        <ConfidenceMeter score={86} band="High" parts={{ r: 0.9, c: 1, a: 1 }} />
        <ConfidenceMeter score={61} band="Medium" parts={{ r: 0.6, c: 0.7, a: 0.6 }} />
        <ConfidenceMeter score={32} band="Low" parts={{ r: 0.3, c: 0, a: 0 }} />
      </section>
      <GuardrailReceipt receipt={{ classification: "diagnostic_support", phi_redacted: true, provider: "local-ollama",
        model: "qwen2.5", external: false, egress_decision: "local", passages_withheld: {}, fallback: null,
        latency_ms: 742, cached: false, checks: { citations: "pass", clinical: "pass", injection: "pass" } }} />
      <section className="space-y-3">
        <SafetyBanner>Reference tool. Does not diagnose or replace clinical judgement.</SafetyBanner>
        <SafetyBanner variant="warning">We removed something that looked like patient information.</SafetyBanner>
        <SafetyBanner variant="emergency">If this is happening now, activate the Rapid Response / Code team per hospital procedure.</SafetyBanner>
      </section>
      <section className="space-y-3">
        <Stepper steps={["Queued", "Extract", "Chunk", "Embed", "Ready"]} current={3} />
        <ProgressBar value={24} max={40} label="Embedding" />
        <Skeleton />
        <EmptyState title="No approved documents match">Try different words or ask the assistant.</EmptyState>
        <ErrorState error={new Error("The database is unavailable. Try again shortly.")} />
      </section>
    </div>
  );
}
