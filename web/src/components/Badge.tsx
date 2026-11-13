import { Lock } from "lucide-react";
import type { Classification, VersionStatus } from "../api/types";

const STATUS: Record<VersionStatus, [string, string]> = {
  PENDING_APPROVAL: ["Waiting for approval", "text-waiting bg-waiting/12"],
  REJECTED: ["Rejected", "text-failed bg-failed/12"],
  QUEUED: ["Queued", "text-working bg-working/12"],
  PROCESSING: ["Processing", "text-working bg-working/12"],
  READY: ["Ready", "text-ready bg-ready/12"],
  SUPERSEDED: ["Superseded", "text-past bg-past/12"],
  FAILED: ["Failed", "text-failed bg-failed/12"],
};

export function StatusBadge({ status }: { status: VersionStatus }) {
  const [label, tone] = STATUS[status] ?? [status, "text-ink bg-bubble"];
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${tone}`}>
      <span aria-hidden className={`size-1.5 rounded-full bg-current ${status === "PROCESSING" ? "animate-pulse" : ""}`} />
      {label}
    </span>
  );
}

const CLASS: Record<Classification, [string, string]> = {
  public: ["Public", "bg-bubble text-ink-soft"],
  internal: ["Internal", "bg-scrub/10 text-scrub-deep"],
  confidential: ["Confidential", "bg-waiting/12 text-waiting"],
  restricted: ["Restricted", "bg-failed/12 text-failed"],
};

export function ClassificationBadge({ value }: { value: Classification }) {
  const [label, tone] = CLASS[value];
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ${tone}`}>
      {value === "restricted" && <Lock aria-hidden size={12} />}
      {label}
    </span>
  );
}

/** The document-control stamp: the version is the visual anchor of every source (version safety is the promise). */
export function VersionStamp({ version, superseded = false }: { version: number; superseded?: boolean }) {
  return (
    <span
      aria-label={`Version ${version}`}
      className={`inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-md border-2 font-serif text-xl font-semibold ${
        superseded ? "border-past text-past line-through" : "border-scrub text-scrub-deep"}`}
    >
      v{version}
    </span>
  );
}

export function Chip({ children }: { children: React.ReactNode }) {
  return <span className="rounded bg-scrub-wash px-2 py-0.5 text-xs text-scrub-deep">{children}</span>;
}
