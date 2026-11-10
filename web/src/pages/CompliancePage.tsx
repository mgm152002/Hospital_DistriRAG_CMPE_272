import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, History, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api, ApiError, postJson } from "../api/client";
import type { AuditEntry, DocumentRow } from "../api/types";
import { ClassificationBadge } from "../components/Badge";
import { Button } from "../components/Button";
import { DataTable } from "../components/DataTable";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { useToast } from "../components/Toast";
import { useSession } from "../app/session";
import { describeError, GROUP_NAMES } from "../copy/errors";

interface Pending { version_id: string; document_id: string; title: string; category: string; classification: any;
  version_number: number; uploaded_by: string; created_at: string; filename: string; groups: string[] }

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function Preview({ versionId }: { versionId: string }) {
  const preview = useQuery({ queryKey: ["preview", versionId],
    queryFn: () => api<{ text: string }>(`/api/versions/${versionId}/preview`) });
  return <pre className="thin-scroll mt-4 max-h-48 overflow-auto whitespace-pre-wrap rounded-xl border border-rule bg-paper p-3.5 font-sans text-sm leading-relaxed">
    {preview.data?.text ?? "Loading preview…"}</pre>;
}

function ApprovalCard({ item }: { item: Pending }) {
  const { me } = useSession();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const toast = useToast();
  const client = useQueryClient();
  const own = me?.user_id === item.uploaded_by;
  const canReview = !!me?.groups.includes("compliance");
  const decide = useMutation({
    mutationFn: (approve: boolean) => approve
      ? postJson(`/api/versions/${item.version_id}/approve`, { comment: "" })
      : postJson(`/api/versions/${item.version_id}/reject`, { reason }),
    onSuccess: (_, approve) => { toast(approve ? `Approved ${item.title}` : `Rejected ${item.title}`);
                                 client.invalidateQueries({ queryKey: ["pending"] }); },
    onError: (e) => toast(e instanceof ApiError ? describeError(e.code) : String(e)),
  });
  return (
    <article aria-label={`${item.title} version ${item.version_number}`} className="rounded-2xl border border-rule bg-card p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">{item.title}, version {item.version_number}</h3>
          <p className="mt-0.5 text-xs text-ink-soft">{item.category} · {item.uploaded_by} · {when(item.created_at)}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs"><ClassificationBadge value={item.classification} />
            <span className="text-ink-soft">Readers: {item.groups.map((g) => GROUP_NAMES[g] ?? g).join(", ")}</span></div>
        </div>
        <div className="flex gap-2">
          <Button className="rounded-xl" disabled={!canReview || own || decide.isPending} title={!canReview ? "A compliance officer must review this version" : own ? "You uploaded this version" : undefined}
                  onClick={() => decide.mutate(true)}>Approve</Button>
          <Button variant="quiet" className="rounded-xl" disabled={!canReview || decide.isPending} onClick={() => setRejecting(!rejecting)}>Reject</Button>
        </div>
      </div>
      <Preview versionId={item.version_id} />
      <Link to={`/admin/documents/${item.document_id}`} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-ink-soft hover:bg-bubble hover:text-ink -ml-2 mt-3"><History aria-hidden size={14} />Version history and changes</Link>
      {rejecting && (
        <div className="mt-3 flex items-center gap-2">
          <label className="flex-1 text-sm"><span className="sr-only">Reason for rejection</span>
            <input className="w-full rounded-xl border border-rule bg-card px-3.5 py-2.5 outline-none focus:border-scrub/60 focus:ring-4 focus:ring-scrub/10" placeholder="Reason, e.g. outdated thresholds"
                   value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          <Button variant="danger" className="rounded-xl" disabled={!canReview || !reason.trim() || decide.isPending} onClick={() => decide.mutate(false)}>Confirm rejection</Button>
        </div>
      )}
    </article>
  );
}

export function Approvals() {
  const pending = useQuery({ queryKey: ["pending"], queryFn: () => api<Pending[]>("/api/versions?status=PENDING_APPROVAL"),
                             refetchInterval: 4000 });
  if (pending.error) return <ErrorState error={pending.error} />;
  if (!pending.data) return <Skeleton />;
  if (!pending.data.length) return <EmptyState title="Nothing waiting for approval" />;
  return <div className="space-y-4">{pending.data.map((p) => <ApprovalCard key={p.version_id} item={p} />)}</div>;
}

function Audit() {
  const [draft, setDraft] = useState({ actor: "", action: "" });
  const [filter, setFilter] = useState({ actor: "", action: "" });
  const query = new URLSearchParams(Object.entries(filter).filter(([, v]) => v));
  const audit = useQuery({ queryKey: ["audit", filter], queryFn: () => api<{ items: AuditEntry[] }>(`/api/audit?${query}`) });
  return (
    <div>
      <form className="flex flex-wrap items-end gap-3 text-sm" onSubmit={(e) => { e.preventDefault(); setFilter(draft); }}>
        <label className="flex flex-col gap-1.5"><span className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Person</span><input className="rounded-xl border border-rule bg-card px-3.5 py-2.5 outline-none focus:border-scrub/60 focus:ring-4 focus:ring-scrub/10 py-2" value={draft.actor}
          onChange={(e) => setDraft({ ...draft, actor: e.target.value })} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Action starts with</span><input className="rounded-xl border border-rule bg-card px-3.5 py-2.5 outline-none focus:border-scrub/60 focus:ring-4 focus:ring-scrub/10 py-2" value={draft.action}
          onChange={(e) => setDraft({ ...draft, action: e.target.value })} /></label>
        <Button type="submit" className="rounded-xl">Filter</Button>
        <a className="inline-flex items-center gap-2 rounded-xl border border-rule bg-card px-3.5 py-2 text-sm font-medium hover:bg-bubble" href={`/api/audit.csv?${query}`}><Download aria-hidden size={16} />Download CSV</a>
      </form>
      <div className="mt-4">
        {audit.error && <ErrorState error={audit.error} />}
        {audit.data && <DataTable caption="Audit log" rows={audit.data.items} rowKey={(r) => String(r.audit_id)} columns={[
          { key: "when", header: "When", render: (r) => when(r.created_at) },
          { key: "who", header: "Person", render: (r) => r.actor_id },
          { key: "action", header: "Action", render: (r) => <code className="rounded-md bg-bubble px-1.5 py-0.5 text-xs">{r.action}</code> },
          { key: "detail", header: "Detail", render: (r) => (
            <details><summary className="cursor-pointer text-xs font-medium text-ink-soft hover:text-ink">Show</summary>
              <pre className="mt-1.5 max-w-md overflow-auto rounded-lg bg-paper p-2 text-xs">{JSON.stringify(r.detail, null, 2)}</pre></details>) },
        ]} />}
      </div>
    </div>
  );
}

function DataEgress() {
  const config = useQuery({ queryKey: ["config"], queryFn: () => api<any>("/api/system/config") });
  const egress = useQuery({ queryKey: ["egress"], queryFn: () => api<any[]>("/api/egress") });
  if (!config.data) return config.error ? <ErrorState error={config.error} /> : <Skeleton />;
  const s = config.data.settings;
  const providers = Object.values(config.data.providers) as any[];
  return (
    <div className="space-y-6">
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {([
          ["Deployment profile", s.deployment_profile],
          ["Answer provider", s.llm_provider],
          ["Highest class sent outside", s.external_max_classification],
          ["Patient details in questions", s.phi_mode === "block" ? "Blocked" : "Redacted"],
          ["Synthetic data only", s.synthetic_data_only ? "Yes" : "No"],
          ["Conversations kept", `${s.chat_retention_days} days`],
          ["Audit log kept", `${s.audit_retention_days} days`],
        ] as [string, string][]).map(([term, value]) => (
          <div key={term} className="rounded-2xl border border-rule bg-card px-4 py-3 shadow-sm">
            <dt className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">{term}</dt>
            <dd className="mt-1 text-sm font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      <DataTable caption="Model providers" rows={providers} rowKey={(p) => p.name} columns={[
        { key: "name", header: "Provider", render: (p) => p.name },
        { key: "where", header: "Where it runs", render: (p) => (p.external ? `External (${p.region})` : "On our servers") },
        { key: "baa", header: "BAA", render: (p) => (p.baa_signed ? "Signed" : "None") },
        { key: "retains", header: "Prompt retention", render: (p) => (p.retains_data ? "Keeps prompts" : "Does not keep prompts") },
      ]} />
      <section>
        <h2 className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Recent egress decisions</h2>
        {egress.data?.length ? (
          <ul className="mt-3 divide-y divide-rule/70 rounded-2xl border border-rule bg-card text-sm shadow-sm">{egress.data.map((e, i) => (
            <li key={i} className="px-5 py-2.5"><span className="tabular-nums text-ink-soft">{when(e.created_at)}</span> · {e.actor_id}, {e.detail.egress ?? e.action}
              {e.detail.provider ? `, ${e.detail.provider}` : ""}</li>))}</ul>
        ) : <p className="mt-3 text-sm text-ink-soft">No external calls yet.</p>}
      </section>
    </div>
  );
}

function Deletions() {
  const [target, setTarget] = useState<DocumentRow | null>(null);
  const [typed, setTyped] = useState("");
  const toast = useToast();
  const client = useQueryClient();
  const docs = useQuery({ queryKey: ["library", "all"], queryFn: () => api<DocumentRow[]>("/api/documents") });
  const receipts = useQuery({ queryKey: ["deletions"], queryFn: () => api<any[]>("/api/deletions"), refetchInterval: 4000 });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast(`Deleting ${target?.title}`); setTarget(null); setTyped("");
                       client.invalidateQueries({ queryKey: ["library"] }); },
  });
  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Delete a document</h2>
        <p className="mt-1 text-sm text-ink-soft">Permanent: removes file, chunks, vectors and cached answers.</p>
        <ul className="mt-3 divide-y divide-rule/70 rounded-2xl border border-rule bg-card shadow-sm">
          {docs.data?.map((d) => (
            <li key={d.document_id} className="group flex items-center justify-between px-5 py-2.5 text-sm transition-colors hover:bg-bubble/40">
              <span className="font-medium">{d.title}</span>
              <button type="button" className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-ink-soft hover:bg-bubble hover:text-ink hover:!text-failed" aria-label={`Delete ${d.title}`} onClick={() => setTarget(d)}>
                <Trash2 aria-hidden size={14} />Delete</button>
            </li>))}
        </ul>
        {target && (
          <div role="dialog" aria-label={`Delete ${target.title}`} className="pop mt-4 rounded-2xl border border-failed/40 bg-alarm-wash p-5">
            <label className="block text-sm">Type the title, <strong>{target.title}</strong>, to confirm
              <input className="mt-2 w-full rounded-xl border border-rule bg-card px-3.5 py-2.5 outline-none focus:border-scrub/60 focus:ring-4 focus:ring-scrub/10" value={typed} onChange={(e) => setTyped(e.target.value)} /></label>
            <div className="mt-3 flex gap-2">
              <Button variant="danger" className="rounded-xl" disabled={typed !== target.title} onClick={() => remove.mutate(target.document_id)}>Delete permanently</Button>
              <Button variant="quiet" className="rounded-xl" onClick={() => setTarget(null)}>Cancel</Button>
            </div>
          </div>
        )}
      </section>
      <section>
        <h2 className="mb-3 text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Deletion receipts</h2>
        {receipts.data?.length ? (
          <DataTable caption="Deletion receipts" rows={receipts.data} rowKey={(r) => r.document_id + r.created_at} columns={[
            { key: "when", header: "When", render: (r) => when(r.created_at) },
            { key: "who", header: "Requested by", render: (r) => r.actor_id },
            { key: "what", header: "Removed", render: (r) => `${r.detail.objects} files, ${r.detail.chunks} chunks, ${r.detail.vectors} vectors, ${r.detail.cache_rows} cached answers` },
          ]} />
        ) : <p className="text-sm text-ink-soft">No deletions yet.</p>}
      </section>
    </div>
  );
}

const TABS = [["", "Approvals"], ["audit", "Audit log"], ["data", "Data and egress"], ["deletions", "Deletions"]];

export default function CompliancePage() {
  return (
    <div className="max-w-5xl">
      <h1 className="text-[1.6rem] font-semibold tracking-tight">Compliance</h1>
      <nav aria-label="Compliance" className="mt-5 inline-flex flex-wrap gap-0.5 rounded-xl bg-rail/60 p-1">
        {TABS.map(([path, label]) => (
          <NavLink key={path} end to={`/compliance${path ? `/${path}` : ""}`}
            className={({ isActive }) => `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${isActive ? "bg-card text-ink shadow-sm" : "text-ink-soft hover:text-ink"}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-6">
        <Routes>
          <Route index element={<Approvals />} />
          <Route path="audit" element={<Audit />} />
          <Route path="data" element={<DataEgress />} />
          <Route path="deletions" element={<Deletions />} />
        </Routes>
      </div>
    </div>
  );
}
