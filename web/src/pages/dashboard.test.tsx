import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderApp } from "../test/render";
import { docDetail } from "../test/fixtures";

test("admin dashboard renders live analytics and document actions", async () => {
  server.use(http.get("/api/admin/analytics", () => HttpResponse.json({
    counts: { documents: 24, published: 22, pending_approval: 2, processing: 0, failed: 0, versions: 28, users: 7, searches: 35, questions: 10 },
    categories: [{ name: "Infection Control", count: 3 }], statuses: [],
    usage: [{ date: "2026-11-25", searches: 35, questions: 10 }], activity: [],
  })));
  renderApp("/admin", "alex");
  expect(await screen.findByText("22 currently published")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Knowledge control center" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload document" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review queue (2)" })).toBeInTheDocument();
});

test("version manager renders superseded and current versions with differences", async () => {
  server.use(http.get("/api/documents/d1", () => HttpResponse.json(docDetail)),
    http.get("/api/admin/documents/d1/compare", () => HttpResponse.json({ added: 1, removed: 1,
      lines: [{ kind: "removed", text: "Rub for 15 seconds." }, { kind: "added", text: "Rub for 20 to 30 seconds." }] })));
  renderApp("/admin/documents/d1", "alex");
  expect(await screen.findByRole("heading", { name: "Hand Hygiene Policy" })).toBeInTheDocument();
  expect(await screen.findByLabelText("Version changes")).toHaveTextContent("Rub for 20 to 30 seconds.");
  expect(screen.getByText("Published version")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload new version" })).toBeInTheDocument();
});
