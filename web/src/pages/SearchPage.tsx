import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { SearchHit } from "../api/types";
import { SourceCard } from "../components/SourceCard";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { CATEGORIES } from "../copy/categories";

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const categories = params.getAll("category");
  const [draft, setDraft] = useState(q);
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => setDraft(q), [q]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(target.tagName)) {
        e.preventDefault();
        box.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const results = useQuery({
    queryKey: ["search", q, categories],
    queryFn: () => {
      const query = new URLSearchParams({ q });
      categories.forEach((c) => query.append("category", c));
      return api<SearchHit[]>(`/api/search?${query}`);
    },
    enabled: q.trim().length >= 2,
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const next = new URLSearchParams(params);
    next.set("q", draft.trim());
    setParams(next);
  }

  function toggle(category: string) {
    const next = new URLSearchParams(params);
    const all = next.getAll("category");
    next.delete("category");
    (all.includes(category) ? all.filter((c) => c !== category) : [...all, category]).forEach((c) => next.append("category", c));
    setParams(next);
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-[1.6rem] font-semibold tracking-tight">Find a policy or procedure</h1>
      <p className="text-sm text-ink-soft">Current approved versions only</p>
      <form role="search" onSubmit={submit} className="mt-5 flex gap-2">
        <label className="relative flex-1">
          <span className="sr-only">Search approved documents</span>
          <Search aria-hidden size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-soft" />
          <input ref={box} type="search" aria-label="Search approved documents" value={draft}
                 onChange={(e) => setDraft(e.target.value)} autoFocus
                 placeholder="e.g. how long to rub hands with alcohol"
                 className="w-full rounded-xl border border-rule bg-card py-2.5 pl-10 pr-3.5 text-sm outline-none placeholder:text-ink-soft focus:border-scrub/60 focus:ring-4 focus:ring-scrub/10" />
        </label>
        <button type="submit" className="btn-primary rounded-xl px-4 py-2 text-sm font-semibold">Search</button>
      </form>
      <fieldset className="mt-3">
        <legend className="sr-only">Filter by category</legend>
        <div className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <button key={c} type="button" aria-pressed={categories.includes(c)} onClick={() => toggle(c)}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${categories.includes(c)
                ? "border-scrub/40 bg-scrub/10 text-scrub-deep" : "border-rule bg-card text-ink-soft hover:border-scrub/40 hover:text-ink"}`}>
              {c}
            </button>
          ))}
        </div>
      </fieldset>
      <section className="mt-6" aria-live="polite">
        {results.isLoading && <Skeleton lines={5} />}
        {results.error && <ErrorState error={results.error} />}
        {results.data && results.data.length === 0 && (
          <EmptyState title="No approved documents you can access match this.">
            Try different words, remove a category filter, or ask the assistant.
          </EmptyState>
        )}
        {results.data && results.data.length > 0 && (
          <>
            <p className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">
              {results.data.length} result{results.data.length === 1 ? "" : "s"} from documents you can access
            </p>
            <div className="mt-3 space-y-3">{results.data.map((hit, i) => <SourceCard key={hit.chunk_id} hit={hit} index={i + 1} />)}</div>
          </>
        )}
        {!q && (
          <p className="text-sm text-ink-soft">
            Press <span className="kbd">/</span> to search from anywhere.
          </p>
        )}
      </section>
    </div>
  );
}
