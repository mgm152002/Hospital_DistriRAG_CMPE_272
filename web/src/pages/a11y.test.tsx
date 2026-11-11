// Covers: UX-9 (automated accessibility on the main pages)
import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderApp } from "../test/render";

test("persona picker has no axe violations", async () => {
  const { container } = renderApp("/");
  await screen.findAllByRole("button", { name: /Sign in as/ });
  expect(await axe(container)).toHaveNoViolations();
});

test("search results have no axe violations", async () => {
  const { container } = renderApp("/search?q=alcohol+rub", "sam");
  await screen.findByRole("link", { name: "Hand Hygiene Policy" });
  expect(await axe(container)).toHaveNoViolations();
});

test("reader has no axe violations", async () => {
  const { container } = renderApp("/documents/d1?version=v2&chunk=c2", "sam");
  await screen.findByTestId("chunk-c2");
  expect(await axe(container)).toHaveNoViolations();
});

test("assistant has no axe violations", async () => {
  const { container } = renderApp("/assistant", "sam");
  await screen.findByRole("log");
  expect(await axe(container)).toHaveNoViolations();
});

test("library has no axe violations", async () => {
  server.use(http.get("/api/documents", () => HttpResponse.json([])));
  const { container } = renderApp("/library", "alex");
  await screen.findByText("No documents yet");
  expect(await axe(container)).toHaveNoViolations();
});
