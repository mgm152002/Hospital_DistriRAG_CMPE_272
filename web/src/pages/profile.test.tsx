import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "../test/render";

test("the sidebar names the hospital and opens the profile", async () => {
  const user = userEvent.setup();
  renderApp("/search", "priya");
  const nav = await screen.findByRole("complementary", { name: "Navigation and account" });
  expect(within(nav).getByText("Riverside General Hospital")).toBeInTheDocument();
  expect(within(nav).getByText("Main campus · RGH-001")).toBeInTheDocument();
  await user.click(within(nav).getByRole("link", { name: /Your profile: Dr\. Priya Rao/ }));
  expect(await screen.findByRole("heading", { level: 1, name: "Dr. Priya Rao" })).toBeInTheDocument();
});

test("the profile page shows personal, hospital and access details", async () => {
  renderApp("/profile", "priya");
  await screen.findByRole("heading", { level: 1, name: "Dr. Priya Rao" });
  const main = screen.getByRole("main");
  expect(within(main).getByText("Attending physician")).toBeInTheDocument();
  expect(within(main).getByText("Emergency Medicine")).toBeInTheDocument();
  expect(within(main).getByText("RGH-001")).toBeInTheDocument();
  expect(within(main).getByText("physicians")).toBeInTheDocument();
  expect(within(main).getByRole("link", { name: "Search" })).toHaveAttribute("href", "/search");
  expect(within(main).queryByRole("link", { name: "Admin panel" })).not.toBeInTheDocument();
});

test("the persona picker names the hospital before sign-in", async () => {
  renderApp("/");
  expect(await screen.findByText(/Riverside General Hospital/)).toBeInTheDocument();
});
