import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, BookMarked, Check, Copy, FileText, PencilLine, RefreshCw, SlidersHorizontal, Square,
         Siren, Stethoscope, ShieldPlus, Pill, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, streamChat } from "../api/client";
import type { ChatFinal, DemoQuestions as Demo, Passage, PhiNotice, StoredMessage } from "../api/types";
import { useSession } from "../app/session";
import { ConfidenceMeter } from "../components/ConfidenceMeter";
import { DemoQuestions } from "../components/DemoQuestions";
import { GuardrailReceipt } from "../components/GuardrailReceipt";
import { Markdown } from "../components/Markdown";
import { ModelPicker } from "../components/ModelPicker";
import { SafetyBanner } from "../components/SafetyBanner";
import { readerHref } from "../components/SourceCard";
import { ErrorState } from "../components/States";

const DISCLAIMER = "Reference only. Verify against the source and use clinical judgement.";
const SAFETY = "Reference tool. Does not diagnose or replace clinical judgement.";

/** The trailing disclaimer lives in Details, not in the reply. */
export const stripDisclaimer = (text: string) =>
  text.replace(DISCLAIMER, "").replace(/\n*\s*Reference only\.[^\n]*\s*$/i, "").trim();

interface Turn {
  question: string;
  sources: Passage[];
  draft: string;
  banner?: string;
  phi?: PhiNotice;
  final?: ChatFinal;
  error?: unknown;
  searched?: boolean;
  stopped?: boolean;
}

const bandFor = (score: number): ChatFinal["band"] => (score >= 75 ? "High" : score >= 50 ? "Medium" : "Low");

/** A stored conversation, replayed as turns: each user message with the answer that followed it. */
function toTurns(conversationId: string, messages: StoredMessage[]): Turn[] {
  const turns: Turn[] = [];
  for (const m of messages) {
    if (m.role === "user") turns.push({ question: m.content, sources: [], draft: "" });
    else if (turns.length) {
      const citations = (m.citations ?? []) as (Passage & { cited?: boolean })[];
      const receipt = m.receipt ?? { classification: null, phi_redacted: false, provider: "", model: "", external: false,
        egress_decision: "none", passages_withheld: {}, checks: { citations: "n/a", clinical: "n/a", injection: "pass" },
        fallback: null, cached: false, latency_ms: 0 };
      turns[turns.length - 1].final = {
        // Saved replies flag what they cited; older ones without the flag are read from their receipt: a fallback that
        // did not quote the policy cited nothing.
        answer: m.content, citations, confidence: m.confidence ?? 0,
        cited: citations.filter((c) => c.cited ?? !(receipt.fallback && receipt.mode !== "extractive")).map((c) => c.index),
        band: bandFor(m.confidence ?? 0), parts: { r: 0, c: 0, a: 0 }, receipt, fallback: receipt.fallback,
        conversation_id: conversationId };
      turns[turns.length - 1].sources = citations;
    }
  }
  return turns;
}

function IconButton({ label, onClick, pressed, disabled, children }:
  { label: string; onClick: () => void; pressed?: boolean; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} aria-expanded={pressed} disabled={disabled}
      className={`grid size-8 place-items-center rounded-lg hover:bg-bubble hover:text-ink disabled:opacity-40 ${pressed ? "bg-bubble text-ink" : "text-ink-soft"}`}>
      {children}
    </button>
  );
}

/** The reply: rendered markdown, source cards, then quiet actions. Everything else waits behind Details. */
function Answer({ turn, index, onRetry, busy }: { turn: Turn; index: number; onRetry: () => void; busy: boolean }) {
  const final = turn.final!;
  const [active, setActive] = useState<number | null>(null);
  const [details, setDetails] = useState(false);
  const [copied, setCopied] = useState(false);
  const body = stripDisclaimer(final.answer);
  const cited = final.cited.length > 0;
  const low = final.band === "Low" && !final.fallback;
  const sources = final.citations.length ? final.citations : turn.sources;
  const id = (n: number) => `turn-${index}-source-${n}`;
  // One card per document version: four cited passages of one policy are one source, not four.
  const docs: { first: Passage; parts: Passage[] }[] = [];
  for (const p of sources) {
    const doc = docs.find((d) => d.first.document_id === p.document_id && d.first.version_id === p.version_id);
    if (doc) doc.parts.push(p); else docs.push({ first: p, parts: [p] });
  }

  function cite(n: number) {
    setActive(n);
    document.getElementById(id(n))?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  function copy() {
    navigator.clipboard?.writeText(body).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); },
                                             () => undefined);
  }

  return (
    <article aria-label="Answer" className="fade-in group/answer space-y-4">
      <div className="text-ink">
        {low ? (
          <details className="rounded-xl border border-dashed border-rule px-3 py-2">
            <summary className="cursor-pointer text-sm text-ink-soft">Low confidence. Show the drafted answer</summary>
            <div className="mt-2"><Markdown text={body} onCite={cite} active={active} /></div>
          </details>
        ) : <Markdown text={body} onCite={cite} active={active} />}
      </div>
      {docs.length > 0 && (
        <section aria-label={cited ? "Sources" : "Related passages"}>
          <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-soft">
            <BookMarked aria-hidden size={13} />{cited ? `${docs.length} source${docs.length > 1 ? "s" : ""}` : "Related"}
          </h3>
          <ol className="thin-scroll -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
            {docs.map(({ first, parts }) => {
              const on = parts.some((p) => p.index === active);
              const shown = parts.find((p) => p.index === active) ?? first;
              return (
                <li key={first.document_id + first.version_id} data-active={on ? "true" : undefined}
                    className={`w-60 shrink-0 rounded-xl border transition-colors ${
                      on ? "border-scrub bg-scrub-wash" : "border-rule bg-card hover:border-scrub/40"}`}>
                  {/* Every passage number keeps an anchor, so a [n] marker can scroll to its document. */}
                  {parts.map((p) => <span key={p.index} id={id(p.index)} data-testid={`source-${p.index}`}
                                          data-active={active === p.index ? "true" : undefined} />)}
                  <Link to={readerHref(shown.document_id, shown.version_id, shown.chunk_id)} className="block px-3 py-2.5">
                    <span className="flex items-center gap-1 text-[0.7rem] text-ink-soft">
                      {cited ? parts.map((p) => (
                        <span key={p.index} className={`grid h-4 min-w-4 place-items-center rounded px-0.5 font-bold ${
                          active === p.index ? "bg-scrub text-white" : "bg-scrub/15 text-scrub-deep"}`}>{p.index}</span>
                      )) : <FileText aria-hidden size={12} />}
                      <span className="ml-0.5">v{first.version_number}</span>
                      {parts.length > 1 ? <span>· {parts.length} passages</span> : first.page ? <span>· p.{first.page}</span> : null}
                    </span>
                    <span className="mt-1 block truncate text-sm font-medium text-ink">{first.title}</span>
                    <span className="block truncate text-xs text-ink-soft">{shown.section ?? "Untitled section"}</span>
                  </Link>
                </li>
              );
            })}
          </ol>
        </section>
      )}
      <div className="-ml-1.5 flex items-center gap-0.5 text-ink-soft opacity-70 transition-opacity group-hover/answer:opacity-100">
        <IconButton label={copied ? "Copied" : "Copy answer"} onClick={copy}>
          {copied ? <Check aria-hidden size={15} /> : <Copy aria-hidden size={15} />}
        </IconButton>
        <IconButton label="Regenerate" onClick={onRetry} disabled={busy}>
          <RefreshCw aria-hidden size={15} />
        </IconButton>
        <IconButton label="Details" pressed={details} onClick={() => setDetails(!details)}>
          <SlidersHorizontal aria-hidden size={15} />
        </IconButton>
        {final.receipt.model && (
          <span className="ml-2 truncate text-xs">
            {final.receipt.model}{final.receipt.latency_ms ? ` · ${(final.receipt.latency_ms / 1000).toFixed(1)}s` : ""}
          </span>
        )}
      </div>
      {details && (
        <div className="pop space-y-3 rounded-xl border border-rule bg-card p-4 text-sm">
          {(final.note || final.receipt.mode === "extractive") && (
            <p className="text-ink-soft">{final.note || "Quoted from the source, not summarised."}</p>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            <ConfidenceMeter score={final.confidence} band={final.band} parts={final.parts} />
            <GuardrailReceipt receipt={final.receipt} />
          </div>
          <p className="text-xs text-ink-soft">{DISCLAIMER} {SAFETY}</p>
        </div>
      )}
    </article>
  );
}

function Composer({ value, onChange, onSubmit, onStop, busy, box }:
  { value: string; onChange: (v: string) => void; onSubmit: () => void; onStop: () => void; busy: boolean;
    box: React.RefObject<HTMLTextAreaElement> }) {
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [value, box]);
  return (
    <div className="composer-shell rounded-t-[1.35rem] p-2 pb-0 sm:rounded-[1.35rem] sm:pb-2">
      <form className="rounded-t-2xl border border-b-0 border-rule bg-card px-3 pb-2 pt-2.5 shadow-sm sm:rounded-2xl sm:border-b"
            onSubmit={(e) => { e.preventDefault(); onSubmit(); }}>
        <textarea ref={box} aria-label="Ask about a policy or procedure" rows={2} value={value} autoFocus
          onChange={(e) => onChange(e.target.value)} maxLength={2000}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSubmit(); } }}
          placeholder="Type your message here…"
          className="composer-input block max-h-64 w-full resize-none bg-transparent px-1 py-1 text-base outline-none placeholder:text-ink-soft/80" />
        <div className="flex items-end justify-between gap-2 pt-1.5">
          <div className="flex min-w-0 items-center gap-1">
            <ModelPicker />
            <span className="hidden items-center gap-1 rounded-full border border-rule px-2 py-0.5 text-[0.7rem] text-ink-soft sm:flex"
                  title="Answers come only from approved hospital documents">
              <BookMarked aria-hidden size={11} />Approved documents
            </span>
          </div>
          {busy ? (
            <button type="button" onClick={onStop} aria-label="Stop"
              className="grid size-9 shrink-0 place-items-center rounded-xl bg-ink text-paper hover:opacity-85">
              <Square aria-hidden size={13} fill="currentColor" />
            </button>
          ) : (
            <button type="submit" disabled={value.trim().length < 2} aria-label="Ask"
              className="btn-primary grid size-9 shrink-0 place-items-center rounded-xl">
              <ArrowUp aria-hidden size={18} strokeWidth={2.4} />
            </button>
          )}
        </div>
      </form>
      <p className="hidden pt-1.5 text-center text-[0.7rem] text-ink-soft sm:block">
        Leave out patient names and record numbers. Verify against the source.
      </p>
    </div>
  );
}

const CATEGORY_ICONS = [ShieldPlus, Siren, Pill, Stethoscope, Sparkles];

export default function AssistantPage() {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const requested = params.get("c");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [category, setCategory] = useState(0);
  const [more, setMore] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const conversation = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const run_id = useRef(0);
  const demo = useQuery({ queryKey: ["demo-questions", me?.user_id], enabled: !!me,
                          queryFn: () => api<Demo>("/api/demo/questions") });
  const groups = demo.data?.enabled ? demo.data.groups : [];
  // Suggestions: the chosen category's test conversations, else the persona's sample questions.
  const suggestions: string[][] = groups.length
    ? (groups[category] ?? groups[0]).conversations.slice(0, 4).map((c) => c.turns)
    : (me?.samples ?? []).slice(0, 4).map((q) => [q]);
  const totalDemo = groups.reduce((n, g) => n + g.conversations.length, 0);
  const firstName = (me?.name ?? "").replace(/^Dr\.?\s+/i, "").split(/\s+/)[0];

  // Open a conversation from the sidebar, or start fresh for "New chat". A conversation already on screen is left alone.
  useEffect(() => {
    if (requested === conversation.current) return;
    conversation.current = requested;
    setMore(false);
    if (!requested) { setTurns([]); box.current?.focus(); return; }
    let cancelled = false;
    api<{ messages: StoredMessage[] }>(`/api/conversations/${requested}`)
      .then((c) => { if (!cancelled) setTurns(toTurns(requested, c.messages)); })
      .catch((error) => {
        if (cancelled) return;
        // Gone, expired or someone else's: start a new chat rather than a dead end.
        if (error instanceof ApiError && (error.status === 404 || error.status === 403)) {
          conversation.current = null;
          setTurns([]);
          navigate("/assistant", { replace: true });
        } else setTurns([{ question: "", sources: [], draft: "", error }]);
      });
    return () => { cancelled = true; };
  }, [requested]);

  const update = (patch: (t: Turn) => Turn) => setTurns((all) => [...all.slice(0, -1), patch(all[all.length - 1])]);

  async function ask(question: string) {
    if (question.trim().length < 2 || busy) return;
    setBusy(true);
    setInput("");
    pinned.current = true;
    const mine = ++run_id.current;
    setTurns((all) => [...all, { question, sources: [], draft: "" }]);
    try {
      for await (const { event, data } of streamChat(question, conversation.current)) {
        if (run_id.current !== mine) break;  // stopped: drop the rest of this reply
        if (event === "token") update((t) => ({ ...t, draft: t.draft + (data.text ?? "") }));
        else if (event === "sources") update((t) => ({ ...t, sources: data.passages, searched: true }));
        else if (event === "banner") update((t) => ({ ...t, banner: data.text }));
        else if (event === "phi") update((t) => ({ ...t, phi: data }));
        else if (event === "final") {
          const fresh = conversation.current !== data.conversation_id;
          conversation.current = data.conversation_id;
          update((t) => ({ ...t, final: data }));
          queryClient.invalidateQueries({ queryKey: ["conversations"] });
          if (fresh) navigate(`/assistant?c=${data.conversation_id}`, { replace: true });
        }
      }
    } catch (error) {
      if (run_id.current === mine) update((t) => ({ ...t, error }));
    } finally {
      if (run_id.current === mine) setBusy(false);
    }
  }

  /** Stop listening to the reply in progress; whatever arrived so far stays on screen. */
  function stop() {
    run_id.current += 1;
    update((t) => (t.final || t.error ? t : { ...t, stopped: true }));
    setBusy(false);
  }

  /** A test question starts a clean conversation; its steps are asked one after another. */
  async function run(steps: string[]) {
    if (busy) return;
    setTurns([]);
    setMore(false);
    conversation.current = null;
    if (requested) navigate("/assistant", { replace: true });
    for (const step of steps) await ask(step);
  }

  function edit(question: string) {
    setInput(question);
    setTimeout(() => box.current?.focus(), 0);
  }

  // Follow the reply while it streams, unless the reader has scrolled up.
  const latest = turns[turns.length - 1];
  const pinned = useRef(true);
  // "Scroll to bottom" shows only when there is more content below the fold.
  const measure = useCallback(() => {
    const el = scroller.current;
    setAtBottom(!el || el.scrollHeight - el.scrollTop - el.clientHeight < 120);
  }, []);
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
    measure();
  }, [turns, latest?.draft, latest?.final, latest?.sources, more, measure]);
  useEffect(() => {
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  function toBottom() {
    const el = scroller.current;
    pinned.current = true;
    el?.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }

  const empty = turns.length === 0;
  return (
    <div className="relative flex h-full flex-col">
      <div ref={scroller} onScroll={(e) => {
             const el = e.currentTarget;
             const near = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
             pinned.current = near;
             setAtBottom(near);
           }}
           className="thin-scroll min-h-0 flex-1 overflow-y-auto">
        <div role="log" aria-live="polite" aria-busy={busy}
             className={`mx-auto w-full max-w-3xl px-4 sm:px-8 ${empty ? "flex min-h-full flex-col justify-center py-16" : "space-y-12 pb-12 pt-20"}`}>
          {empty && (
            <div className="fade-in pb-[8vh]">
              <h1 className="text-[1.9rem] font-semibold tracking-tight text-ink sm:text-[2.2rem]">
                How can I help you{firstName ? `, ${firstName}` : ""}?
              </h1>
              {groups.length > 1 && (
                <div role="tablist" aria-label="Topics" className="mt-6 flex flex-wrap gap-2">
                  {groups.slice(0, 5).map((g, i) => {
                    const Icon = CATEGORY_ICONS[i % CATEGORY_ICONS.length];
                    return (
                      <button key={g.scenario} type="button" role="tab" aria-selected={category === i}
                        onClick={() => setCategory(i)}
                        className={`flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
                          category === i ? "btn-primary border-transparent" : "border-rule bg-card/70 text-ink/80 hover:bg-bubble hover:text-ink"}`}>
                        <Icon aria-hidden size={14} />{g.title}
                      </button>
                    );
                  })}
                </div>
              )}
              {suggestions.length > 0 && (
                <ul aria-label="Suggestions" className="mt-5 divide-y divide-rule/70">
                  {suggestions.map((steps) => (
                    <li key={steps.join("|")}>
                      <button type="button" disabled={busy} onClick={() => run(steps)}
                        className="w-full rounded-lg px-3 py-3 text-left text-[0.95rem] text-ink/75 transition-colors hover:bg-bubble/70 hover:text-ink disabled:opacity-50">
                        {steps[0]}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {totalDemo > suggestions.length && (
                <button type="button" aria-expanded={more} onClick={() => setMore(!more)}
                        className="mt-3 px-3 text-sm font-semibold text-scrub-deep hover:underline">
                  {more ? "Fewer examples" : "More examples"}
                </button>
              )}
              {more && <div className="mt-4"><DemoQuestions groups={groups} disabled={busy} onRun={run} /></div>}
            </div>
          )}
          {turns.map((t, i) => (
            <section key={i} aria-label={`Question ${i + 1}`} className="space-y-5">
              {t.question && (
                <div className="group/q flex flex-col items-end gap-1">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-bubble px-4 py-2.5 text-ink">
                    {t.question}
                  </p>
                  <div className="flex gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover/q:opacity-100">
                    <IconButton label="Edit question" onClick={() => edit(t.question)} disabled={busy}>
                      <PencilLine aria-hidden size={14} />
                    </IconButton>
                    <IconButton label="Copy question" onClick={() => navigator.clipboard?.writeText(t.question)}>
                      <Copy aria-hidden size={14} />
                    </IconButton>
                  </div>
                </div>
              )}
              {t.banner && <SafetyBanner variant="emergency">{t.banner}</SafetyBanner>}
              {t.phi && (
                <SafetyBanner variant="warning">
                  {t.phi.notice || "We removed something that looked like patient information."}
                </SafetyBanner>
              )}
              {t.error ? <ErrorState error={t.error} />
                : t.final ? <Answer turn={t} index={i} busy={busy} onRetry={() => ask(t.question)} />
                : t.stopped ? (
                  <div className="space-y-2">
                    {t.draft && <div className="text-ink"><Markdown text={stripDisclaimer(t.draft)} /></div>}
                    <p className="text-sm italic text-ink-soft">Stopped.</p>
                  </div>
                )
                : t.draft ? (
                  <div data-testid="streaming" className="text-ink"><Markdown text={stripDisclaimer(t.draft)} /></div>
                ) : (
                  <div role="status" className="flex items-center gap-2.5 text-sm">
                    <span className="typing flex h-6 items-center gap-1"><span /><span /><span /></span>
                    <span className="shimmer font-medium">
                      {t.searched ? (t.sources.length ? `Reading ${t.sources.length} source${t.sources.length > 1 ? "s" : ""}…`
                        : "Checking the library…") : "Searching approved documents…"}
                    </span>
                    <span className="sr-only">Writing an answer</span>
                  </div>
                )}
            </section>
          ))}
        </div>
      </div>
      {!atBottom && !empty && (
        <button type="button" onClick={toBottom} aria-label="Scroll to bottom"
          className="pop absolute bottom-36 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border border-rule bg-card/90 px-3 py-1.5 text-xs font-medium text-ink-soft shadow-md backdrop-blur hover:text-ink">
          <ArrowDown aria-hidden size={13} />Scroll to bottom
        </button>
      )}
      <div className="shrink-0">
        <div className="mx-auto w-full max-w-3xl sm:px-6 sm:pb-3">
          <Composer value={input} onChange={setInput} onSubmit={() => ask(input)} onStop={stop} busy={busy} box={box} />
        </div>
      </div>
    </div>
  );
}
