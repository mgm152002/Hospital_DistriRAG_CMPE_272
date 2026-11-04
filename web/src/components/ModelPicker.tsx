import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Lock, Search, Sparkles, TerminalSquare, Globe } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fetchModels, modelName, providerLabel, providersOf, useChatSettings, useSaveChatSettings, withCurrent }
  from "../api/chatSettings";

const PROVIDER_ICON: Record<string, typeof Globe> = { "local-proxy": TerminalSquare, "openrouter-free": Globe };

/** Provider and model choice inside the composer: a popover with provider tabs and a searchable model list. */
export function ModelPicker() {
  const settings = useChatSettings();
  const save = useSaveChatSettings();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const data = settings.data;
  const shown = tab ?? data?.provider ?? "";
  const catalog = useQuery({ queryKey: ["chat-models", shown], enabled: open && !!data && shown !== data.provider,
                             queryFn: () => fetchModels(shown) });

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  if (!data) return null;
  const locked = !data.can_edit;
  const providers = providersOf(data);
  const models = shown === data.provider ? withCurrent(data.models, data.model) : catalog.data?.models ?? [];
  const needle = filter.trim().toLowerCase();
  const visible = models.filter((m) => !needle || `${m.id} ${m.name ?? ""}`.toLowerCase().includes(needle));
  const current = data.models.find((m) => m.id === data.model);

  async function choose(model: string) {
    setError(null);
    try {
      await save.mutateAsync({ provider: shown, model });
      setOpen(false); setFilter(""); setTab(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change the model");
    }
  }

  const Icon = PROVIDER_ICON[data.provider] ?? Sparkles;
  return (
    <div ref={root} className="relative min-w-0">
      <button type="button" aria-haspopup="dialog" aria-expanded={open} aria-label={`Model: ${current ? modelName(current) : data.model}`}
        title={locked ? "Only an administrator can change the model" : undefined}
        onClick={() => { setOpen(!open); setTab(null); setError(null); }}
        className="flex max-w-[16rem] items-center gap-1.5 rounded-lg px-2 py-1.5 text-[0.8rem] font-medium text-ink/80 hover:bg-bubble hover:text-ink">
        <Icon aria-hidden size={14} className="shrink-0 text-scrub" />
        <span className="truncate">{current ? modelName(current) : data.model}</span>
        {locked ? <Lock aria-hidden size={12} className="shrink-0 text-ink-soft" />
          : <ChevronDown aria-hidden size={14} className="shrink-0 text-ink-soft" />}
      </button>
      {open && (
        <div role="dialog" aria-label="Choose a model"
             className="pop absolute bottom-full left-0 z-30 mb-2 w-[22rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-rule bg-card shadow-xl shadow-black/10">
          <div role="tablist" aria-label="Provider" className="flex gap-1 border-b border-rule bg-rail/50 p-1.5">
            {providers.map((p) => {
              const PIcon = PROVIDER_ICON[p.id] ?? Sparkles;
              const usable = p.configured || p.id === data.provider;
              return (
                <button key={p.id} type="button" role="tab" aria-selected={shown === p.id} disabled={!usable}
                  title={usable ? undefined : "Add an API key in Settings"} onClick={() => { setTab(p.id); setFilter(""); }}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-semibold transition-colors disabled:opacity-45 ${
                    shown === p.id ? "bg-card text-ink shadow-sm" : "text-ink-soft hover:text-ink"}`}>
                  <PIcon aria-hidden size={13} />{p.label || providerLabel(p.id)}
                  {!usable && <span className="font-normal">· no key</span>}
                  {p.id === data.provider && <span aria-label="active" className="size-1.5 rounded-full bg-ready" />}
                </button>
              );
            })}
          </div>
          <label className="flex items-center gap-2 border-b border-rule px-3 py-2">
            <Search aria-hidden size={14} className="text-ink-soft" />
            <span className="sr-only">Search models</span>
            <input autoFocus value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search models…"
                   className="w-full bg-transparent text-sm outline-none placeholder:text-ink-soft" />
          </label>
          <ul role="listbox" aria-label="Models" className="thin-scroll max-h-72 overflow-y-auto p-1.5">
            {catalog.isLoading && <li className="px-3 py-2 text-sm text-ink-soft">Loading models…</li>}
            {!catalog.isLoading && !visible.length && <li className="px-3 py-2 text-sm text-ink-soft">No models found.</li>}
            {visible.map((m) => {
              const selected = shown === data.provider && m.id === data.model;
              return (
                <li key={m.id} role="option" aria-selected={selected}>
                  <button type="button" disabled={locked || save.isPending} onClick={() => choose(m.id)}
                    className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm disabled:cursor-default ${
                      selected ? "bg-scrub-wash text-ink" : "text-ink/85 enabled:hover:bg-bubble"}`}>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{modelName(m)}</span>
                      {m.name && m.name !== m.id && <span className="block truncate text-xs text-ink-soft">{m.id}</span>}
                    </span>
                    {selected && <Check aria-hidden size={15} className="shrink-0 text-scrub" />}
                  </button>
                </li>
              );
            })}
          </ul>
          {(error || locked) && (
            <p role={error ? "alert" : undefined} className={`border-t border-rule px-3 py-2 text-xs ${error ? "text-failed" : "text-ink-soft"}`}>
              {error || "Only an administrator can change the model."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
