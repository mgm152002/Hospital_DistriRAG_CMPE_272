import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BookOpenText, LibraryBig, LogOut, Monitor, Moon, PanelLeftClose, PanelLeftOpen, Pin, PinOff,
         Hospital, PencilLine, ScanSearch, Search, Settings2, ShieldCheck, SquarePen, Sun, Trash2, Waypoints, X,
         type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ConversationSummary } from "../api/types";
import { AREAS, canUse, useHospital, useSession, type Area } from "./session";
import { useTheme, type Theme } from "./theme";

const ICONS: Partial<Record<Area, LucideIcon>> = {
  admin: LibraryBig, search: ScanSearch, library: BookOpenText, compliance: ShieldCheck, operations: Activity,
};
const SECTIONS: Area[] = ["search", "library", "compliance", "admin", "operations"];

export const initials = (name: string) => name.replace(/^Dr\.?\s+/i, "").split(/\s+/).map((w) => w[0]).slice(0, 2).join("");
const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const MOD = mac ? "⌘" : "Ctrl";

const DAY = 86_400_000;
function bucket(iso: string, now: Date): string {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const t = new Date(iso).getTime();
  if (t >= start) return "Today";
  if (t >= start - DAY) return "Yesterday";
  if (t >= start - 6 * DAY) return "Last 7 days";
  if (t >= start - 29 * DAY) return "Last 30 days";
  return "Older";
}

const wide = () => typeof window === "undefined" || typeof window.matchMedia !== "function"
  || window.matchMedia("(min-width: 768px)").matches;

const PINS = "distrirag-pinned";
function usePins(): [Set<string>, (id: string) => void] {
  const [pins, setPins] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(window.localStorage?.getItem(PINS) ?? "[]")); } catch { return new Set(); }
  });
  const toggle = useCallback((id: string) => setPins((old) => {
    const next = new Set(old);
    if (next.has(id)) next.delete(id); else next.add(id);
    try { window.localStorage?.setItem(PINS, JSON.stringify([...next])); } catch { /* private mode */ }
    return next;
  }), []);
  return [pins, toggle];
}

function Threads({ onNavigate, searchRef }: { onNavigate: () => void; searchRef: React.RefObject<HTMLInputElement> }) {
  const { me } = useSession();
  const location = useLocation();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [filter, setFilter] = useState("");
  const [pins, togglePin] = usePins();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; draft: string } | null>(null);
  const active = location.pathname === "/assistant" ? new URLSearchParams(location.search).get("c") : null;
  const threads = useQuery({ queryKey: ["conversations", me?.user_id], enabled: !!me,
                             queryFn: () => api<ConversationSummary[]>("/api/conversations") });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/api/conversations/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      client.setQueryData<ConversationSummary[]>(["conversations", me?.user_id],
                                                 (all) => all?.filter((c) => c.conversation_id !== id));
      client.invalidateQueries({ queryKey: ["conversations"] });
      setConfirming(null);
      if (id === active) navigate("/assistant", { replace: true });
    },
  });
  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api<{ conversation_id: string; title: string }>(`/api/conversations/${id}`, {
        method: "PATCH", body: JSON.stringify({ title }), headers: { "Content-Type": "application/json" } }),
    onSuccess: ({ conversation_id, title }) => {
      client.setQueryData<ConversationSummary[]>(["conversations", me?.user_id],
        (all) => all?.map((c) => (c.conversation_id === conversation_id ? { ...c, title } : c)));
      client.invalidateQueries({ queryKey: ["conversations"] });
      setRenaming(null);
    },
  });
  const saveRename = () => {
    const title = renaming?.draft.trim();
    if (rename.isPending) return;
    if (!renaming || !title) return setRenaming(null);
    rename.mutate({ id: renaming.id, title });
  };
  const groups = useMemo(() => {
    const now = new Date();
    const needle = filter.trim().toLowerCase();
    const sorted = [...(threads.data ?? [])]
      .filter((c) => !needle || c.title.toLowerCase().includes(needle))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    const out: [string, ConversationSummary[]][] = [];
    const pinned = sorted.filter((c) => pins.has(c.conversation_id));
    if (pinned.length) out.push(["Pinned", pinned]);
    for (const c of sorted.filter((c) => !pins.has(c.conversation_id))) {
      const label = bucket(c.updated_at, now);
      if (out.at(-1)?.[0] !== label) out.push([label, []]);
      out.at(-1)![1].push(c);
    }
    return out;
  }, [threads.data, filter, pins]);

  return (
    <>
      <div className="shrink-0 px-3 pt-3">
        <label className="group flex items-center gap-2 border-b border-rule px-1.5 pb-2 focus-within:border-scrub/50">
          <Search aria-hidden size={14} strokeWidth={2} className="text-ink-soft" />
          <span className="sr-only">Search your threads</span>
          <input ref={searchRef} type="search" value={filter} onChange={(e) => setFilter(e.target.value)}
                 placeholder="Search your threads…"
                 className="w-full bg-transparent text-sm outline-none placeholder:text-ink-soft [&::-webkit-search-cancel-button]:hidden" />
          {filter ? (
            <button type="button" aria-label="Clear search" onClick={() => setFilter("")} className="text-ink-soft hover:text-ink">
              <X aria-hidden size={14} />
            </button>
          ) : <span aria-hidden className="kbd hidden group-hover:inline">{MOD} K</span>}
        </label>
      </div>
      <nav aria-label="Recent conversations" className="thin-scroll min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {groups.map(([label, items]) => (
          <section key={label} className="mt-4">
            <h2 className="flex items-center gap-1 px-2.5 pb-1 text-[0.7rem] font-semibold uppercase tracking-wider text-scrub-deep/80">
              {label === "Pinned" && <Pin aria-hidden size={11} />}{label}
            </h2>
            <ul className="space-y-px">
              {items.map((c) => {
                const current = c.conversation_id === active;
                const pinned = pins.has(c.conversation_id);
                return (
                  <li key={c.conversation_id} className="group relative">
                    {renaming?.id === c.conversation_id ? (
                      <form onSubmit={(e) => { e.preventDefault(); saveRename(); }} className="px-1 py-1">
                        <input autoFocus value={renaming.draft} maxLength={80} disabled={rename.isPending}
                          aria-label={`New title for ${c.title}`}
                          onChange={(e) => setRenaming({ id: c.conversation_id, draft: e.target.value })}
                          onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); setRenaming(null); } }}
                          onBlur={saveRename}
                          className="w-full rounded-lg border border-scrub/50 bg-paper px-2 py-1.5 text-sm outline-none" />
                      </form>
                    ) : <Link to={`/assistant?c=${c.conversation_id}`} title={c.title} onClick={onNavigate}
                      aria-current={current ? "page" : undefined}
                      className={`block truncate rounded-lg py-2 pl-2.5 pr-24 text-sm transition-colors ${
                        current ? "bg-bubble font-medium text-ink" : "text-ink/85 hover:bg-bubble/70 hover:text-ink"}`}>
                      {c.title}
                    </Link>}
                    {renaming?.id === c.conversation_id ? null : confirming === c.conversation_id ? (
                      <div className="pop absolute inset-y-0 right-0 flex items-center gap-1 rounded-lg bg-bubble pl-2 pr-1">
                        <button type="button" aria-label={`Confirm delete ${c.title}`} disabled={remove.isPending}
                          onClick={() => remove.mutate(c.conversation_id)}
                          className="rounded-md bg-failed px-2 py-0.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-60">
                          {remove.isPending ? "Deleting…" : "Delete"}
                        </button>
                        <button type="button" aria-label="Cancel delete" onClick={() => setConfirming(null)}
                          className="grid size-6 place-items-center rounded-md text-ink-soft hover:bg-rule hover:text-ink">
                          <X aria-hidden size={13} />
                        </button>
                      </div>
                    ) : (
                      <div className="absolute right-1 top-1/2 flex -translate-y-1/2 gap-0.5 rounded-md pl-3 opacity-0 focus-within:opacity-100 group-hover:opacity-100"
                           style={{ background: "linear-gradient(90deg, transparent, var(--color-bubble) 30%)" }}>
                        <button type="button" aria-label={pinned ? `Unpin ${c.title}` : `Pin ${c.title}`}
                          onClick={() => togglePin(c.conversation_id)}
                          className="grid size-6 place-items-center rounded-md text-ink-soft hover:bg-rule hover:text-ink">
                          {pinned ? <PinOff aria-hidden size={13} /> : <Pin aria-hidden size={13} />}
                        </button>
                        <button type="button" aria-label={`Rename ${c.title}`} title="Rename"
                          onClick={() => { rename.reset(); setConfirming(null); setRenaming({ id: c.conversation_id, draft: c.title }); }}
                          className="grid size-6 place-items-center rounded-md text-ink-soft hover:bg-rule hover:text-ink">
                          <PencilLine aria-hidden size={13} />
                        </button>
                        <button type="button" aria-label={`Delete ${c.title}`} title="Delete"
                          onClick={() => { remove.reset(); setConfirming(c.conversation_id); }}
                          className="grid size-6 place-items-center rounded-md text-ink-soft hover:bg-rule hover:text-failed">
                          <Trash2 aria-hidden size={13} />
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
        {remove.isError && (
          <p role="alert" className="mx-2.5 mt-3 rounded-lg bg-alarm-wash px-2.5 py-1.5 text-xs text-failed">
            Couldn't delete the thread. Try again.
          </p>
        )}
        {rename.isError && (
          <p role="alert" className="mx-2.5 mt-3 rounded-lg bg-alarm-wash px-2.5 py-1.5 text-xs text-failed">
            Couldn't rename the thread. Try again.
          </p>
        )}
        {filter && !groups.length && <p className="px-2.5 pt-4 text-sm text-ink-soft">No matching threads.</p>}
        {!filter && !groups.length && threads.isSuccess && (
          <p className="px-2.5 pt-4 text-sm text-ink-soft">Your conversations will appear here.</p>
        )}
      </nav>
    </>
  );
}

const THEMES: { id: Theme; label: string; Icon: LucideIcon }[] = [
  { id: "light", label: "Light theme", Icon: Sun }, { id: "dark", label: "Dark theme", Icon: Moon },
  { id: "system", label: "System theme", Icon: Monitor },
];

function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  const index = THEMES.findIndex((t) => t.id === theme);
  const { Icon, label } = THEMES[index];
  const next = THEMES[(index + 1) % THEMES.length];
  return (
    <button type="button" aria-label={`${label}. Switch to ${next.label.toLowerCase()}`} title={label}
            onClick={() => setTheme(next.id)}
            className="grid size-8 place-items-center rounded-lg text-ink-soft hover:bg-bubble hover:text-ink">
      <Icon aria-hidden size={16} />
    </button>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { me, signOut, config } = useSession();
  const hospital = useHospital();
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(wide);
  const searchRef = useRef<HTMLInputElement>(null);
  // On phones the sidebar is a drawer: close it after moving somewhere.
  useEffect(() => { if (!wide()) setOpen(false); }, [location.pathname, location.search]);
  const chat = !!me && canUse(me, "assistant");

  // Shortcuts: ⌘K search threads, ⌘⇧O new chat, ⌘B toggle the sidebar.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      const key = e.key.toLowerCase();
      if (key === "k" && chat) { e.preventDefault(); setOpen(true); setTimeout(() => searchRef.current?.focus(), 0); }
      else if (key === "o" && e.shiftKey && chat) { e.preventDefault(); navigate("/assistant"); }
      else if (key === "b") { e.preventDefault(); setOpen((o) => !o); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chat, navigate]);

  if (!me) return null;
  const fullBleed = location.pathname === "/assistant";
  const closeOnPhone = () => { if (!wide()) setOpen(false); };
  const sections = SECTIONS.filter((a) => canUse(me, a));
  const signOutLabel = config?.mode === "local" ? "Sign out" : "Switch person";

  return (
    <div className="flex h-dvh overflow-hidden bg-rail">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-card focus:p-2">
        Skip to content
      </a>
      {open && <div aria-hidden onClick={() => setOpen(false)} className="fixed inset-0 z-30 bg-black/40 backdrop-blur-[2px] md:hidden" />}
      <aside aria-label="Navigation and account"
             className={`${open ? "flex" : "hidden"} rail-wash fixed inset-y-0 left-0 z-40 w-72 shrink-0 flex-col md:static md:z-auto md:w-[17rem]`}>
        <div className="flex h-14 shrink-0 items-center gap-2 px-3">
          <button type="button" aria-label="Close sidebar" title={`Close sidebar (${MOD} B)`} onClick={() => setOpen(false)}
                  className="grid size-8 place-items-center rounded-lg text-ink-soft hover:bg-bubble hover:text-ink">
            <PanelLeftClose aria-hidden size={18} />
          </button>
          <Link to="/" className="flex flex-1 items-center justify-center gap-2 pr-10">
            <span aria-hidden className="btn-primary grid size-6 place-items-center rounded-md">
              <Waypoints size={14} strokeWidth={2.4} />
            </span>
            <span className="text-[1.05rem] font-bold tracking-tight text-ink">Distri<span className="text-scrub">RAG</span></span>
          </Link>
        </div>
        {hospital && (
          <div className="mx-3 mb-3 flex shrink-0 items-center gap-2 rounded-lg border border-rule bg-card/60 px-2.5 py-1.5"
               title={`${hospital.name} · ${hospital.campus} · ${hospital.code}`}>
            <Hospital aria-hidden size={14} className="shrink-0 text-scrub" />
            <div className="min-w-0 leading-tight">
              <p className="truncate text-[0.8rem] font-semibold text-ink">{hospital.name}</p>
              <p className="truncate text-[0.7rem] text-ink-soft">{hospital.campus} · {hospital.code}</p>
            </div>
          </div>
        )}
        {chat && (
          <div className="shrink-0 px-3">
            <Link to="/assistant" onClick={closeOnPhone} title={`New chat (${MOD} ⇧ O)`}
              className="btn-primary flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold">
              <SquarePen aria-hidden size={15} /> New chat
            </Link>
          </div>
        )}
        {chat ? <Threads onNavigate={closeOnPhone} searchRef={searchRef} /> : <div className="flex-1" />}
        <div className="shrink-0 space-y-1 px-2 pb-3">
          {sections.length > 0 && (
            <nav aria-label="Main" className="grid grid-cols-2 gap-0.5 border-t border-rule pt-2">
              {sections.map((a) => {
                const Icon = ICONS[a]!;
                return (
                  <NavLink key={a} to={AREAS[a].path} onClick={closeOnPhone}
                    className={({ isActive }) => `flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[0.8rem] transition-colors ${
                      isActive ? "bg-bubble font-medium text-ink" : "text-ink-soft hover:bg-bubble/70 hover:text-ink"}`}>
                    <Icon aria-hidden size={14} />{AREAS[a].label}
                  </NavLink>
                );
              })}
            </nav>
          )}
          <div className="flex items-center gap-1 rounded-xl px-1 py-1 hover:bg-bubble/60">
            <Link to="/profile" onClick={closeOnPhone} aria-label={`Your profile: ${me.name}`} title="View profile"
                  className="flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-1 py-1">
              <span aria-hidden className="btn-primary grid size-8 shrink-0 place-items-center rounded-full text-xs font-bold">
                {initials(me.name)}
              </span>
              <span className="min-w-0 flex-1 leading-tight">
                <span className="block truncate text-sm font-semibold">{me.name}</span>
                <span className="block truncate text-xs text-ink-soft">{me.role}</span>
              </span>
            </Link>
            <button type="button" onClick={signOut} title={signOutLabel} aria-label={signOutLabel}
                    className="grid size-8 place-items-center rounded-lg text-ink-soft hover:bg-bubble hover:text-ink">
              <LogOut aria-hidden size={15} />
            </button>
          </div>
        </div>
      </aside>
      <div className={`relative flex min-w-0 flex-1 flex-col bg-paper ${
        open ? "md:mt-3 md:rounded-tl-2xl md:border-l md:border-t md:border-rule" : ""}`}>
        {!open && (
          <div className="absolute left-3 top-3 z-20 flex gap-0.5 rounded-xl border border-rule bg-rail/80 p-1 backdrop-blur">
            <button type="button" aria-label="Open sidebar" title={`Open sidebar (${MOD} B)`} onClick={() => setOpen(true)}
                    className="grid size-8 place-items-center rounded-lg text-ink-soft hover:bg-bubble hover:text-ink">
              <PanelLeftOpen aria-hidden size={17} />
            </button>
            {chat && (
              <>
                <button type="button" aria-label="Search threads" onClick={() => { setOpen(true); setTimeout(() => searchRef.current?.focus(), 0); }}
                        className="grid size-8 place-items-center rounded-lg text-ink-soft hover:bg-bubble hover:text-ink">
                  <Search aria-hidden size={16} />
                </button>
                <Link to="/assistant" aria-label="New chat"
                      className="grid size-8 place-items-center rounded-lg text-ink-soft hover:bg-bubble hover:text-ink">
                  <SquarePen aria-hidden size={16} />
                </Link>
              </>
            )}
          </div>
        )}
        <div className="absolute right-3 top-3 z-20 flex gap-0.5 rounded-xl border border-rule bg-rail/80 p-1 backdrop-blur">
          {canUse(me, "settings") && (
            <NavLink to="/settings" aria-label="Settings" title="Settings" onClick={closeOnPhone}
              className={({ isActive }) => `grid size-8 place-items-center rounded-lg hover:bg-bubble hover:text-ink ${
                isActive ? "bg-bubble text-ink" : "text-ink-soft"}`}>
              <Settings2 aria-hidden size={16} />
            </NavLink>
          )}
          <ThemeSwitch />
        </div>
        <main id="main" className={`min-h-0 flex-1 ${fullBleed ? "overflow-hidden"
          : "thin-scroll overflow-y-auto px-5 pb-10 pt-16 md:px-10"}`}>
          {fullBleed ? children : <div className="mx-auto w-full max-w-6xl">{children}</div>}
        </main>
      </div>
    </div>
  );
}

export function Forbidden() {
  return (
    <div className="max-w-xl">
      <h1 className="text-xl font-semibold">You don't have access to this page</h1>
      <p className="mt-2 text-ink-soft">Switch person to see it.</p>
    </div>
  );
}
