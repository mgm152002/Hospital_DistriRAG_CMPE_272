import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { me } from "../test/fixtures";
import { renderApp } from "../test/render";

function local(initiallySignedIn = false) {
  let loggedIn = initiallySignedIn;
  server.use(
    http.get("/api/auth/config", () => HttpResponse.json({ mode: "local", registration_enabled: true,
      demo_accounts: [{ user_id: "alex", name: "Alex Morgan", role: "Knowledge administrator", groups: ["doc-admins"] }] })),
    http.get("/api/me", () => loggedIn ? HttpResponse.json(me("sam")) : HttpResponse.json({}, { status: 401 })),
    http.post("/api/auth/login", () => { loggedIn = true; return HttpResponse.json({ user_id: "sam" }); }),
    http.post("/api/auth/register", () => { loggedIn = true; return HttpResponse.json({ user_id: "sam" }, { status: 201 }); }),
    http.post("/api/auth/logout", () => { loggedIn = false; return new HttpResponse(null, { status: 204 }); }),
  );
}

test("login screen shows email sign-in and demo accounts", async () => {
  local(); renderApp("/");
  expect(await screen.findByRole("heading", { name: /Welcome to Distri/ })).toBeInTheDocument();
  expect(screen.getByLabelText("Email address")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sign in as Alex Morgan" })).toBeInTheDocument();
});

test("a restored cookie session can log out after a browser reload", async () => {
  local(true); renderApp("/");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("heading", { name: /Welcome to Distri/ })).toBeInTheDocument();
});

test("OIDC mode bootstraps the current identity without a demo user in local storage", async () => {
  server.use(http.get("/api/auth/config", () => HttpResponse.json({ mode: "oidc", registration_enabled: false, demo_accounts: [] })),
    http.get("/api/me", () => HttpResponse.json(me("sam"))));
  renderApp("/");
  expect(await screen.findByRole("searchbox", { name: "Search approved documents" })).toBeInTheDocument();
});

test("staff can register and enter the authenticated app", async () => {
  local(); renderApp("/register");
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Full name"), "New Staff");
  await user.type(screen.getByLabelText("Email address"), "staff@example.test");
  await user.type(screen.getByLabelText("Password"), "a strong password");
  await user.type(screen.getByLabelText("Confirm password"), "a strong password");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(await screen.findByRole("searchbox", { name: "Search approved documents" })).toBeInTheDocument();
});
