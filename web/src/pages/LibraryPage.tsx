import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, History, Plus, Search, Upload } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DocumentRow, VersionStatus } from "../api/types";
import { ClassificationBadge, StatusBadge } from "../components/Badge";
import { DataTable } from "../components/DataTable";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { useToast } from "../components/Toast";
import { CATEGORIES } from "../copy/categories";
import { useSession } from "../app/session";

export default function LibraryPage() {
  const { me } = useSession();
  const canUpload = !!me?.groups.includes("doc-admins");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const toast = useToast();
  const client = useQueryClient();
  const docs = useQuery({
    queryKey: ["library", category, status],
    queryFn: () => api<DocumentRow[]>(`/api/documents?${new URLSearchParams({
      ...(category ? { category } : {}), ...(status ? { status } : {}) })}`),
    refetchInterval: 3000,
  });
  const retire = useMutation({
    mutationFn: (id: string) => api(`/api/documents/${id}/retire`, { method: "POST" }),
    onSuccess: () => { toast("Document retired"); client.invalidateQueries({ queryKey: ["library"] }); },
  });

  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const rows = (docs.data ?? []).filter((r) => !needle || `${r.title} ${r.category}`.toLowerCase().includes(needle));
  const action = "inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-ink-soft hover:bg-bubble hover:text-ink";

  return (
    <div className="max-w-6xl">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-[1.6rem] font-semibold tracking-tight">Library</h1>
          {docs.data && <p className="text-sm text-ink-soft">{docs.data.length} document{docs.data.length === 1 ? "" : "s"}</p>}
        </div>
        {canUpload && <Link to="/library/new" className="btn-primary inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold">
          <Plus aria-hidden size={16} /> New document
        </Link>}
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-2 text-sm">
        <label className="flex min-w-56 flex-1 items-center gap-2 rounded-xl border border-rule bg-card px-3 py-2 focus-within:border-scrub/50 sm:max-w-xs">
          <Search aria-hidden size={15} className="text-ink-soft" />
          <span className="sr-only">Filter documents</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter documents…"
                 className="w-full bg-transparent outline-none placeholder:text-ink-soft" />
        </label>
        <label>
          <span className="sr-only">Category</span>
          <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)} className="rounded-xl py-2">
            <option value="">All categories</option>
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label>
          <span className="sr-only">Status</span>
          <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-xl py-2">
            <option value="">All statuses</option>
            {["PENDING_APPROVAL", "QUEUED", "PROCESSING", "READY", "FAILED", "REJECTED"].map((s) => (
              <option key={s} value={s}>{s.charAt(0) + s.slice(1).replace("_", " ").toLowerCase()}</option>))}
          </select>
        </label>
      </div>
      <div className="mt-4">
        {docs.isLoading && <Skeleton lines={6} />}
        {docs.error && <ErrorState error={docs.error} />}
        {docs.data?.length === 0 && <EmptyState title="No documents yet">Upload the first approved policy.</EmptyState>}
        {!!docs.data?.length && !rows.length && <p className="px-1 py-6 text-sm text-ink-soft">No documents match “{query}”.</p>}
        {!!rows.length && (
          <DataTable caption="Documents" rows={rows} rowKey={(r) => r.document_id} columns={[
            { key: "title", header: "Title", render: (r) => (
              <div className="min-w-0"><Link className="font-medium text-ink hover:text-scrub" to={`/documents/${r.document_id}`}>{r.title}</Link>
                <p className="text-xs text-ink-soft">{r.category}</p></div>) },
            { key: "class", header: "Classification", render: (r) => <ClassificationBadge value={r.classification} /> },
            { key: "active", header: "Live", render: (r) => r.active_version_number
              ? <span className="rounded-md bg-bubble px-1.5 py-0.5 text-xs font-semibold tabular-nums">v{r.active_version_number}</span>
              : <span className="text-xs text-ink-soft">None yet</span> },
            { key: "latest", header: "Latest upload", render: (r) => (
              <Link to={`/versions/${r.latest_version_id}`} className="inline-flex items-center gap-2" title={`Version ${r.latest_version_number}`}>
                <StatusBadge status={r.latest_status as VersionStatus} />
                <span className="text-xs tabular-nums text-ink-soft">
                  v{r.latest_version_number}{r.latest_status === "PROCESSING" ? ` · ${r.chunks_embedded}/${r.chunks_total}` : ""}
                </span>
              </Link>) },
            { key: "actions", header: "", className: "text-right", render: (r) => (
              <div className="flex justify-end gap-0.5 opacity-70 transition-opacity group-hover:opacity-100">
                <Link className={action} to={`/admin/documents/${r.document_id}`} title="Version history">
                  <History aria-hidden size={14} />Versions
                </Link>
                {canUpload && <Link className={action} to={`/library/${r.document_id}/new-version`} title="Upload new version">
                  <Upload aria-hidden size={14} /><span className="sr-only">Upload new version</span><span aria-hidden>New version</span>
                </Link>}
                {canUpload && !r.retired_at && <button type="button" className={`${action} hover:!text-failed`}
                  onClick={() => retire.mutate(r.document_id)} title="Retire document">
                  <Archive aria-hidden size={14} />Retire
                </button>}
              </div>) },
          ]} />
        )}
      </div>
    </div>
  );
}
