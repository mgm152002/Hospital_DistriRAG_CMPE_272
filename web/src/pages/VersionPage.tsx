import { useQuery } from "@tanstack/react-query";
import { FileText, Upload } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { VersionStatus } from "../api/types";
import { StatusBadge } from "../components/Badge";
import { ProgressBar } from "../components/ProgressBar";
import { ErrorState, Skeleton } from "../components/States";
import { Stepper } from "../components/Stepper";
import { describeError } from "../copy/errors";

interface Status { version_id: string; document_id: string; title: string; version_number: number; status: VersionStatus;
  stage: string | null; chunks_total: number; chunks_embedded: number; error_code: string | null; error: string | null }

const STEPS = ["Approval", "Queued", "Extract", "Chunk", "Embed", "Finalize", "Ready"];
function stepIndex(s: Status) {
  if (s.status === "PENDING_APPROVAL" || s.status === "REJECTED") return 0;
  if (s.status === "QUEUED") return 1;
  if (s.status === "READY" || s.status === "SUPERSEDED") return 6;
  return { EXTRACT: 2, CHUNK: 3, EMBED: 4, FINALIZE: 5 }[s.stage ?? "EXTRACT"] ?? 2;
}

export default function VersionPage() {
  const { versionId } = useParams();
  const status = useQuery({
    queryKey: ["status", versionId], queryFn: () => api<Status>(`/api/versions/${versionId}/status`),
    refetchInterval: (q) => (["READY", "FAILED", "REJECTED", "SUPERSEDED"].includes(q.state.data?.status ?? "") ? false : 1500),
  });
  if (status.error) return <ErrorState error={status.error} />;
  if (!status.data) return <Skeleton />;
  const s = status.data;
  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h1 className="text-[1.6rem] font-semibold tracking-tight">{s.title}, version {s.version_number}</h1>
        <div className="mt-2"><StatusBadge status={s.status} /></div>
      </div>
      <section className="space-y-4 rounded-2xl border border-rule bg-card p-5 shadow-sm">
        <h2 className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Progress</h2>
        <Stepper steps={STEPS} current={stepIndex(s)} failed={s.status === "FAILED"} />
        {s.stage === "EMBED" && s.chunks_total > 0 && (
          <div><p className="mb-1.5 text-sm tabular-nums text-ink-soft">{s.chunks_embedded} of {s.chunks_total} chunks embedded</p>
            <ProgressBar value={s.chunks_embedded} max={s.chunks_total} label="Embedding" /></div>
        )}
      </section>
      {s.status === "FAILED" && <div role="alert" className="rounded-xl border border-failed/30 bg-alarm-wash px-4 py-3 text-sm text-failed">
        <p className="font-semibold">{describeError(s.error_code)}</p>{s.error && <p className="mt-1 text-xs">{s.error}</p>}</div>}
      <div className="flex flex-wrap gap-2">
        {s.status === "READY" && <Link className="btn-primary inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold"
          to={`/documents/${s.document_id}?version=${s.version_id}`}><FileText aria-hidden size={16} />Open the document</Link>}
        <Link className="inline-flex items-center gap-2 rounded-xl border border-rule bg-card px-3.5 py-2 text-sm font-medium hover:bg-bubble"
          to={`/library/${s.document_id}/new-version`}><Upload aria-hidden size={16} />Upload a new version</Link>
      </div>
    </div>
  );
}
