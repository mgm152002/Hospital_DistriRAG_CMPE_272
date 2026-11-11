// Covers: UX-7, UX-8, UX-10, RL-8, RL-9, AT-04, AT-11, AT-12, AT-13
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ApiError } from "../api/client";
import { ErrorState } from "../components/States";
import { server } from "../test/server";
import { renderApp } from "../test/render";

const card = (status: string, stage: string | null, embedded = 0) => ({
  version_id: "v1", document_id: "d1", title: "Blood Transfusion Administration", version_number: 2, status, stage,
  chunks_total: 8, chunks_embedded: embedded, error_code: null, updated_at: "2026-11-25",
});

function pipeline(events: [string, unknown][]) {
  const body = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  server.use(http.get("/api/pipeline/events", () => new HttpResponse(body, { headers: { "Content-Type": "text/event-stream" } })));
}

const streams = { outbox_unpublished: 0, streams: [
  { stream: "ingest.embed", group: "embedders", length: 12, pending: 3, lag: 0, dlq: 0,
    consumers: [{ name: "app-embed-1", pending: 3, idle_ms: 42000 }] }] };

function opsHandlers(extra: Parameters<typeof server.use> = []) {
  server.use(
    ...extra,
    http.get("/api/ops/streams", () => HttpResponse.json(streams)),
    http.get("/api/ops/events", () => HttpResponse.json([])),
    http.get("/api/ops/dead-letters", () => HttpResponse.json([])),
  );
}

test("cards move between columns as pipeline events arrive", async () => {
  opsHandlers();
  pipeline([["version", card("QUEUED", null)], ["version", card("PROCESSING", "EMBED", 3)]]);
  renderApp("/ops", "casey");
  const embedding = await screen.findByRole("region", { name: "Embedding" });
  expect(await within(embedding).findByText("Blood Transfusion Administration v2")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Queued" })).queryByText(/Blood Transfusion/)).not.toBeInTheDocument();
  expect(within(embedding).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "3");
});

test("the streams strip shows pending messages and idle consumers", async () => {
  opsHandlers();
  pipeline([]);
  renderApp("/ops", "casey");
  expect(await screen.findByText("ingest.embed")).toBeInTheDocument();
  expect(screen.getByText("3 pending")).toBeInTheDocument();
  expect(screen.getByText(/app-embed-1, idle 42 s/)).toBeInTheDocument();
});

test("a drill asks for confirmation, then shows its timeline", async () => {
  let ran = "";
  opsHandlers([
    http.post("/api/ops/drills/:name", ({ params }) => { ran = params.name as string; return HttpResponse.json({ drill: ran }, { status: 202 }); }),
    http.get("/api/ops/events", () => HttpResponse.json([
      { id: 1, kind: "worker.killed", version_id: null, detail: { consumer: "app-embed-1" }, created_at: "2026-11-25T14:02:10Z" },
      { id: 2, kind: "message.reclaimed", version_id: "v1", detail: { from: "app-embed-1", to: "app-embed-2", idle_ms: 61000, delivery: 2 }, created_at: "2026-11-25T14:03:11Z" },
      { id: 3, kind: "version.ready", version_id: "v1", detail: { chunks: 8 }, created_at: "2026-11-25T14:03:12Z" },
    ])),
    http.get("/api/versions/v1/status", () => HttpResponse.json({ ...card("READY", null, 8) })),
  ]);
  pipeline([]);
  const user = userEvent.setup();
  renderApp("/ops", "casey");
  await user.click(await screen.findByRole("button", { name: "Kill a worker" }));
  expect(ran).toBe("");
  await user.click(screen.getByRole("button", { name: "Run drill" }));
  await waitFor(() => expect(ran).toBe("kill-worker"));
  const timeline = await screen.findByRole("list", { name: "Recovery timeline" });
  expect(await within(timeline).findByText(/reclaimed by app-embed-2 after 61 s/)).toBeInTheDocument();
  expect(await screen.findByText("8 of 8 chunks stored, 0 duplicates, 0 lost")).toBeInTheDocument();
});

test("knowledge admins see the board but not the drills", async () => {
  opsHandlers();
  pipeline([]);
  renderApp("/ops", "alex");
  expect(await screen.findByRole("heading", { name: "Pipeline" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Kill a worker" })).not.toBeInTheDocument();
});

test("a 429 shows a Retry-After countdown", () => {
  render(<ErrorState error={new ApiError(429, "rate_limited", "Too many requests", 5)} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Try again in 5 s");
});

test("each column shows the most recently updated versions first", async () => {
  opsHandlers();
  const old = Array.from({ length: 9 }, (_, i) => ["version", { ...card("READY", null, 8), version_id: `old${i}`,
    title: `Old ${i}`, updated_at: `2026-11-0${i + 1}T00:00:00Z` }] as [string, unknown]);
  pipeline([...old, ["version", { ...card("READY", null, 8), version_id: "new", title: "Newest", updated_at: "2026-11-25T00:00:00Z" }]]);
  renderApp("/ops", "casey");
  const ready = await screen.findByRole("region", { name: "Ready" });
  const items = await within(ready).findAllByRole("listitem");
  expect(items[0]).toHaveTextContent("Newest v2");
  expect(items).toHaveLength(8);
});
