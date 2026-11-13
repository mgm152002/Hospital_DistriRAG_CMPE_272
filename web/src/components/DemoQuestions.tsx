import { CornerDownRight } from "lucide-react";
import { useState } from "react";
import type { DemoGroup } from "../api/types";

/**
 * The evaluation corpus as one-click prompts for the signed-in role. Tabs name what each set of questions checks.
 * A conversation with several steps plays in order, so follow-ups ("and with soap?") work as they would for a person.
 */
export function DemoQuestions({ groups, disabled, onRun }:
  { groups: DemoGroup[]; disabled: boolean; onRun: (steps: string[]) => void }) {
  const [selected, setSelected] = useState(groups[0]?.scenario);
  const group = groups.find((g) => g.scenario === selected) ?? groups[0];
  if (!group) return null;
  return (
    <section aria-label="Test questions" className="surface overflow-hidden">
      <h2 className="sr-only">Test questions</h2>
      <div role="tablist" aria-label="What the questions check" className="flex gap-1 pt-2 overflow-x-auto px-4 [mask-image:linear-gradient(to_right,black_92%,transparent)]">
        {groups.map((g) => (
          <button key={g.scenario} type="button" role="tab" aria-selected={g.scenario === group.scenario}
            onClick={() => setSelected(g.scenario)}
            className={`flex shrink-0 items-center gap-2 rounded-t-lg border-b-2 px-3 py-2 text-sm font-bold ${
              g.scenario === group.scenario ? "border-scrub text-scrub-deep" : "border-transparent text-ink-soft hover:text-ink"}`}>
            <span>{g.title}</span>
            <span className="rounded-full bg-paper px-1.5 text-xs font-normal text-ink-soft">{g.conversations.length}</span>
          </button>
        ))}
      </div>
      <div role="tabpanel" className="border-t border-rule bg-paper/60 px-5 py-4">
        <ul className="grid gap-2 md:grid-cols-2">
          {group.conversations.map((c) => (
            <li key={c.id}>
              <button type="button" disabled={disabled} onClick={() => onRun(c.turns)}
                className="group flex h-full w-full items-start gap-3 rounded-lg border border-rule bg-card px-3.5 py-3 text-left text-sm shadow-sm transition hover:border-scrub hover:shadow disabled:opacity-50">
                <CornerDownRight aria-hidden size={16} className="mt-0.5 shrink-0 text-scrub" />
                <span className="flex-1">{c.turns[0]}</span>
                {c.turns.length > 1 && (
                  <span className="shrink-0 rounded bg-scrub-wash px-1.5 text-xs font-bold text-scrub-deep">
                    {c.turns.length} steps
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
