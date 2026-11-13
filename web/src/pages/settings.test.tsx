import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { chatSettings, server } from "../test/server";
import { renderApp } from "../test/render";

const settings = { ...chatSettings, can_edit: true };

test("settings shows the provider, its models, and keeps the stored key out of the input", async () => {
  server.use(http.get("/api/chat/settings", () => HttpResponse.json(settings)));
  renderApp("/settings", "alex");
  expect(await screen.findByRole("radio", { name: /OpenRouter/ })).toBeChecked();
  expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("openrouter/free");
  expect(screen.getByText("OpenRouter API key")).toBeInTheDocument();
  expect(screen.getByLabelText("Replace API key")).toHaveValue("");
  expect(screen.getByLabelText("Replace API key")).toHaveAttribute("type", "password");
});

test("changing the model preserves the key when the replacement is blank", async () => {
  let submitted: any;
  server.use(http.get("/api/chat/settings", () => HttpResponse.json(settings)),
    http.put("/api/chat/settings", async ({ request }) => {
      submitted = await request.json();
      return HttpResponse.json({ ...settings, model: submitted.model });
    }));
  const user = userEvent.setup();
  renderApp("/settings", "alex");
  await user.selectOptions(await screen.findByRole("combobox", { name: "Model" }), "vendor/model:free");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Saved.");
  expect(submitted).toEqual({ provider: "openrouter-free", model: "vendor/model:free", network_access: true });
  await waitFor(() => expect(screen.getByLabelText("Replace API key")).toHaveValue(""));
});

test("choosing another provider loads its models and saves its key", async () => {
  let submitted: any;
  server.use(http.get("/api/chat/settings", () => HttpResponse.json(settings)),
    http.put("/api/chat/settings", async ({ request }) => {
      submitted = await request.json();
      return HttpResponse.json({ ...settings, provider: submitted.provider, model: submitted.model });
    }));
  const user = userEvent.setup();
  renderApp("/settings", "alex");
  await user.click(await screen.findByRole("radio", { name: /CLI Proxy/ }));
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("gpt-6-luna"));
  expect(screen.getByText("CLI Proxy API key")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Replace API key"), "secret");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Saved.");
  expect(submitted).toEqual({ provider: "local-proxy", model: "gpt-6-luna", network_access: true, api_key: "secret" });
});

test("staff can view settings while changes require an administrator", async () => {
  server.use(http.get("/api/chat/settings", () => HttpResponse.json({ ...settings, can_edit: false })));
  renderApp("/settings", "sam");
  expect(await screen.findByRole("combobox", { name: "Model" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.queryByLabelText("Replace API key")).not.toBeInTheDocument();
});

test("a catalog outage notice is shown", async () => {
  server.use(http.get("/api/chat/settings", () => HttpResponse.json({ ...settings,
    models: settings.models.slice(0, 1), catalog_notice: "The model list is unavailable. Try the automatic free router." })));
  renderApp("/settings", "alex");
  expect(await screen.findByText(/The model list is unavailable/)).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("openrouter/free");
});

test("network can be switched off without supplying an API key", async () => {
  let submitted: any;
  const noKey = { ...settings, key_configured: false,
    providers: settings.providers.map((p) => ({ ...p, configured: p.id !== "openrouter-free" })) };
  server.use(http.get("/api/chat/settings", () => HttpResponse.json(noKey)),
    http.put("/api/chat/settings", async ({ request }) => {
      submitted = await request.json();
      return HttpResponse.json({ ...noKey, ...submitted });
    }));
  const user = userEvent.setup();
  renderApp("/settings", "alex");
  const save = await screen.findByRole("button", { name: "Save" });
  expect(save).toBeDisabled();
  await user.click(screen.getByRole("switch", { name: "Allow external AI network access" }));
  expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();
  await user.click(save);
  await screen.findByText("Saved.");
  expect(submitted.network_access).toBe(false);
});

test("airgapped deployments keep the network switch locked off", async () => {
  server.use(http.get("/api/chat/settings", () => HttpResponse.json({ ...settings, airgapped: true, network_access: false })));
  renderApp("/settings", "alex");
  const network = await screen.findByRole("switch", { name: "Allow external AI network access" });
  expect(network).toBeDisabled();
  expect(network).not.toBeChecked();
});
