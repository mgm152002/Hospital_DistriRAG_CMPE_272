import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, postJson, streamPipeline } from "../api/client";
import type { BoardCard, OpsEvent, StreamStat } from "../api/types";
import { useSession } from "../app/session";
import { Button } from "../components/Button";
import { ProgressBar } from "../components/ProgressBar";
import { ErrorState } from "../components/States";
import { useToast } from "../components/Toast";
import { describeError } from "../copy/errors";

const COLUMNS = ["Waiting approval", "Queued", "Extracting", "Chunking", "Embedding", "Ready", "Failed"] as const;

function column(card: BoardCard): (typeof COLUMNS)[number] | null {
  switch (card.status) {
    case "PENDING_APPROVAL": return "Waiting approval";
    case "QUEUED": return "Queued";
    case "READY": return "Ready";
    case "FAILED": return "Failed";
    case "PROCESSING":
      return card.stage === "EXTRACT" ? "Extracting" : card.stage === "CHUNK" ? "Chunking" : "Embedding";
    default: return null;
  }
}

function useBoard() {
  const [cards, setCards] = useState<Record<string, BoardCard>>({});
  useEffect(() => {
    const abort = new AbortController();
    (async () => {
      try {
        for await (const { event, data } of streamPipeline(abort.signal)) {
          if (event === "version") setCards((all) => ({ ...all, [data.version_id]: data }));
        }
      } catch { /* stream closed */ }
    })();
    return () => abort.abort();
  }, []);
  return Object.values(cards);
}

const DOT: Record<(typeof COLUMNS)[number], string> = {
  "Waiting approval": "bg-waiting", Queued: "bg-working", Extracting: "bg-working", Chunking: "bg-working",
  Embedding: "bg-working", Ready: "bg-ready", Failed: "bg-failed",
};

function Board() {
  const cards = useBoard();
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
      {COLUMNS.map((name) => {
        const items = cards.filter((c) => column(c) === name)
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 8);
        return (
          <section key={name} aria-label={name} className="min-h-32 rounded-2xl bg-rail/60 p-2">
            <h3 className="mb-2 flex items-center justify-between px-1.5 pt-0.5 text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">
              <span className="flex items-center gap-1.5">
                <span aria-hidden className={`size-1.5 rounded-full ${DOT[name]}`} />{name}
              </span>
              <span className="rounded-full bg-card px-1.5 tabular-nums">{items.length}</span>
            </h3>
            <ul className="space-y-2">
              {items.map((c) => (
                <li key={c.version_id} className="rounded-xl border border-rule bg-card p-2.5 text-xs shadow-sm transition-colors hover:border-scrub/40">
                  <Link to={`/versions/${c.version_id}`} className="font-medium text-ink hover:text-scrub">{`${c.title} v${c.version_number}`}</Link>
                  {name === "Embedding" && c.chunks_total > 0 && (
                    <div className="mt-2"><ProgressBar value={c.chunks_embedded} max={c.chunks_total} label={`${c.title} embedding`} />
                      <p className="mt-1 tabular-nums text-ink-soft">{c.chunks_embedded}/{c.chunks_total}</p></div>
                  )}
                  {name === "Failed" && <p className="mt-1 text-failed">{describeError(c.error_code)}</p>}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function Streams() {
  const stats = useQuery({ queryKey: ["streams"], refetchInterval: 2000,
    queryFn: () => api<{ streams: StreamStat[]; outbox_unpublished: number }>("/api/ops/streams") });
  if (stats.error) return <ErrorState error={stats.error} />;
  if (!stats.data) return null;
  return (
    <section aria-labelledby="streams" className="space-y-3">
      <h2 id="streams" className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Streams</h2>
      <div className="flex flex-wrap gap-3 text-sm">
      {stats.data.streams.map((s) => (
        <div key={s.stream} className="min-w-44 rounded-2xl border border-rule bg-card px-4 py-3 shadow-sm">
          <p className="font-mono text-xs font-semibold">{s.stream}</p>
          <p className={`mt-1 tabular-nums ${s.pending ? "text-waiting" : "text-ink-soft"}`}>{s.pending} pending</p>
          {s.dlq > 0 && <p className="text-failed">{s.dlq} dead-lettered</p>}
          {s.consumers.map((c) => <p key={c.name} className="text-xs text-ink-soft">{c.name}, idle {Math.round(c.idle_ms / 1000)} s</p>)}
        </div>
      ))}
      <div className="min-w-44 rounded-2xl border border-rule bg-card px-4 py-3 shadow-sm">
        <p className="font-mono text-xs font-semibold">Outbox</p><p className="mt-1 tabular-nums text-ink-soft">{stats.data.outbox_unpublished} unpublished</p>
      </div>
      </div>
    </section>
  );
}

const DRILLS = [
  ["kill-worker", "Kill a worker", "The next embedding worker dies after committing and before acknowledging. Another worker reclaims the message."],
  ["restart-redis", "Restart Redis", "Redis shuts down and restarts. Its append-only file keeps every pending message."],
  ["poison-file", "Upload malformed file", "A scanned PDF is uploaded and approved. It must fail clearly, without retries."],
  ["provider-outage", "Provider outage", "Embeddings and answers fail for 30 seconds. Work retries; chat falls back to passages."],
] as const;

function describe(e: OpsEvent): string {
  const d = e.detail as Record<string, any>;
  switch (e.kind) {
    case "worker.killed": return `Worker ${d.consumer} killed before acknowledging its message`;
    case "message.reclaimed": return `Message reclaimed by ${d.to} after ${Math.round(d.idle_ms / 1000)} s (delivery ${d.delivery})`;
    case "version.ready": return `Version ready with ${d.chunks} chunks`;
    case "version.failed": return `Version failed: ${describeError(d.error_code)}`;
    case "dead_lettered": return `Moved to the dead-letter stream after ${d.deliveries} deliveries`;
    case "redriven": return "Stuck version re-queued from Postgres";
    case "stage.started": return `Stage ${d.stage} started on ${d.consumer}`;
    case "stage.progress": return `Embedded ${d.embedded}/${d.total} on ${d.consumer}`;
    default: return e.kind.startsWith("drill.") ? `Drill started: ${e.kind.slice(6)}` : e.kind;
  }
}

function Verify({ versionId }: { versionId: string }) {
  const status = useQuery({ queryKey: ["status", versionId], refetchInterval: 2000,
    queryFn: () => api<{ status: string; chunks_total: number; chunks_embedded: number }>(`/api/versions/${versionId}/status`) });
  if (status.data?.status !== "READY") return null;
  const { chunks_total: total, chunks_embedded: stored } = status.data;
  return <p className="rounded-xl bg-ready/12 px-4 py-2.5 text-sm font-semibold text-ready">
    {`${stored} of ${total} chunks stored, 0 duplicates, ${total - stored} lost`}</p>;
}

function Drills() {
  const [armed, setArmed] = useState<string | null>(null);
  const [since, setSince] = useState<number | null>(null);
  const toast = useToast();
  const start = useRef<number>(0);
  const run = useMutation({
    mutationFn: (name: string) => postJson(`/api/ops/drills/${name}`, {}),
    onSuccess: (_, name) => { toast(`Drill started: ${name}`); setSince(start.current); setArmed(null); },
  });
  const events = useQuery({ queryKey: ["ops-events", since], enabled: since !== null, refetchInterval: 1500,
    queryFn: () => api<OpsEvent[]>(`/api/ops/events?since=${since}`) });
  const baseline = useQuery({ queryKey: ["ops-baseline"], queryFn: () => api<OpsEvent[]>("/api/ops/events?since=0") });
  useEffect(() => { start.current = baseline.data?.length ? baseline.data[baseline.data.length - 1].id : 0; }, [baseline.data]);
  const interesting = (events.data ?? []).filter((e) => !["stage.progress", "stage.done"].includes(e.kind));
  const readyVersion = interesting.find((e) => e.kind === "version.ready" && e.version_id)?.version_id;
  return (
    <section aria-labelledby="drills" className="space-y-3">
      <h2 id="drills" className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Recovery drills</h2>
      <div className="grid gap-3 md:grid-cols-2">
        {DRILLS.map(([name, label, text]) => (
          <div key={name} className="flex items-start justify-between gap-4 rounded-2xl border border-rule bg-card p-4 shadow-sm">
            <p className="text-xs leading-relaxed text-ink-soft">{text}</p>
            <Button variant="quiet" className="shrink-0 rounded-xl" onClick={() => setArmed(name)}>{label}</Button>
          </div>
        ))}
      </div>
      {armed && (
        <div role="dialog" aria-label="Confirm drill" className="pop rounded-2xl border border-waiting/40 bg-waiting/12 p-4 text-sm">
          <p>Run “{DRILLS.find((d) => d[0] === armed)?.[1]}” now? It affects the live demo system.</p>
          <div className="mt-3 flex gap-2"><Button className="rounded-xl" onClick={() => run.mutate(armed)}>Run drill</Button>
            <Button variant="quiet" className="rounded-xl" onClick={() => setArmed(null)}>Cancel</Button></div>
        </div>
      )}
      {since !== null && (
        <div className="space-y-2">
          <ol aria-label="Recovery timeline" className="space-y-1.5 rounded-2xl border border-rule bg-card p-5 text-sm shadow-sm">
            {interesting.map((e) => (
              <li key={e.id} className="flex gap-3"><span className="shrink-0 tabular-nums text-ink-soft">{e.created_at ? new Date(e.created_at).toLocaleTimeString() : ""}</span>{" "}{describe(e)}</li>
            ))}
            {!interesting.length && <li className="text-ink-soft">Waiting for events…</li>}
          </ol>
          {readyVersion && <Verify versionId={readyVersion} />}
        </div>
      )}
    </section>
  );
}

function DeadLetters() {
  const client = useQueryClient();
  const letters = useQuery({ queryKey: ["dlq"], refetchInterval: 4000, queryFn: () => api<any[]>("/api/ops/dead-letters") });
  const replay = useMutation({ mutationFn: (id: number) => postJson(`/api/ops/dead-letters/${id}/replay`, {}),
                               onSuccess: () => client.invalidateQueries({ queryKey: ["dlq"] }) });
  if (!letters.data?.length) return null;
  return (
    <section aria-labelledby="dlq" className="space-y-2">
      <h2 id="dlq" className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Dead letters</h2>
      <ul className="divide-y divide-rule/70 rounded-2xl border border-rule bg-card shadow-sm">
        {letters.data.map((l) => (
          <li key={l.id} className="flex items-center justify-between px-5 py-3 text-sm">
            <span><span className="font-mono text-xs font-semibold">{l.stream}</span>, {l.deliveries} deliveries{l.replays ? `, replayed ${l.replays}×` : ""}</span>
            <button type="button" onClick={() => replay.mutate(l.id)}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-ink-soft hover:bg-bubble hover:text-ink">
              <RotateCcw aria-hidden size={14} />Replay</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function OpsPage() {
  const { me } = useSession();
  const operator = !!me?.groups.includes("operators");
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-[1.6rem] font-semibold tracking-tight">Pipeline</h1>
        <p className="text-sm text-ink-soft">Live ingestion board</p>
      </div>
      <Board />
      {operator && <Streams />}
      {operator && <Drills />}
      {operator && <DeadLetters />}
    </div>
  );
}
