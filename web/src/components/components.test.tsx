// Covers: UX-2, UX-3, UX-4, UX-9, CP-9 (design system components and accessibility)
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { ClassificationBadge, StatusBadge, VersionStamp } from "./Badge";
import { Button } from "./Button";
import { ConfidenceMeter } from "./ConfidenceMeter";
import { EmptyState, ErrorState } from "./States";
import { GuardrailReceipt } from "./GuardrailReceipt";
import { ProgressBar } from "./ProgressBar";
import { SafetyBanner } from "./SafetyBanner";
import { SourceCard } from "./SourceCard";
import { Stepper } from "./Stepper";
import type { Receipt, SearchHit } from "../api/types";

const SNIPPET = "Rub all surfaces of both hands with alcohol-based hand rub for 20 to 30 seconds until dry.";
const hit: SearchHit = {
  chunk_id: "c1", document_id: "d1", version_id: "v2", title: "Hand Hygiene Policy", version_number: 2,
  category: "Infection Control", department: "Infection Prevention", classification: "internal",
  section: "Hand Hygiene Policy > Alcohol-based hand rub", page: 1, score: 0.92,
  snippet: SNIPPET,
  highlights: [[SNIPPET.indexOf("alcohol"), SNIPPET.indexOf("alcohol") + 7], [SNIPPET.indexOf("20"), SNIPPET.indexOf("20") + 4]],
};

const receipt: Receipt = {
  classification: "clinical_reference", phi_redacted: false, provider: "local-ollama", model: "qwen",
  external: false, egress_decision: "local", passages_withheld: {}, fallback: null, latency_ms: 812,
  checks: { citations: "pass", clinical: "pass", injection: "stripped" }, cached: false,
};

test("status badge names the state in plain words", () => {
  render(<StatusBadge status="PENDING_APPROVAL" />);
  expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
});

test("version stamp shows the version large and its label", () => {
  render(<VersionStamp version={2} />);
  expect(screen.getByLabelText("Version 2")).toHaveTextContent("v2");
});

test("restricted classification is announced", () => {
  render(<ClassificationBadge value="restricted" />);
  expect(screen.getByText("Restricted")).toBeInTheDocument();
});

test("source card marks highlights without injecting HTML", async () => {
  const { container } = render(<MemoryRouter><SourceCard hit={hit} index={1} /></MemoryRouter>);
  const marks = container.querySelectorAll("mark");
  expect([...marks].map((m) => m.textContent)).toEqual(["alcohol", "20 t"]);
  expect(screen.getByRole("link", { name: /Hand Hygiene Policy/ })).toHaveAttribute(
    "href", "/documents/d1?version=v2&chunk=c1");
  expect(await axe(container)).toHaveNoViolations();
});

test("source card shows score as a percentage", () => {
  render(<MemoryRouter><SourceCard hit={hit} index={1} /></MemoryRouter>);
  expect(screen.getByText("92% match")).toBeInTheDocument();
});

test("confidence meter shows band and explains parts", async () => {
  const user = userEvent.setup();
  render(<ConfidenceMeter score={82} band="High" parts={{ r: 0.86, c: 1, a: 1 }} />);
  expect(screen.getByText("82")).toBeInTheDocument();
  expect(screen.getByText("High confidence")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "How this is scored" }));
  expect(screen.getByText(/Retrieval strength/)).toBeInTheDocument();
});

test("guardrail receipt lists checks", () => {
  render(<GuardrailReceipt receipt={receipt} />);
  expect(screen.getByText("Prompt-injection text removed from a source")).toBeInTheDocument();
  expect(screen.getByText("Answered by local model; nothing left the network")).toBeInTheDocument();
});

test("emergency banner is an alert", () => {
  render(<SafetyBanner variant="emergency">Activate the team</SafetyBanner>);
  expect(screen.getByRole("alert")).toHaveTextContent("Activate the team");
});

test("progress bar exposes values", () => {
  render(<ProgressBar value={24} max={40} label="Embedding" />);
  const bar = screen.getByRole("progressbar", { name: "Embedding" });
  expect(bar).toHaveAttribute("aria-valuenow", "24");
});

test("stepper marks the current step", () => {
  render(<Stepper steps={["Extract", "Chunk", "Embed"]} current={1} />);
  expect(screen.getByText("Chunk").closest("li")).toHaveAttribute("aria-current", "step");
});

test("button disabled state and tooltip", () => {
  render(<Button disabled title="You uploaded this version">Approve</Button>);
  expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
});

test("empty and error states give direction", () => {
  render(<><EmptyState title="No results">Try other words.</EmptyState><ErrorState error={new Error("boom")} /></>);
  expect(screen.getByText("Try other words.")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("boom");
});
