import { Link } from "react-router-dom";
import type { SearchHit } from "../api/types";
import { ClassificationBadge, Chip, VersionStamp } from "./Badge";

export function Highlighted({ text, ranges }: { text: string; ranges: [number, number][] }) {
  const parts: React.ReactNode[] = [];
  let at = 0;
  [...ranges].sort((a, b) => a[0] - b[0]).forEach(([start, end], i) => {
    if (start < at) return;
    parts.push(text.slice(at, start));
    parts.push(<mark key={i}>{text.slice(start, end)}</mark>);
    at = end;
  });
  parts.push(text.slice(at));
  return <>{parts}</>;
}

export function readerHref(documentId: string, versionId: string, chunkId: string) {
  return `/documents/${documentId}?version=${versionId}&chunk=${chunkId}`;
}

export function SourceCard({ hit, index, active = false }: { hit: SearchHit; index: number; active?: boolean }) {
  return (
    <article
      id={`source-${index}`}
      className={`flex gap-4 rounded-2xl border bg-card p-4 shadow-sm transition-colors hover:border-scrub/40 ${
        active ? "border-scrub/50 bg-scrub-wash/60" : "border-rule"}`}
    >
      <VersionStamp version={hit.version_number} />
      <div className="min-w-0 flex-1">
        <h2 className="text-base font-semibold leading-snug">
          <Link className="text-ink hover:text-scrub" to={readerHref(hit.document_id, hit.version_id, hit.chunk_id)}>
            {hit.title}
          </Link>
        </h2>
        <p className="mt-0.5 text-xs text-ink-soft">
          {hit.section ?? "Untitled section"}, page {hit.page}
        </p>
        <p className="mt-2 text-sm leading-relaxed"><Highlighted text={hit.snippet} ranges={hit.highlights} /></p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Chip>{hit.category}</Chip>
          <ClassificationBadge value={hit.classification} />
          <span className="text-xs tabular-nums text-ink-soft">{Math.round(hit.score * 100)}% match</span>
        </div>
      </div>
    </article>
  );
}
