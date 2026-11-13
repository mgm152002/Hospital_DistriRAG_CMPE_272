// Covers: UX-3, AG-5, AG-7, AG-9, AG-10, CP-3, RL-10, AT-14, AT-15, AT-18, AT-19, AT-22
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ChatFinal, Passage } from "../api/types";
import { chatSettings, server } from "../test/server";
import { renderApp } from "../test/render";

const passage: Passage = {
  index: 1, chunk_id: "c1", document_id: "d9", version_id: "v9", title: "Sepsis Screening and Escalation Protocol",
  version_number: 2, section: "Screening criteria", page: 1, classification: "internal", category: "Clinical Policy",
  score: 0.82, text: "Screen for sepsis when two or more are present: temperature above 38.3 C, heart rate above 90.",
};

function final(overrides: Partial<ChatFinal> = {}): ChatFinal {
  return {
    answer: "Screen for sepsis when two or more criteria are present [1].\n\nReference only. Verify against the source and use clinical judgement.",
    citations: [passage], cited: [1], confidence: 82, band: "High", parts: { r: 0.8, c: 1, a: 0.6 },
    fallback: null, conversation_id: "conv-1",
    receipt: { classification: "clinical_reference", phi_redacted: false, provider: "fake", model: "fake",
               external: false, egress_decision: "local", passages_withheld: {}, fallback: null, cached: false,
               latency_ms: 40, checks: { citations: "pass", clinical: "pass", injection: "pass" } },
    ...overrides,
  };
}

function sse(events: [string, unknown][]) {
  const body = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  return new HttpResponse(body, { headers: { "Content-Type": "text/event-stream" } });
}

function respond(events: [string, unknown][]) {
  server.use(http.post("/api/chat", () => sse(events)));
}

async function ask(text: string) {
  const user = userEvent.setup();
  renderApp("/assistant", "priya");
  const box = await screen.findByRole("textbox", { name: "Ask about a policy or procedure" });
  await user.type(box, text);
  await user.click(screen.getByRole("button", { name: "Ask" }));
  return user;
}

async function openDetails(user: ReturnType<typeof userEvent.setup>) {
  const card = await screen.findByRole("article", { name: "Answer" });
  await user.click(within(card).getByRole("button", { name: "Details" }));
  return card;
}

test("the verified answer keeps confidence, receipt and disclaimer behind Details", async () => {
  respond([["classification", { label: "clinical_reference" }], ["sources", { passages: [passage] }],
           ["token", { text: "Screen " }], ["token", { text: "for sepsis " }], ["final", final()]]);
  const user = await ask("What are our sepsis screening criteria?");
  expect(await screen.findByText(/Screen for sepsis when two or more criteria are present/)).toBeInTheDocument();
  expect(screen.queryByText("High confidence")).not.toBeInTheDocument();
  expect(screen.queryByText(/Reference only. Verify against the source/)).not.toBeInTheDocument();
  await openDetails(user);
  expect(screen.getByText("High confidence")).toBeInTheDocument();
  expect(screen.getByText("Guardrail receipt")).toBeInTheDocument();
  expect(screen.getByText(/Reference only. Verify against the source/)).toBeInTheDocument();
});

test("a citation chip highlights its source", async () => {
  respond([["classification", { label: "clinical_reference" }], ["sources", { passages: [passage] }], ["final", final()]]);
  const user = await ask("What are our sepsis screening criteria?");
  await user.click(await screen.findByRole("button", { name: "Source 1" }));
  const sources = screen.getByRole("region", { name: "Sources" });
  expect(within(sources).getByTestId("source-1")).toHaveAttribute("data-active", "true");
});

test("emergency banner renders above the answer", async () => {
  respond([["classification", { label: "emergency" }],
           ["banner", { level: "emergency", text: "If this is happening now, activate the Rapid Response / Code team per hospital procedure." }],
           ["sources", { passages: [passage] }], ["final", final()]]);
  await ask("My patient is unresponsive");
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("activate the Rapid Response");
  const answer = await screen.findByText(/Screen for sepsis when two or more criteria/);
  expect(alert.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("low confidence collapses the answer", async () => {
  respond([["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }],
           ["final", final({ confidence: 38, band: "Low" })]]);
  const user = await ask("Something vague");
  expect(await screen.findByText(/Show the drafted answer/)).toBeInTheDocument();
  await openDetails(user);
  expect(screen.getByText("Low confidence")).toBeInTheDocument();
});

test("PHI notice is shown when identifiers were removed", async () => {
  respond([["phi", { types: ["MRN", "NAME"] }], ["classification", { label: "policy_lookup" }],
           ["sources", { passages: [passage] }], ["final", final()]]);
  await ask("Patient John Smith MRN 00482913 fell");
  expect(await screen.findByText("We removed something that looked like patient information.")).toBeInTheDocument();
});

test("passages-only fallback shows a notice, not an error page", async () => {
  respond([["classification", { label: "clinical_reference" }], ["sources", { passages: [passage] }],
           ["final", final({ answer: "The answer service is unavailable; here are the most relevant passages.\n\nReference only. Verify against the source and use clinical judgement.",
                             fallback: "provider_unavailable", cited: [], band: "Low", confidence: 30 })]]);
  await ask("What are our sepsis screening criteria?");
  expect(await screen.findByText(/The answer service is unavailable/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Related passages" })).getByText("Sepsis Screening and Escalation Protocol")).toBeInTheDocument();
});

test("an empty conversation asks how to help and offers the persona's questions", async () => {
  renderApp("/assistant", "sam");
  expect(await screen.findByRole("heading", { level: 1, name: /^How can I help you/ })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "How long should I rub hands with alcohol-based rub?" })).toBeInTheDocument();
  expect(screen.queryByText(/Reference tool/)).not.toBeInTheDocument();
});

test("the answer area is a polite live region", async () => {
  renderApp("/assistant", "sam");
  expect(await screen.findByRole("log")).toHaveAttribute("aria-live", "polite");
});

// ---- streaming ----------------------------------------------------------------------------------------------------

test("tokens are shown as they arrive", async () => {
  respond([["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }],
           ["token", { text: "Screen " }], ["token", { text: "for sepsis " }]]);
  await ask("What are our sepsis screening criteria?");
  expect(await screen.findByTestId("streaming")).toHaveTextContent("Screen for sepsis");
  expect(screen.queryByRole("article", { name: "Answer" })).not.toBeInTheDocument();
});

test("a typing indicator shows before the first token", async () => {
  server.use(http.post("/api/chat", () => new HttpResponse(new ReadableStream({ start() { /* never sends */ } }),
    { headers: { "Content-Type": "text/event-stream" } })));
  await ask("What are our sepsis screening criteria?");
  expect(await screen.findByText("Writing an answer")).toBeInTheDocument();
});

test("the final answer replaces the streamed draft", async () => {
  respond([["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }],
           ["token", { text: "Draft " }], ["final", final()]]);
  await ask("What are our sepsis screening criteria?");
  const card = await screen.findByRole("article", { name: "Answer" });
  expect(within(card).getByText(/Screen for sepsis when two or more criteria are present/)).toBeInTheDocument();
  expect(screen.queryByText(/Draft/)).not.toBeInTheDocument();
});

test("source chips name the document and version; no provenance prose", async () => {
  respond([["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }], ["final", final()]]);
  await ask("What are our sepsis screening criteria?");
  const card = await screen.findByRole("article", { name: "Answer" });
  const sources = within(card).getByRole("region", { name: "Sources" });
  expect(within(sources).getByRole("link", { name: /Sepsis Screening and Escalation Protocol/ })).toBeInTheDocument();
  expect(within(sources).getByText("v2")).toBeInTheDocument();
  expect(within(card).queryByText(/^From /)).not.toBeInTheDocument();
});

test("markdown lists and bold render as structure", async () => {
  respond([["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }],
           ["final", final({ answer: "Screen when **two or more** apply:\n\n- Temperature above 38.3 C [1]\n- Heart rate above 90 [1]\n\n1. Draw lactate\n2. Escalate" })]]);
  await ask("What are our sepsis screening criteria?");
  const card = await screen.findByRole("article", { name: "Answer" });
  expect(within(card).getByText("two or more").tagName).toBe("STRONG");
  const bullets = within(card).getByText(/Temperature above 38.3 C/).closest("ul")!;
  expect(within(bullets).getAllByRole("listitem")).toHaveLength(2);
  expect(within(card).getByText("Draw lactate").closest("ol")).not.toBeNull();
});

test("a reply that cited nothing does not claim sources", async () => {
  respond([["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }],
           ["final", final({ fallback: "citations", cited: [], band: "Low", confidence: 0,
                             answer: "I couldn't verify a cited answer; here are the most relevant passages.\n\nReference only. Verify against the source and use clinical judgement." })]]);
  await ask("What is the fall risk reassessment schedule?");
  const card = await screen.findByRole("article", { name: "Answer" });
  expect(within(card).queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
  expect(within(card).getByRole("region", { name: "Related passages" })).toBeInTheDocument();
});

test("says in plain words what was removed from the question", async () => {
  respond([["phi", { types: ["NAME", "MRN"], notice: "Removed a name and a medical record number before searching." }],
           ["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }], ["final", final()]]);
  await ask("John Smith MRN 4471203 fell, what now?");
  expect(await screen.findByText("Removed a name and a medical record number before searching.")).toBeInTheDocument();
});

test("a quoted answer says so only inside Details", async () => {
  const receipt = final().receipt;
  respond([["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }],
           ["final", final({ fallback: "citations", band: "Medium", confidence: 70,
                             receipt: { ...receipt, mode: "extractive", fallback: "citations" },
                             answer: "Screen for sepsis when two or more are present. [1]\n\nReference only. Verify against the source and use clinical judgement." })]]);
  const user = await ask("What are our sepsis screening criteria?");
  expect(await screen.findByText(/Screen for sepsis when two or more are present\./)).toBeInTheDocument();
  expect(screen.queryByText("Quoted from the source, not summarised.")).not.toBeInTheDocument();
  await openDetails(user);
  expect(screen.getByText("Quoted from the source, not summarised.")).toBeInTheDocument();
});

test("a not-found reply keeps its next steps on screen", async () => {
  respond([["classification", { label: "policy_lookup" }], ["sources", { passages: [] }],
           ["final", final({ fallback: "no_sources", citations: [], cited: [], band: "Low", confidence: 0,
                             answer: "I couldn't find this in approved documents you can access. Try different words or a more specific question, or ask the knowledge administrator whether a document exists.\n\nReference only. Verify against the source and use clinical judgement." })]]);
  await ask("What is our DVT prophylaxis protocol?");
  expect(await screen.findByText(/Try different words or a more specific question/)).toBeInTheDocument();
});

test("an emergency shows the banner above an answer that starts with the number to dial", async () => {
  respond([["banner", { level: "emergency", text: "If this is happening now, activate the Rapid Response / Code team per hospital procedure." }],
           ["classification", { label: "emergency" }], ["sources", { passages: [passage] }],
           ["final", final({ answer: "Dial extension 5555 and state \"Code Blue\" with the unit and room number. [1]\n\nReference only. Verify against the source and use clinical judgement." })]]);
  await ask("patient is not breathing");
  const banner = await screen.findByRole("alert");
  const action = await screen.findByText(/Dial extension 5555/);
  expect(banner.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("a citation chip hugs its sentence instead of floating a space away", async () => {
  respond([["classification", { label: "clinical_reference" }], ["sources", { passages: [passage] }], ["final", final()]]);
  await ask("What are our sepsis screening criteria?");
  const paragraph = (await screen.findByText(/Screen for sepsis when two or more criteria are present/)).closest("p")!;
  expect(paragraph.textContent).toMatch(/present1\.$/);
});

test("the guardrail receipt is collapsed behind a one-line verdict", async () => {
  respond([["classification", { label: "clinical_reference" }], ["sources", { passages: [passage] }], ["final", final()]]);
  const user = await ask("What are our sepsis screening criteria?");
  await openDetails(user);
  const summary = screen.getByText("Guardrail receipt");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(within(summary).getByText("all checks passed")).toBeInTheDocument();
});

// ---- suggestions --------------------------------------------------------------------------------------------------

const demoGroups = [
  { scenario: "jargon", title: "Jargon", description: "Shorthand staff actually type",
    conversations: [{ id: "SAM-02", turns: ["HH duration with ABHR?"] }] },
  { scenario: "multi_turn", title: "Multi turn", description: "Follow-ups",
    conversations: [{ id: "SAM-09", turns: ["How long do I rub hands with gel?", "and with soap?"] }] },
];

function offerTestQuestions() {
  server.use(http.get("/api/demo/questions", () => HttpResponse.json({ enabled: true, groups: demoGroups })));
}

function recordChat(bodies: { message: string; conversation_id: string | null }[]) {
  server.use(http.post("/api/chat", async ({ request }) => {
    bodies.push((await request.json()) as { message: string; conversation_id: string | null });
    return sse([["classification", { label: "policy_lookup" }], ["sources", { passages: [passage] }], ["final", final()]]);
  }));
}

test("demo questions become one-click suggestions", async () => {
  offerTestQuestions();
  const bodies: { message: string; conversation_id: string | null }[] = [];
  recordChat(bodies);
  const user = userEvent.setup();
  renderApp("/assistant", "priya");
  const list = await screen.findByRole("list", { name: "Suggestions" });
  await user.click(await within(list).findByRole("button", { name: "HH duration with ABHR?" }));
  expect(await screen.findByText(/Screen for sepsis when two or more criteria are present/)).toBeInTheDocument();
  expect(bodies.map((b) => b.message)).toEqual(["HH duration with ABHR?"]);
});

test("a multi-step suggestion plays its steps in order within one conversation", async () => {
  offerTestQuestions();
  const bodies: { message: string; conversation_id: string | null }[] = [];
  recordChat(bodies);
  const user = userEvent.setup();
  renderApp("/assistant", "priya");
  await user.click(await screen.findByRole("tab", { name: "Multi turn" }));
  await user.click(await screen.findByRole("button", { name: "How long do I rub hands with gel?" }));
  expect(await screen.findByRole("region", { name: "Question 2" })).toBeInTheDocument();
  expect(bodies.map((b) => b.message)).toEqual(["How long do I rub hands with gel?", "and with soap?"]);
  expect(bodies[0].conversation_id).toBeNull();
  expect(bodies[1].conversation_id).toBe("conv-1");
});

test("outside a demo the persona's samples are the suggestions", async () => {
  renderApp("/assistant", "priya");
  const list = await screen.findByRole("list", { name: "Suggestions" });
  expect(within(list).getByRole("button", { name: "What is the fall risk reassessment schedule?" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "More examples" })).not.toBeInTheDocument();
});

// ---- sidebar threads ----------------------------------------------------------------------------------------------

const stored = {
  conversation_id: "conv-9",
  messages: [
    { role: "user", content: "How long should I rub hands?", citations: null, confidence: null, receipt: null,
      created_at: "2026-11-25T10:00:00Z" },
    { role: "assistant", content: "Rub for 20 to 30 seconds [1].\n\nReference only. Verify against the source and use clinical judgement.",
      citations: [passage], confidence: 88, receipt: final().receipt, created_at: "2026-11-25T10:00:02Z" },
  ],
};

const threads = [
  { conversation_id: "conv-9", title: "How long should I rub hands?", updated_at: new Date().toISOString(), messages: 2 },
  { conversation_id: "conv-8", title: "Visiting hours", updated_at: "2020-01-01T09:00:00Z", messages: 2 },
];

test("threads are grouped by date, newest first", async () => {
  server.use(http.get("/api/conversations", () => HttpResponse.json([...threads].reverse())));
  renderApp("/assistant", "priya");
  const recents = await screen.findByRole("navigation", { name: "Recent conversations" });
  await waitFor(() => expect(within(recents).getAllByRole("link").map((l) => l.textContent))
    .toEqual(["How long should I rub hands?", "Visiting hours"]));
  expect(within(recents).getByRole("heading", { name: "Today" })).toBeInTheDocument();
  expect(within(recents).getByRole("heading", { name: "Older" })).toBeInTheDocument();
});

test("searching threads filters the list", async () => {
  server.use(http.get("/api/conversations", () => HttpResponse.json(threads)));
  const user = userEvent.setup();
  renderApp("/assistant", "priya");
  const recents = await screen.findByRole("navigation", { name: "Recent conversations" });
  await within(recents).findByRole("link", { name: "Visiting hours" });
  await user.type(screen.getByRole("searchbox", { name: "Search your threads" }), "visit");
  expect(within(recents).getAllByRole("link").map((l) => l.textContent)).toEqual(["Visiting hours"]);
});

test("deleting a thread removes it", async () => {
  let deleted = "";
  server.use(http.get("/api/conversations", () => HttpResponse.json(deleted ? threads.slice(0, 1) : threads)),
             http.delete("/api/conversations/:id", ({ params }) => {
               deleted = params.id as string;
               return new HttpResponse(null, { status: 204 });
             }));
  const user = userEvent.setup();
  renderApp("/assistant", "priya");
  await user.click(await screen.findByRole("button", { name: "Delete Visiting hours" }));
  expect(deleted).toBe("");  // asks first
  await user.click(await screen.findByRole("button", { name: "Confirm delete Visiting hours" }));
  await waitFor(() => expect(screen.queryByRole("link", { name: "Visiting hours" })).not.toBeInTheDocument());
  expect(deleted).toBe("conv-8");
});

test("opening a thread shows its questions and answers", async () => {
  server.use(http.get("/api/conversations/conv-9", () => HttpResponse.json(stored)));
  renderApp("/assistant?c=conv-9", "priya");
  const log = await screen.findByRole("log");
  expect(await within(log).findByText("How long should I rub hands?")).toBeInTheDocument();
  const card = within(log).getByRole("article", { name: "Answer" });
  expect(within(card).getByText(/Rub for 20 to 30 seconds/)).toBeInTheDocument();
  expect(within(card).getByRole("region", { name: "Sources" })).toBeInTheDocument();
});

test("a follow-up in a reopened conversation continues that conversation", async () => {
  server.use(http.get("/api/conversations/conv-9", () => HttpResponse.json(stored)));
  const bodies: { message: string; conversation_id: string | null }[] = [];
  recordChat(bodies);
  const user = userEvent.setup();
  renderApp("/assistant?c=conv-9", "priya");
  await within(await screen.findByRole("log")).findByText("How long should I rub hands?");
  await user.type(screen.getByRole("textbox", { name: "Ask about a policy or procedure" }), "and with soap?");
  await user.click(screen.getByRole("button", { name: "Ask" }));
  await screen.findByRole("region", { name: "Question 2" });
  expect(bodies).toEqual([{ message: "and with soap?", conversation_id: "conv-9" }]);
});

test("new chat links to an empty conversation", async () => {
  renderApp("/assistant", "priya");
  await screen.findByRole("heading", { level: 1, name: /^How can I help you/ });
  expect(screen.queryByRole("region", { name: "Question 1" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "New chat" })).toHaveAttribute("href", "/assistant");
});

test("Enter sends and the send button stays disabled until there is something to ask", async () => {
  const bodies: { message: string; conversation_id: string | null }[] = [];
  recordChat(bodies);
  const user = userEvent.setup();
  renderApp("/assistant", "priya");
  const send = await screen.findByRole("button", { name: "Ask" });
  expect(send).toBeDisabled();
  await user.type(screen.getByRole("textbox", { name: "Ask about a policy or procedure" }), "Visiting hours?");
  expect(send).toBeEnabled();
  await user.keyboard("{Enter}");
  await screen.findByRole("region", { name: "Question 1" });
  expect(bodies.map((b) => b.message)).toEqual(["Visiting hours?"]);
});

test("other sections sit in a compact menu, not the chat list", async () => {
  renderApp("/assistant", "alex");
  const main = await screen.findByRole("navigation", { name: "Main" });
  expect(within(main).getByRole("link", { name: "Library" })).toBeInTheDocument();
  expect(within(main).queryByRole("link", { name: "Assistant" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
});

test("a reopened reply that cited nothing does not claim a source", async () => {
  const receipt = { ...final().receipt, fallback: "citations" };
  server.use(http.get("/api/conversations/conv-7", () => HttpResponse.json({ conversation_id: "conv-7", messages: [
    { role: "user", content: "who is manoj", citations: null, confidence: null, receipt: null, created_at: "2026-11-26T07:00:00Z" },
    { role: "assistant", content: "I couldn't verify a cited answer; here are the most relevant passages.",
      citations: [{ ...passage, cited: false }], confidence: 0, receipt, created_at: "2026-11-26T07:00:03Z" },
  ] })));
  renderApp("/assistant?c=conv-7", "priya");
  const card = await screen.findByRole("article", { name: "Answer" });
  expect(within(card).queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
  expect(within(card).getByRole("region", { name: "Related passages" })).toBeInTheDocument();
});

test("an older saved reply without citation flags is read from its receipt", async () => {
  const receipt = { ...final().receipt, fallback: "citations" };
  server.use(http.get("/api/conversations/conv-6", () => HttpResponse.json({ conversation_id: "conv-6", messages: [
    { role: "user", content: "who is manoj", citations: null, confidence: null, receipt: null, created_at: "2026-11-26T07:00:00Z" },
    { role: "assistant", content: "I couldn't verify a cited answer; here are the most relevant passages.",
      citations: [passage], confidence: 0, receipt, created_at: "2026-11-26T07:00:03Z" },
  ] })));
  renderApp("/assistant?c=conv-6", "priya");
  const card = await screen.findByRole("article", { name: "Answer" });
  expect(within(card).queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
});

// ---- provider and model picker ------------------------------------------------------------------------------------

test("the composer shows the model, read-only without edit rights", async () => {
  const user = userEvent.setup();
  renderApp("/assistant", "priya");
  await user.click(await screen.findByRole("button", { name: "Model: Automatic" }));
  const dialog = await screen.findByRole("dialog", { name: "Choose a model" });
  expect(within(dialog).getByRole("tab", { name: /OpenRouter/ })).toHaveAttribute("aria-selected", "true");
  expect(within(dialog).getByRole("option", { name: /Automatic/ })).toHaveAttribute("aria-selected", "true");
  expect(within(dialog).getByRole("button", { name: /Example free model/ })).toBeDisabled();
  expect(within(dialog).getByText("Only an administrator can change the model.")).toBeInTheDocument();
});

test("switching provider loads its models and saves the choice", async () => {
  let saved: any;
  server.use(http.get("/api/chat/settings", () => HttpResponse.json({ ...chatSettings, can_edit: true })),
    http.get("/api/chat/settings/models", () => HttpResponse.json({ models: [{ id: "gpt-6-luna", name: "gpt-6-luna" }],
                                                                     catalog_notice: null })),
    http.put("/api/chat/settings", async ({ request }) => {
      saved = await request.json();
      return HttpResponse.json({ ...chatSettings, can_edit: true, provider: saved.provider, model: saved.model,
                                 models: [{ id: "gpt-6-luna", name: "gpt-6-luna" }] });
    }));
  const user = userEvent.setup();
  renderApp("/assistant", "alex");
  await user.click(await screen.findByRole("button", { name: "Model: Automatic" }));
  await user.click(await screen.findByRole("tab", { name: /CLI Proxy/ }));
  await user.click(await screen.findByRole("button", { name: /gpt-6-luna/ }));
  await waitFor(() => expect(saved).toEqual({ provider: "local-proxy", model: "gpt-6-luna" }));
  expect(await screen.findByRole("button", { name: "Model: gpt-6-luna" })).toBeInTheDocument();
});

test("a provider without a key is offered disabled with a hint", async () => {
  server.use(http.get("/api/chat/settings", () => HttpResponse.json({ ...chatSettings, can_edit: true,
    providers: [{ id: "local-proxy", label: "CLI Proxy", configured: false },
                { id: "openrouter-free", label: "OpenRouter", configured: true }] })));
  const user = userEvent.setup();
  renderApp("/assistant", "alex");
  await user.click(await screen.findByRole("button", { name: "Model: Automatic" }));
  const tab = await screen.findByRole("tab", { name: /CLI Proxy/ });
  expect(tab).toBeDisabled();
  expect(tab).toHaveAttribute("title", "Add an API key in Settings");
});

