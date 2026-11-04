import type { ReactNode } from "react";

/**
 * A small markdown renderer for answers: paragraphs, bullet and numbered lists, headings, **bold**, `code`, and
 * [n] citation markers as raised pills. Text is rendered as React text nodes, never as HTML.
 */
type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; text: string }
  | { kind: "ul" | "ol"; items: string[]; start: number };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBER = /^\s*(\d+)[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}#{1,4}\s+(.*)$/;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let current = null as Block | null;
  const flush = () => { if (current) blocks.push(current); current = null; };
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) { flush(); continue; }
    const heading = line.match(HEADING);
    const bullet = line.match(BULLET);
    const number = line.match(NUMBER);
    if (heading) { flush(); blocks.push({ kind: "h", text: heading[1] }); }
    else if (bullet || number) {
      const kind = bullet ? "ul" : "ol";
      const item = bullet ? bullet[1] : number![2];
      if (current?.kind !== kind) { flush(); current = { kind, items: [], start: number ? Number(number[1]) : 1 }; }
      (current as Extract<Block, { kind: "ul" | "ol" }>).items.push(item);
    } else if ((current?.kind === "ul" || current?.kind === "ol") && /^\s+/.test(raw)) {
      const items = current.items;
      items[items.length - 1] += " " + line.trim();
    } else {
      if (current?.kind !== "p") { flush(); current = { kind: "p", lines: [] }; }
      (current as Extract<Block, { kind: "p" }>).lines.push(line);
    }
  }
  flush();
  return blocks;
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/;

function Inline({ text, onCite, active }: { text: string; onCite?: (n: number) => void; active?: number | null }) {
  const parts = text.split(INLINE);
  return (
    <>
      {parts.map((part, i) => {
        const cite = part.match(/^\[(\d+)\]$/);
        if (cite) {
          const n = Number(cite[1]);
          return (
            <button key={i} type="button" aria-label={`Source ${n}`} onClick={() => onCite?.(n)}
              className={`mx-px inline-block min-w-[1.1rem] -translate-y-[0.35em] rounded-full px-1 text-center align-baseline font-sans text-[0.68rem] font-bold leading-4 ${
                active === n ? "bg-scrub text-white" : "bg-scrub-wash text-scrub-deep hover:bg-scrub hover:text-white"}`}>
              {n}
            </button>
          );
        }
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={i}>{part.slice(2, -2)}</strong>;
        if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={i}>{part.slice(1, -1)}</code>;
        // The space before a citation belongs to the sentence, not the chip.
        return <span key={i}>{/^\[\d+\]$/.test(parts[i + 1] ?? "") ? part.replace(/\s+$/, "") : part}</span>;
      })}
    </>
  );
}

export function Markdown({ text, onCite, active }: { text: string; onCite?: (n: number) => void; active?: number | null }) {
  const nodes: ReactNode[] = parseBlocks(text).map((b, i) => {
    if (b.kind === "h") return <h3 key={i}><Inline text={b.text} onCite={onCite} active={active} /></h3>;
    if (b.kind === "p") {
      return (
        <p key={i}>
          {b.lines.map((line, j) => (
            <span key={j}>{j > 0 && <br />}<Inline text={line} onCite={onCite} active={active} /></span>
          ))}
        </p>
      );
    }
    const items = b.items.map((item, j) => <li key={j}><Inline text={item} onCite={onCite} active={active} /></li>);
    return b.kind === "ul" ? <ul key={i}>{items}</ul> : <ol key={i} start={b.start}>{items}</ol>;
  });
  return <div className="md">{nodes}</div>;
}
