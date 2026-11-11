// Covers: UX-5, UX-6, FR-2, FR-4, FR-5, FR-7, FR-12, CR-5, CP-5, CP-7, AT-01, AT-03, AT-10, AT-23, AT-24
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderApp } from "../test/render";
import { describeError } from "../copy/errors";

const row = {
  document_id: "d1", title: "Visitor Policy", category: "Operational Workflow", department: "Patient Services",
  classification: "public", owner_id: "alex", created_at: "2026-11-01", retired_at: null, active_version_number: 1,
  latest_version_id: "v2", latest_version_number: 2, latest_status: "PROCESSING", latest_stage: "EMBED",
  chunks_total: 8, chunks_embedded: 3, updated_at: "2026-11-25", error_code: null, groups: ["all-staff"],
};

function file(name: string, size = 20, type = "text/markdown") {
  return new File(["x".repeat(size)], name, { type });
}

test("library lists documents with status and progress", async () => {
  server.use(http.get("/api/documents", () => HttpResponse.json([row])));
  renderApp("/library", "alex");
  expect(await screen.findByText("Visitor Policy")).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Documents" });
  expect(within(table).getByText("Processing")).toBeInTheDocument();
  expect(within(table).getByText(/3\/8/)).toBeInTheDocument();
});

test("wizard checks file type and size before uploading", async () => {
  const user = userEvent.setup({ applyAccept: false });
  renderApp("/library/new", "alex");
  const input = await screen.findByLabelText("Choose a file");
  await user.upload(input, file("photo.png", 20, "image/png"));
  expect(screen.getByText("Only .txt, .md and text-based .pdf files are supported.")).toBeInTheDocument();
  await user.upload(input, file("huge.pdf", 11 * 1024 * 1024, "application/pdf"));
  expect(screen.getByText("Files must be at most 10 MB.")).toBeInTheDocument();
});

test("wizard walks file, details, access and review, and reuses one idempotency key", async () => {
  const keys: string[] = [];
  server.use(http.post("/api/documents", ({ request }) => {
    keys.push(request.headers.get("Idempotency-Key") ?? "");
    return HttpResponse.json({ document_id: "d1", version_id: "v1", version_number: 1, status: "PENDING_APPROVAL" },
                             { status: 202 });
  }), http.get("/api/versions/v1/status", () => HttpResponse.json({ version_id: "v1", document_id: "d1",
    title: "Visitor Policy", version_number: 1, status: "PENDING_APPROVAL", stage: null, chunks_total: 0,
    chunks_embedded: 0, error_code: null, error: null, updated_at: "2026-11-25" })));
  const user = userEvent.setup();
  renderApp("/library/new", "alex");
  await user.upload(await screen.findByLabelText("Choose a file"), file("visitor.md"));
  await user.click(screen.getByRole("button", { name: "Next" }));
  await user.type(screen.getByLabelText("Title"), "Visitor Policy");
  await user.selectOptions(screen.getByLabelText("Category"), "Operational Workflow");
  await user.click(screen.getByRole("button", { name: "Next" }));
  await user.click(screen.getByRole("checkbox", { name: "nursing" }));
  expect(screen.getByText(/Nurses will be able to read this/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Next" }));
  const submit = screen.getByRole("button", { name: "Submit for approval" });
  await user.dblClick(submit);
  await waitFor(() => expect(keys.length).toBeGreaterThan(0));
  expect(new Set(keys).size).toBe(1);
  expect(await screen.findByText("Waiting for approval")).toBeInTheDocument();
});

test("error codes are explained in plain words", () => {
  expect(describeError("pdf_no_text_layer")).toBe("This PDF has no text layer (it looks scanned). Upload a text-based PDF.");
  expect(describeError("something_new")).toBe("Something went wrong (something_new).");
});

test("version page shows the failure in plain words", async () => {
  server.use(http.get("/api/versions/v5/status", () => HttpResponse.json({ version_id: "v5", document_id: "d5",
    title: "Scanned Policy", version_number: 1, status: "FAILED", stage: null, chunks_total: 0, chunks_embedded: 0,
    error_code: "pdf_no_text_layer", error: "no text", updated_at: "2026-11-25" })));
  renderApp("/versions/v5", "alex");
  expect(await screen.findByText("This PDF has no text layer (it looks scanned). Upload a text-based PDF.")).toBeInTheDocument();
});

const pending = [
  { version_id: "v1", document_id: "d1", title: "Visitor Policy", category: "Operational Workflow",
    classification: "public", version_number: 2, uploaded_by: "alex", created_at: "2026-11-25", filename: "v.md",
    groups: ["all-staff"] },
  { version_id: "v2", document_id: "d2", title: "Self Upload", category: "Clinical Policy", classification: "internal",
    version_number: 1, uploaded_by: "taylor", created_at: "2026-11-25", filename: "s.md", groups: ["clinical"] },
];

test("approve is disabled on your own upload; reject needs a reason", async () => {
  const approved: string[] = [];
  server.use(
    http.get("/api/versions", () => HttpResponse.json(pending)),
    http.get("/api/versions/:id/preview", () => HttpResponse.json({ text: "Visiting hours are 7:00 to 21:00." })),
    http.post("/api/versions/:id/approve", ({ params }) => { approved.push(params.id as string);
      return HttpResponse.json({ status: "QUEUED" }, { status: 202 }); }),
  );
  const user = userEvent.setup();
  renderApp("/compliance", "taylor");
  const own = await screen.findByRole("article", { name: "Self Upload version 1" });
  expect(within(own).getByRole("button", { name: "Approve" })).toBeDisabled();
  expect(within(own).getByRole("button", { name: "Approve" })).toHaveAttribute("title", "You uploaded this version");
  const other = screen.getByRole("article", { name: "Visitor Policy version 2" });
  expect(await within(other).findByText(/Visiting hours are 7:00/)).toBeInTheDocument();
  await user.click(within(other).getByRole("button", { name: "Reject" }));
  expect(within(other).getByRole("button", { name: "Confirm rejection" })).toBeDisabled();
  await user.click(within(other).getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(approved).toEqual(["v1"]));
});

test("audit log filters by actor and links to CSV", async () => {
  let seen = "";
  server.use(http.get("/api/audit", ({ request }) => {
    seen = new URL(request.url).search;
    return HttpResponse.json({ page: 1, items: [{ audit_id: 1, actor_id: "taylor", action: "version.approved",
      target: "v1", detail: { comment: "ok" }, created_at: "2026-11-25T10:00:00Z" }] });
  }));
  const user = userEvent.setup();
  renderApp("/compliance/audit", "taylor");
  expect(await screen.findByText("version.approved")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Person"), "taylor");
  await user.click(screen.getByRole("button", { name: "Filter" }));
  await waitFor(() => expect(seen).toContain("actor=taylor"));
  expect(screen.getByRole("link", { name: "Download CSV" })).toHaveAttribute("href", expect.stringContaining("/api/audit.csv"));
});

test("deleting a document needs its title typed", async () => {
  let deleted = false;
  server.use(
    http.get("/api/documents", () => HttpResponse.json([{ ...row, latest_status: "READY" }])),
    http.get("/api/deletions", () => HttpResponse.json([])),
    http.delete("/api/documents/d1", () => { deleted = true; return HttpResponse.json({}, { status: 202 }); }),
  );
  const user = userEvent.setup();
  renderApp("/compliance/deletions", "taylor");
  await user.click(await screen.findByRole("button", { name: "Delete Visitor Policy" }));
  const confirm = screen.getByRole("button", { name: "Delete permanently" });
  expect(confirm).toBeDisabled();
  await user.type(screen.getByLabelText(/Type the title/), "Visitor Policy");
  await user.click(confirm);
  await waitFor(() => expect(deleted).toBe(true));
});

test("data and egress page shows the profile and providers", async () => {
  server.use(
    http.get("/api/system/config", () => HttpResponse.json({ settings: { deployment_profile: "hybrid",
      external_max_classification: "internal", chat_retention_days: 30, audit_retention_days: 365,
      synthetic_data_only: true, phi_mode: "redact", llm_provider: "openrouter-free" },
      providers: { "openrouter-free": { name: "openrouter-free", external: true, baa_signed: false, retains_data: true,
                                        region: "us" } }, egress_blocked: [] })),
    http.get("/api/egress", () => HttpResponse.json([])),
  );
  renderApp("/compliance/data", "taylor");
  expect(await screen.findByText("hybrid")).toBeInTheDocument();
  expect(screen.getByText("Keeps prompts")).toBeInTheDocument();
});
