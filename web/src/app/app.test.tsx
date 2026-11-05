// Covers: UX-1, UX-2, UX-4, UX-9, AT-02, AT-07
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "../test/render";
import { mergeChunks } from "../pages/ReaderPage";

test("persona picker lists seven personas with roles", async () => {
  renderApp("/");
  expect(await screen.findByRole("heading", { name: /Choose who you are/ })).toBeInTheDocument();
  const cards = await screen.findAllByRole("button", { name: /Sign in as/ });
  expect(cards).toHaveLength(7);
  expect(screen.getByText("Clinical pharmacist")).toBeInTheDocument();
});

test("signing in as Sam lands on search", async () => {
  const user = userEvent.setup();
  renderApp("/");
  await user.click(await screen.findByRole("button", { name: "Sign in as Sam Lee" }));
  expect(await screen.findByRole("searchbox", { name: "Search approved documents" })).toBeInTheDocument();
});

test("navigation shows only permitted areas", async () => {
  renderApp("/ops", "casey");
  const nav = await screen.findByRole("navigation", { name: "Main" });
  expect(within(nav).queryByRole("link", { name: "Search" })).not.toBeInTheDocument();
  expect(within(nav).getByRole("link", { name: "Operations" })).toBeInTheDocument();
});

test("visiting a page without the role shows a 403 page", async () => {
  renderApp("/compliance", "sam");
  expect(await screen.findByRole("heading", { name: "You don't have access to this page" })).toBeInTheDocument();
});

test("search syncs the URL and renders source cards", async () => {
  const user = userEvent.setup();
  renderApp("/search", "sam");
  const box = await screen.findByRole("searchbox", { name: "Search approved documents" });
  await user.type(box, "alcohol rub{Enter}");
  expect(await screen.findByRole("link", { name: "Hand Hygiene Policy" })).toBeInTheDocument();
  expect(screen.getByText("2 results from documents you can access")).toBeInTheDocument();
  expect(screen.getByLabelText("Version 2")).toBeInTheDocument();
});

test("empty search explains what to do", async () => {
  renderApp("/search?q=nothing+here", "sam");
  expect(await screen.findByText("No approved documents you can access match this.")).toBeInTheDocument();
});

test("slash focuses the search box", async () => {
  const user = userEvent.setup();
  renderApp("/search", "sam");
  const box = await screen.findByRole("searchbox", { name: "Search approved documents" });
  box.blur();
  await user.keyboard("/");
  expect(box).toHaveFocus();
});

test("reader highlights the cited chunk and lists versions", async () => {
  renderApp("/documents/d1?version=v2&chunk=c2", "sam");
  expect(await screen.findByRole("heading", { name: "Hand Hygiene Policy" })).toBeInTheDocument();
  const cited = await screen.findByTestId("chunk-c2");
  expect(cited).toHaveAttribute("data-cited", "true");
  await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
  expect(screen.getByRole("list", { name: "Version history" })).toHaveTextContent("Approved by taylor");
});

test("reader warns on a superseded version", async () => {
  renderApp("/documents/d1?version=v1", "sam");
  expect(await screen.findByText(/This is not the current version/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View version 2" })).toBeInTheDocument();
});

test("mergeChunks removes the overlap between consecutive chunks", () => {
  expect(mergeChunks(["The quick brown fox jumps", "fox jumps over the dog"])).toBe("The quick brown fox jumps over the dog");
  expect(mergeChunks(["No overlap here.", "Second part."])).toBe("No overlap here. Second part.");
});
