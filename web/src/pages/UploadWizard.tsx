import { useQuery } from "@tanstack/react-query";
import { Check, FileText, Lock, UploadCloud, Users, X } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { newIdempotencyKey } from "../api/ids";
import type { DocumentDetail } from "../api/types";
import { Button } from "../components/Button";
import { ErrorState } from "../components/States";
import { Stepper } from "../components/Stepper";
import { CATEGORIES, CLASSIFICATIONS, GROUPS } from "../copy/categories";
import { describeError, GROUP_NAMES } from "../copy/errors";

const MAX = 10 * 1024 * 1024;
const ALLOWED = [".txt", ".md", ".markdown", ".pdf"];

function checkFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ALLOWED.some((ext) => name.endsWith(ext))) return describeError("unsupported_type");
  if (file.size > MAX) return describeError("too_large");
  if (file.size === 0) return describeError("empty_document");
  return null;
}

export default function UploadWizard() {
  const { documentId } = useParams();
  const newVersion = !!documentId;
  const steps = newVersion ? ["File", "Review"] : ["File", "Details", "Access", "Review"];
  const [step, setStep] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [meta, setMeta] = useState({ title: "", category: "", department: "", classification: "internal",
                                     effective_date: "", review_due: "" });
  const [groups, setGroups] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const key = useRef(newIdempotencyKey());
  const navigate = useNavigate();
  const parent = useQuery({ queryKey: ["doc", documentId], enabled: newVersion,
                            queryFn: () => api<DocumentDetail>(`/api/documents/${documentId}`) });

  const canNext = [!!file && !fileError, !!meta.title.trim() && !!meta.category, groups.length > 0, true][step];
  const readers = groups.map((g) => GROUP_NAMES[g] ?? g);

  async function submit() {
    if (!file || submitting) return;
    setSubmitting(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    if (meta.effective_date) form.append("effective_date", meta.effective_date);
    if (meta.review_due) form.append("review_due", meta.review_due);
    if (!newVersion) {
      ["title", "category", "department", "classification"].forEach((k) => form.append(k, meta[k as keyof typeof meta]));
      form.append("groups", groups.join(","));
    }
    try {
      const ref = await api<{ version_id: string }>(newVersion ? `/api/documents/${documentId}/versions` : "/api/documents",
        { method: "POST", body: form, headers: { "Idempotency-Key": key.current } });
      navigate(`/versions/${ref.version_id}`);
    } catch (e) {
      setError(e);
      setSubmitting(false);
    }
  }

  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  function pick(f: File | null) {
    setFile(f);
    setFileError(f ? checkFile(f) : null);
    if (f && !meta.title) setMeta((m) => ({ ...m, title: f.name.replace(/\.[^.]+$/, "").replace(/[-_]/g, " ") }));
  }
  const size = (n: number) => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
  const field = "mt-1.5 w-full rounded-xl border border-rule bg-card py-2.5 pl-3.5 pr-9 text-[0.95rem] font-normal outline-none focus:border-scrub/60 focus:ring-4 focus:ring-scrub/10";
  const label = "block text-sm font-medium";
  return (
    <div className="max-w-2xl">
      <h1 className="text-[1.6rem] font-semibold tracking-tight">
        {newVersion ? `New version of ${parent.data?.title ?? "document"}` : "Upload a document"}
      </h1>
      <div className="mt-5 overflow-hidden rounded-2xl border border-rule bg-card shadow-sm">
        <div className="border-b border-rule bg-rail/40 px-6 py-4"><Stepper steps={steps} current={step} /></div>
        <div className="space-y-5 px-6 py-6">
          {step === 0 && (
            <div>
              <label htmlFor="file" className="sr-only">Choose a file</label>
              <input ref={picker} id="file" type="file" accept=".txt,.md,.markdown,.pdf" className="sr-only"
                onChange={(e) => pick(e.target.files?.[0] ?? null)} />
              {file ? (
                <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${fileError ? "border-failed/50 bg-alarm-wash" : "border-rule bg-paper"}`}>
                  <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-scrub/10 text-scrub"><FileText aria-hidden size={20} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{file.name}</span>
                    <span className="block text-xs text-ink-soft">{size(file.size)}</span>
                  </span>
                  {!fileError && <Check aria-hidden size={18} className="text-ready" />}
                  <button type="button" aria-label="Remove file" onClick={() => { pick(null); if (picker.current) picker.current.value = ""; }}
                    className="grid size-8 place-items-center rounded-lg text-ink-soft hover:bg-bubble hover:text-ink">
                    <X aria-hidden size={16} />
                  </button>
                </div>
              ) : (
                <button type="button" onClick={() => picker.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
                  onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0] ?? null); }}
                  className={`flex w-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
                    dragging ? "border-scrub bg-scrub-wash" : "border-rule bg-paper hover:border-scrub/50 hover:bg-scrub-wash/50"}`}>
                  <span className="grid size-12 place-items-center rounded-full bg-scrub/10 text-scrub"><UploadCloud aria-hidden size={24} /></span>
                  <span className="text-sm font-semibold">Drop a file here, or <span className="text-scrub">browse</span></span>
                  <span className="text-xs text-ink-soft">.txt, .md or text-based .pdf · up to 10 MB</span>
                </button>
              )}
              {fileError && <p role="alert" className="mt-2 text-sm text-failed">{fileError}</p>}
            </div>
          )}
          {step === 1 && !newVersion && (
            <>
              <label className={label}>Title<input className={field} value={meta.title}
                onChange={(e) => setMeta({ ...meta, title: e.target.value })} /></label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className={label}>Category<select className={field} value={meta.category}
                  onChange={(e) => setMeta({ ...meta, category: e.target.value })}>
                  <option value="">Choose a category</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></label>
                <label className={label}>Department<input className={field} value={meta.department} placeholder="Optional"
                  onChange={(e) => setMeta({ ...meta, department: e.target.value })} /></label>
                <label className={label}>Effective date<input type="date" className={field}
                  value={meta.effective_date} onChange={(e) => setMeta({ ...meta, effective_date: e.target.value })} /></label>
                <label className={label}>Review due<input type="date" className={field}
                  value={meta.review_due} onChange={(e) => setMeta({ ...meta, review_due: e.target.value })} /></label>
              </div>
            </>
          )}
          {step === 2 && !newVersion && (
            <>
              <label className={label}>Classification<select className={field} value={meta.classification}
                onChange={(e) => setMeta({ ...meta, classification: e.target.value })}>
                {CLASSIFICATIONS.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}</select></label>
              <fieldset>
                <legend className="text-sm font-medium">Who may read it</legend>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {GROUPS.map((g) => {
                    const on = groups.includes(g);
                    return (
                      <label key={g} className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-2.5 text-sm transition-colors ${
                        on ? "border-scrub bg-scrub-wash" : "border-rule bg-paper hover:border-scrub/40"}`}>
                        <input type="checkbox" aria-label={g} checked={on} className="sr-only"
                          onChange={() => setGroups((all) => all.includes(g) ? all.filter((x) => x !== g) : [...all, g])} />
                        <span aria-hidden className={`grid size-5 shrink-0 place-items-center rounded-md border ${
                          on ? "btn-primary border-transparent" : "border-rule bg-card"}`}>
                          {on && <Check size={13} strokeWidth={3} />}
                        </span>
                        <span className="font-medium">{GROUP_NAMES[g]}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
              {readers.length > 0 && (
                <p className="flex items-start gap-2 rounded-xl bg-scrub-wash px-3.5 py-2.5 text-sm text-ink">
                  <Users aria-hidden size={16} className="mt-0.5 shrink-0 text-scrub" />
                  {readers.join(", ")} will be able to read this once it is approved.
                </p>
              )}
            </>
          )}
          {step === steps.length - 1 && (
            <dl className="divide-y divide-rule/70 rounded-xl border border-rule bg-paper text-sm">
              {[["File", file?.name],
                ...(!newVersion ? [["Title", meta.title], ["Category", meta.category],
                                   ["Classification", meta.classification], ["Readers", readers.join(", ")]] : [])]
                .map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[8.5rem_1fr] gap-3 px-4 py-2.5">
                    <dt className="text-ink-soft">{k}</dt><dd className="font-medium">{v}</dd>
                  </div>
                ))}
            </dl>
          )}
          {step === steps.length - 1 && (
            <p className="flex items-center gap-2 text-xs text-ink-soft"><Lock aria-hidden size={13} />Nothing is searchable until a reviewer approves it.</p>
          )}
          {error != null && <ErrorState error={error instanceof ApiError ? new Error(describeError(error.code)) : error} />}
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-rule bg-rail/30 px-6 py-3.5">
          {step > 0 ? <Button variant="quiet" onClick={() => setStep(step - 1)}>Back</Button> : <span />}
          {step < steps.length - 1
            ? <Button disabled={!canNext} onClick={() => setStep(step + 1)}>Next</Button>
            : <Button disabled={submitting} onClick={submit}>{submitting ? "Submitting…" : "Submit for approval"}</Button>}
        </div>
      </div>
    </div>
  );
}
