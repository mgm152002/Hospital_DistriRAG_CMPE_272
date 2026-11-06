import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { fetchModels, modelName, providersOf, useChatSettings, useSaveChatSettings, withCurrent }
  from "../api/chatSettings";
import type { ChatProviderId } from "../api/types";
import { Button } from "../components/Button";
import { ErrorState, Skeleton } from "../components/States";

export default function SettingsPage() {
  const query = useChatSettings();
  const mutation = useSaveChatSettings();
  const [provider, setProvider] = useState<ChatProviderId>("openrouter-free");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [saved, setSaved] = useState(false);
  const [networkAccess, setNetworkAccess] = useState(true);
  useEffect(() => {
    if (query.data) {
      setProvider(query.data.provider); setModel(query.data.model); setNetworkAccess(query.data.network_access);
    }
  }, [query.data]);
  const other = !!query.data && provider !== query.data.provider;
  const catalog = useQuery({ queryKey: ["chat-models", provider], enabled: other, queryFn: () => fetchModels(provider) });
  useEffect(() => {
    const list = catalog.data?.models;
    if (other && list && !list.some((m) => m.id === model)) setModel(list[0]?.id ?? "");
  }, [catalog.data, other, model]);

  if (query.isLoading) return <Skeleton />;
  if (query.error) return <ErrorState error={query.error} />;
  if (!query.data) return null;
  const data = query.data;
  const providers = providersOf(data);
  const chosen = providers.find((p) => p.id === provider) ?? providers[0];
  const label = chosen?.label ?? provider;
  const configured = chosen?.configured ?? data.key_configured;
  const notice = other ? catalog.data?.catalog_notice : data.catalog_notice;
  const models = withCurrent(other ? catalog.data?.models ?? [] : data.models, model);
  const disabled = !data.can_edit || !!data.airgapped || mutation.isPending;
  const change = <T,>(set: (v: T) => void) => (v: T) => { set(v); setSaved(false); };

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-[1.6rem] font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-ink-soft">{data.can_edit ? "Assistant model and provider" : "Only an administrator can change these."}</p>
      </div>
      <form className="space-y-6 rounded-2xl border border-rule bg-card p-5 shadow-sm" onSubmit={(event) => {
        event.preventDefault(); setSaved(false);
        mutation.mutate({ provider, model, network_access: networkAccess, ...(key.trim() ? { api_key: key.trim() } : {}) },
                        { onSuccess: () => { setKey(""); setSaved(true); } });
      }}>
        <fieldset>
          <legend className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Provider</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {providers.map((p) => (
              <label key={p.id} className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-2.5 transition-colors ${
                provider === p.id ? "border-scrub/50 bg-scrub-wash" : "border-rule hover:border-scrub/40"}`}>
                <input type="radio" name="provider" value={p.id} checked={provider === p.id} disabled={disabled}
                       onChange={() => { change(setProvider)(p.id); if (p.id === data.provider) setModel(data.model); }}
                       className="accent-scrub" />
                <span className="flex-1 text-sm font-semibold">{p.label}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${p.configured ? "bg-ready/12 text-ready" : "bg-bubble text-ink-soft"}`}>
                  {p.configured ? "Ready" : "No key"}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div>
          <label htmlFor="chat-model" className="mb-2 block text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">Model</label>
          <select id="chat-model" value={model} disabled={disabled || !networkAccess || (other && catalog.isLoading)}
            onChange={(event) => change(setModel)(event.target.value)}
            className="w-full rounded-xl py-2.5 pl-3.5 pr-9">
            {models.map((choice) => <option key={choice.id} value={choice.id}>{modelName(choice)}</option>)}
          </select>
          {notice && <p role="status" className="mt-2 text-sm text-ink-soft">{notice}</p>}
          {catalog.error && <div className="mt-2"><ErrorState error={catalog.error} /></div>}
        </div>
        <div>
          <p className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">{label} API key</p>
          <p className="mt-1 text-sm text-ink-soft">{configured ? "Saved on the server." : "Not set."}</p>
          {data.can_edit && <>
            <label htmlFor="chat-api-key" className="mt-3 block text-sm font-medium">Replace API key</label>
            <input id="chat-api-key" type="password" autoComplete="new-password" spellCheck={false}
              value={key} disabled={disabled} maxLength={512} onChange={(event) => change(setKey)(event.target.value)}
              placeholder={configured ? "Leave blank to keep the saved key" : `Paste your ${label} API key`}
              className="mt-1.5 w-full rounded-xl border border-rule bg-card px-3.5 py-2.5 text-sm outline-none placeholder:text-ink-soft focus:border-scrub/60 focus:ring-4 focus:ring-scrub/10" />
          </>}
        </div>
        <div className="border-t border-rule pt-5">
          <label htmlFor="external-network" className="flex items-center gap-3 text-sm font-medium">
            <input id="external-network" type="checkbox" role="switch" checked={networkAccess}
              disabled={disabled} aria-describedby="network-help" className="h-5 w-5 accent-scrub"
              onChange={(event) => change(setNetworkAccess)(event.target.checked)} />
            Allow external AI network access
          </label>
          <p id="network-help" className="mt-1 pl-8 text-sm text-ink-soft">{data.airgapped
            ? "Locked off in air-gapped deployments."
            : `Off blocks ${label} answers. Search still works.`}</p>
        </div>
        {mutation.error && <ErrorState error={mutation.error} />}
        {saved && <p role="status" className="text-sm text-ready">Saved.</p>}
        <Button type="submit" className="rounded-xl" disabled={disabled || !model || (networkAccess && !configured && !key.trim())}>
          {mutation.isPending ? "Saving…" : "Save"}
        </Button>
      </form>
    </div>
  );
}
