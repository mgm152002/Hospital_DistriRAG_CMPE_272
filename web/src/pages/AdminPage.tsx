import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BookOpen, Clock3, ExternalLink, FileCheck2, Layers3, MessageSquare, Plus, Search, Upload, Users } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Route, Routes, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { DocumentDetail } from "../api/types";
import { useSession } from "../app/session";
import { ClassificationBadge, StatusBadge } from "../components/Badge";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { Approvals } from "./CompliancePage";
import LibraryPage from "./LibraryPage";

interface Analytics {
  counts: Record<string, number>;
  categories: { name: string; count: number }[];
  statuses: { name: string; count: number }[];
  usage: { date: string; searches: number; questions: number }[];
  activity: { id: number; action: string; actor: string; at: string }[];
}
const date = (value: string) => new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString(undefined, { month: "short", day: "numeric" });

function Overview() {
  const { me } = useSession();
  const query = useQuery({ queryKey: ["admin-analytics"], queryFn: () => api<Analytics>("/api/admin/analytics"), refetchInterval: 10000 });
  if (query.error) return <ErrorState error={query.error} />;
  if (!query.data) return <Skeleton lines={6} />;
  const { counts, usage, categories, activity } = query.data;
  const maxUsage = Math.max(1, ...usage.map((day) => day.searches + day.questions));
  const maxCategory = Math.max(1, ...categories.map((category) => category.count));
  const cards = [
    { label: "Documents", value: counts.documents, note: `${counts.published} currently published`, icon: BookOpen },
    { label: "Awaiting approval", value: counts.pending_approval, note: "Independent review required", icon: Clock3 },
    { label: "Document versions", value: counts.versions, note: `${counts.processing} processing · ${counts.failed} failed`, icon: Layers3 },
    { label: "Staff accounts", value: counts.users, note: "Active registered and demo users", icon: Users },
  ];
  return <div className="space-y-6">
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map(({ label, value, note, icon: Icon }) => <section key={label} className="rounded-2xl border border-rule bg-card p-5 shadow-sm">
        <div className="flex items-center justify-between"><h2 className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">{label}</h2>
          <span aria-hidden className="grid size-8 place-items-center rounded-lg bg-scrub/10 text-scrub"><Icon size={16} /></span></div>
        <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight">{value.toLocaleString()}</p><p className="mt-1 text-xs text-ink-soft">{note}</p>
      </section>)}
    </div>
    <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
      <section className="rounded-2xl border border-rule bg-card p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-base font-semibold">Knowledge in use</h2>
          <p className="text-xs text-ink-soft">Last 14 days</p></div>
          <div className="flex gap-4 text-xs text-ink-soft"><span><Search aria-hidden size={14} className="mr-1 inline text-scrub" />{counts.searches} searches</span>
            <span><MessageSquare aria-hidden size={14} className="mr-1 inline text-working" />{counts.questions} questions</span></div></div>
        <div role="img" aria-label={`Usage over 14 days; ${counts.searches} searches and ${counts.questions} questions in 30 days`}
          className="mt-6 flex h-44 items-end gap-2 border-b border-rule pb-1">
          {usage.map((day) => <div key={day.date} title={`${day.date}: ${day.searches} searches, ${day.questions} questions`}
            className="flex h-full flex-1 items-end gap-0.5">
            <div className="min-h-0.5 flex-1 rounded-t-md bg-scrub" style={{ height: `${Math.max(1, day.searches/maxUsage*100)}%` }} />
            <div className="min-h-0.5 flex-1 rounded-t-md bg-working/60" style={{ height: `${Math.max(1, day.questions/maxUsage*100)}%` }} />
          </div>)}
        </div>
        <div className="mt-2 flex justify-between text-xs text-ink-soft"><span>{usage[0] ? date(usage[0].date) : ""}</span><span>Today</span></div>
      </section>
      <section className="rounded-2xl border border-rule bg-card p-5 shadow-sm"><h2 className="text-base font-semibold">Library by category</h2>
        <div className="mt-5 space-y-4">{categories.slice(0, 7).map((category) => <div key={category.name}>
          <div className="mb-1 flex justify-between gap-3 text-sm"><span>{category.name}</span><span className="font-semibold tabular-nums">{category.count}</span></div>
          <div className="h-1.5 overflow-hidden rounded-full bg-rule/70"><div className="h-full rounded-full bg-scrub" style={{ width: `${category.count/maxCategory*100}%` }} /></div>
        </div>)}{!categories.length && <p className="text-sm text-ink-soft">No documents yet.</p>}</div>
      </section>
    </div>
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="rounded-2xl border border-rule bg-card p-5 shadow-sm"><h2 className="text-base font-semibold">Keep knowledge current</h2>
        <p className="text-xs text-ink-soft">The published version stays live during review.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {me?.groups.includes("doc-admins") && <Link to="/library/new" className="btn-primary inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold"><Plus aria-hidden size={16} />Upload document</Link>}
          <Link to="/admin/approvals" className="inline-flex items-center gap-2 rounded-xl border border-rule bg-card px-3.5 py-2 text-sm font-medium hover:bg-bubble"><Clock3 aria-hidden size={16} />Review queue ({counts.pending_approval})</Link>
          <Link to="/admin/documents" className="inline-flex items-center gap-2 rounded-xl border border-rule bg-card px-3.5 py-2 text-sm font-medium hover:bg-bubble"><Layers3 aria-hidden size={16} />Manage versions</Link>
        </div>
      </section>
      <section className="rounded-2xl border border-rule bg-card p-5 shadow-sm"><h2 className="text-base font-semibold">Recent activity</h2>
        <ul className="mt-3 divide-y divide-rule/70">{activity.slice(0, 6).map((item) => <li key={item.id} className="flex items-center gap-3 py-2.5 text-sm">
          <FileCheck2 aria-hidden size={15} className="shrink-0 text-scrub" /><span className="flex-1">{item.action.replaceAll(".", " ").replaceAll("_", " ")}<span className="ml-2 text-ink-soft">by {item.actor}</span></span>
          <time className="text-xs tabular-nums text-ink-soft">{date(item.at)}</time>
        </li>)}{!activity.length && <li className="py-2.5 text-sm text-ink-soft">No activity yet.</li>}</ul>
      </section>
    </div>
  </div>;
}

function Versions() {
  const { documentId } = useParams();
  const { me } = useSession();
  const [from, setFrom] = useState(""); const [to, setTo] = useState("");
  const query = useQuery({ queryKey: ["admin-document", documentId], queryFn: () => api<DocumentDetail>(`/api/documents/${documentId}`), refetchInterval: 5000 });
  const versions = query.data?.versions ?? [];
  const before = from || versions[1]?.version_id || versions[0]?.version_id;
  const after = to || versions[0]?.version_id;
  const comparison = useQuery({ queryKey: ["version-diff", documentId, before, after],
    queryFn: () => api<{ lines: { kind: string; text: string }[]; added: number; removed: number }>(
      `/api/admin/documents/${documentId}/compare?${new URLSearchParams({ from_version: before, to_version: after })}`),
    enabled: !!before && !!after && before !== after });
  if (query.error) return <ErrorState error={query.error} />;
  if (!query.data) return <Skeleton />;
  const document = query.data;
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><Link to="/admin/documents" className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-ink-soft hover:bg-bubble hover:text-ink -ml-2"><ArrowLeft aria-hidden size={14} />All documents</Link>
      <h2 className="mt-2 text-xl font-semibold tracking-tight">{document.title}</h2><div className="mt-1.5 flex items-center gap-2 text-sm text-ink-soft"><ClassificationBadge value={document.classification} />{document.category}</div></div>
      {me?.groups.includes("doc-admins") && <Link to={`/library/${documentId}/new-version`} className="btn-primary inline-flex h-fit items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold"><Upload aria-hidden size={16} />Upload new version</Link>}</div>
    <section className="rounded-2xl border border-rule bg-card p-5 shadow-sm"><h3 className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Version history</h3>
      <ol aria-label="Document version history" className="mt-2 divide-y divide-rule/70">{versions.map((version) => <li key={version.version_id} className="flex flex-wrap items-center justify-between gap-4 py-3.5">
        <div><div className="flex flex-wrap items-center gap-2"><span className="rounded-md bg-bubble px-1.5 py-0.5 text-xs font-semibold tabular-nums">v{version.version_number}</span><StatusBadge status={version.status} />
          {version.version_id === document.active_version_id && <span className="rounded-full bg-scrub/10 px-2.5 py-0.5 text-xs font-medium text-scrub-deep">Published version</span>}</div>
          <p className="mt-1.5 text-xs text-ink-soft">Uploaded by {version.uploaded_by} · {date(version.created_at)}{version.approved_by ? ` · Approved by ${version.approved_by}` : version.status === "REJECTED" ? " · Rejected" : " · Awaiting independent approval"}</p>
          {version.error && <p className="mt-1 text-sm text-failed">{version.error}</p>}</div>
        <Link className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-ink-soft hover:bg-bubble hover:text-ink" to={`/documents/${documentId}?version=${version.version_id}`}><ExternalLink aria-hidden size={14} />Open version</Link>
      </li>)}</ol>
    </section>
    <section className="rounded-2xl border border-rule bg-card p-5 shadow-sm"><h3 className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Compare versions</h3>
      {versions.length < 2 ? <p className="mt-2 text-sm text-ink-soft">Upload a second version to compare changes.</p> : <>
        <div className="mt-3 flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-sm text-ink-soft">From<select aria-label="Compare from version" value={before} onChange={(e) => setFrom(e.target.value)}>{versions.map((version) => <option key={version.version_id} value={version.version_id}>v{version.version_number}</option>)}</select></label>
          <label className="flex items-center gap-2 text-sm text-ink-soft">To<select aria-label="Compare to version" value={after} onChange={(e) => setTo(e.target.value)}>{versions.map((version) => <option key={version.version_id} value={version.version_id}>v{version.version_number}</option>)}</select></label>
        </div>
        {comparison.isFetching && <div className="mt-4"><Skeleton /></div>}
        {comparison.error && <div className="mt-4"><ErrorState error={comparison.error} /></div>}
        {comparison.data && before !== after && <><p className="mt-4 flex gap-2 text-xs font-medium"><span className="rounded-full bg-ready/12 px-2.5 py-0.5 text-ready">{comparison.data.added} lines added</span><span className="rounded-full bg-failed/12 px-2.5 py-0.5 text-failed">{comparison.data.removed} lines removed</span></p>
          <pre className="thin-scroll mt-3 max-h-[32rem] overflow-auto rounded-xl border border-rule bg-paper py-3 text-sm" aria-label="Version changes">{comparison.data.lines.map((line, index) => <span key={index} className={`block whitespace-pre-wrap px-4 ${line.kind === "added" ? "bg-ready/12 text-ready" : line.kind === "removed" ? "bg-failed/12 text-failed" : "text-ink-soft"}`}>{line.kind === "added" ? "+ " : line.kind === "removed" ? "− " : "  "}{line.text || " "}</span>)}</pre></>}
        {before === after && <p className="mt-4 text-sm text-ink-soft">Choose two different versions to compare.</p>}
      </>}
    </section>
  </div>;
}

export default function AdminPage() {
  return <div className="max-w-7xl">
    <header className="mb-5"><h1 className="text-[1.6rem] font-semibold tracking-tight">Knowledge control center</h1></header>
    <nav aria-label="Administration" className="mb-6 inline-flex gap-0.5 rounded-xl bg-rail/60 p-1 text-sm font-medium">
      {[["/admin", "Overview"], ["/admin/documents", "Documents"], ["/admin/approvals", "Approvals"]].map(([path, label]) => <NavLink key={path} to={path} end={path === "/admin"}
        className={({ isActive }) => `rounded-lg px-3 py-1.5 transition-colors ${isActive ? "bg-card text-ink shadow-sm" : "text-ink-soft hover:text-ink"}`}>{label}</NavLink>)}
    </nav>
    <Routes><Route index element={<Overview />} /><Route path="documents" element={<LibraryPage />} />
      <Route path="documents/:documentId" element={<Versions />} /><Route path="approvals" element={<section>
        <h2 className="mb-3 text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Review queue</h2>
        <Approvals /></section>} />
      <Route path="*" element={<EmptyState title="This admin page was not found" />} /></Routes>
  </div>;
}
