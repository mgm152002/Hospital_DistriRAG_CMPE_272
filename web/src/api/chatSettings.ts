import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { ChatModel, ChatModels, ChatProvider, ChatProviderId, ChatSettings } from "./types";

export const CHAT_SETTINGS = ["chat-settings"] as const;

const LABELS: Record<ChatProviderId, string> = { "local-proxy": "CLI Proxy", "openrouter-free": "OpenRouter" };
export const providerLabel = (id: string) => LABELS[id as ChatProviderId] ?? id;

/** Older servers send no provider list; fall back to the active provider and the known pair. */
export function providersOf(s: ChatSettings): ChatProvider[] {
  if (s.providers?.length) return s.providers;
  return (Object.keys(LABELS) as ChatProviderId[]).map((id) => (
    { id, label: LABELS[id], configured: id === s.provider ? s.key_configured || id === "local-proxy" : false }));
}

export const modelName = (m: ChatModel) => m.name || m.id;

/** The models for a picker: the catalog, with the saved choice kept visible if the catalog no longer lists it. */
export function withCurrent(models: ChatModel[], current: string): ChatModel[] {
  return !current || models.some((m) => m.id === current) ? models : [{ id: current, name: current }, ...models];
}

export const fetchModels = (provider: string) =>
  api<ChatModels>(`/api/chat/settings/models?provider=${encodeURIComponent(provider)}`);

export function useChatSettings(enabled = true) {
  return useQuery({ queryKey: CHAT_SETTINGS, enabled, queryFn: () => api<ChatSettings>("/api/chat/settings") });
}

export function useSaveChatSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<ChatSettings>("/api/chat/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    onSuccess: (data) => {
      client.setQueryData(CHAT_SETTINGS, data);
      client.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
