import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { docDetail, hits, hospital, me, personas, versionText } from "./fixtures";

export const chatSettings = {
  provider: "openrouter-free", model: "openrouter/free", enabled: true, key_configured: true, can_edit: false,
  network_access: true, catalog_notice: null, free_only: true, airgapped: false, external_max_classification: "internal",
  allowed_hosts: ["openrouter.ai"],
  providers: [{ id: "local-proxy", label: "CLI Proxy", configured: true },
              { id: "openrouter-free", label: "OpenRouter", configured: true }],
  models: [{ id: "openrouter/free", name: "Automatic" }, { id: "vendor/model:free", name: "Example free model" }],
};

export const handlers = [
  http.get("/api/auth/config", () => HttpResponse.json({ mode: "header", registration_enabled: false, demo_accounts: [], hospital })),
  http.get("/api/personas", () => HttpResponse.json(personas)),
  http.get("/api/me", ({ request }) => {
    const user = request.headers.get("X-User-Id");
    if (!user) return HttpResponse.json({ error_code: "unauthenticated", detail: "Sign in" }, { status: 401 });
    return HttpResponse.json(me(user));
  }),
  http.get("/api/conversations", () => HttpResponse.json([])),
  http.get("/api/chat/settings", () => HttpResponse.json(chatSettings)),
  http.get("/api/chat/settings/models", ({ request }) => {
    const provider = new URL(request.url).searchParams.get("provider");
    return HttpResponse.json(provider === "local-proxy"
      ? { models: [{ id: "gpt-6-luna", name: "gpt-6-luna" }], catalog_notice: null }
      : { models: chatSettings.models, catalog_notice: null });
  }),
  http.get("/api/demo/questions", () => HttpResponse.json({ enabled: false, groups: [] })),
  http.get("/api/search", ({ request }) => {
    const q = new URL(request.url).searchParams.get("q") ?? "";
    return HttpResponse.json(q.includes("nothing") ? [] : hits);
  }),
  http.get("/api/documents/:id", () => HttpResponse.json(docDetail)),
  http.get("/api/versions/:vid/text", ({ params }) => HttpResponse.json(versionText(params.vid as string))),
];

export const server = setupServer(...handlers);
