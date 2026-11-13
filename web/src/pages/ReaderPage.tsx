import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Chunk, DocumentDetail, VersionText } from "../api/types";
import { Quote } from "lucide-react";
import { ClassificationBadge, Chip, StatusBadge } from "../components/Badge";
import { SafetyBanner } from "../components/SafetyBanner";
import { ErrorState, Skeleton } from "../components/States";

/** Join consecutive overlapping chunks without repeating the shared text. */
export function mergeChunks(texts: string[]): string {
  return texts.reduce((acc, next) => {
    if (!acc) return next;
    for (let k = Math.min(200, acc.length, next.length); k >= 8; k--) {
      if (acc.endsWith(next.slice(0, k))) return acc + next.slice(k);
    }
    return `${acc} ${next}`;
  }, "");
}

function trimOverlap(prev: string | undefined, text: string): string {
  if (!prev) return text;
  for (let k = Math.min(200, prev.length, text.length); k >= 8; k--) {
    if (prev.endsWith(text.slice(0, k))) return text.slice(k).replace(/^\s+/, "");
  }
  return text;
}

/** A chunk often starts with its own section heading ("1. Recognition"); the heading is already shown above it. */
function dropHeading(section: string | null, text: string): string {
  const title = section?.split(" > ").slice(-1)[0]?.trim();
  if (!title) return text;
  const [first, ...rest] = text.replace(/^\s+/, "").split("\n");
  return first.replace(/^#+\s*/, "").trim() === title ? rest.join("\n").replace(/^\s+/, "") : text;
}

function sections(chunks: Chunk[]) {
  const out: { section: string | null; chunks: { chunk: Chunk; text: string }[] }[] = [];
  chunks.forEach((chunk, i) => {
    const prev = chunks[i - 1];
    const text = dropHeading(chunk.section,
      prev && prev.section === chunk.section ? trimOverlap(prev.text, chunk.text) : chunk.text);
    if (!out.length || out[out.length - 1].section !== chunk.section) out.push({ section: chunk.section, chunks: [] });
    out[out.length - 1].chunks.push({ chunk, text });
  });
  return out;
}

const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" }) : "");

export default function ReaderPage() {
  const { documentId } = useParams();
  const [params] = useSearchParams();
  const doc = useQuery({ queryKey: ["doc", documentId], queryFn: () => api<DocumentDetail>(`/api/documents/${documentId}`) });
  const versionId = params.get("version") ?? doc.data?.active_version_id ?? undefined;
  const text = useQuery({
    queryKey: ["text", versionId], enabled: !!versionId,
    queryFn: () => api<VersionText>(`/api/versions/${versionId}/text`),
  });
  const cited = params.get("chunk");

  useEffect(() => {
    if (cited && text.data) document.getElementById(`chunk-${cited}`)?.scrollIntoView({ block: "center" });
  }, [cited, text.data]);

  if (doc.error) return <ErrorState error={doc.error} />;
  if (!doc.data) return <Skeleton lines={8} />;
  const d = doc.data;
  const viewing = d.versions.find((v) => v.version_id === versionId);
  const current = d.versions.find((v) => v.version_id === d.active_version_id);
  const superseded = !!viewing && viewing.version_id !== d.active_version_id;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <article className="rounded-2xl border border-rule bg-card px-6 py-6 shadow-sm sm:px-10 sm:py-8">
        <header className="border-b border-rule pb-5">
          <h1 className="text-[1.6rem] font-semibold tracking-tight leading-tight">{d.title}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            {viewing && (
              <span aria-label={`Version ${viewing.version_number}`}
                    className={`rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums ${
                      superseded ? "bg-past/15 text-past line-through" : "btn-primary"}`}>
                v{viewing.version_number}
              </span>
            )}
            <Chip>{d.category}</Chip>
            <ClassificationBadge value={d.classification} />
            {d.department && <span className="text-xs text-ink-soft">· {d.department}</span>}
          </div>
        </header>
        {superseded && current && (
          <div className="mt-5">
            <SafetyBanner variant="warning">
              This is not the current version. <Link className="font-bold underline"
                to={`/documents/${d.document_id}?version=${current.version_id}`}>View version {current.version_number}</Link>
            </SafetyBanner>
          </div>
        )}
        {text.isLoading && <div className="mt-6"><Skeleton lines={10} /></div>}
        {text.error && <div className="mt-6"><ErrorState error={text.error} /></div>}
        <div className="mt-6 max-w-[44rem] leading-[1.75] text-ink/90">
          {text.data && sections(text.data.chunks).map(({ section, chunks }, i) => (
            <section key={`${section}-${i}`} className="mb-7">
              {section && <h2 className="mb-2 text-[1.02rem] font-semibold text-ink">{section.split(" > ").slice(-1)[0]}</h2>}
              <div className="whitespace-pre-line">
                {chunks.map(({ chunk, text: body }) => chunk.chunk_id === cited ? (
                  <span key={chunk.chunk_id} id={`chunk-${chunk.chunk_id}`} data-testid={`chunk-${chunk.chunk_id}`}
                        data-cited="true"
                        className="relative -mx-3 my-1 block rounded-lg border-l-[3px] border-scrub bg-scrub-wash px-3 py-2 text-ink">
                    <span className="mb-1 flex items-center gap-1 text-[0.68rem] font-semibold uppercase tracking-wider text-scrub-deep">
                      <Quote aria-hidden size={11} />Cited
                    </span>
                    {body}
                  </span>
                ) : (
                  <span key={chunk.chunk_id} id={`chunk-${chunk.chunk_id}`} data-testid={`chunk-${chunk.chunk_id}`}>
                    {body}{" "}
                  </span>
                ))}
              </div>
            </section>
          ))}
        </div>
      </article>
      <aside aria-label="Document versions" className="h-fit rounded-2xl border border-rule bg-card p-5 shadow-sm lg:sticky lg:top-0">
        <h2 className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Versions</h2>
        <ol aria-label="Version history" className="mt-3 space-y-1">
          {d.versions.map((v) => {
            const on = v.version_id === versionId;
            return (
              <li key={v.version_id}>
                <Link to={`/documents/${d.document_id}?version=${v.version_id}`}
                      className={`block rounded-xl px-3 py-2.5 transition-colors ${on ? "bg-scrub-wash" : "hover:bg-bubble/60"}`}>
                  <span className="flex items-center justify-between gap-2">
                    <span className={`text-sm font-semibold ${on ? "text-scrub-deep" : "text-ink"}`}>Version {v.version_number}</span>
                    <StatusBadge status={v.status} />
                  </span>
                  <span className="mt-1 block text-xs text-ink-soft">
                    {v.approved_by ? `Approved by ${v.approved_by} · ${date(v.approved_at)}` : `Uploaded by ${v.uploaded_by}`}
                  </span>
                  {v.effective_date && <span className="block text-xs text-ink-soft">Effective {date(v.effective_date)}</span>}
                </Link>
              </li>
            );
          })}
        </ol>
      </aside>
    </div>
  );
}
