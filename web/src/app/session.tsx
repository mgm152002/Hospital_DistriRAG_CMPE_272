import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, postJson, session } from "../api/client";
import type { Hospital, Me, Persona } from "../api/types";

interface AuthConfig {
  mode: "local" | "header" | "oidc"; registration_enabled: boolean; demo_accounts: Persona[]; hospital?: Hospital;
}
interface SessionValue {
  me: Me | null; loading: boolean; config?: AuthConfig;
  signIn: (userId: string) => Promise<void>; signOut: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
}
const noop = async () => {};
const SessionContext = createContext<SessionValue>({ me: null, loading: false, signIn: noop, signOut: noop,
                                                  login: noop, register: noop });

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [userId, setUserId] = useState(session.get());
  const [authGeneration, setAuthGeneration] = useState(0);
  const client = useQueryClient();
  const navigate = useNavigate();
  // A new identity starts at its own home page: the previous person's URL (a private conversation, an admin page)
  // must not be reopened under the next account.
  const home = () => navigate("/", { replace: true });
  const config = useQuery({ queryKey: ["auth-config"], queryFn: () => api<AuthConfig>("/api/auth/config"), staleTime: Infinity });
  const mode = config.data?.mode;
  const query = useQuery({ queryKey: ["me", userId, authGeneration], queryFn: () => api<Me>("/api/me"),
                           enabled: mode === "local" || mode === "oidc" || (mode === "header" && !!userId), retry: false });
  const clearPrivate = () => client.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth-config" });
  const authenticated = (id: string) => { session.clear(); clearPrivate(); home(); setUserId(id); setAuthGeneration((n) => n+1); };
  const value: SessionValue = {
    me: mode === "local" || mode === "oidc" || userId ? query.data ?? null : null,
    loading: config.isLoading || ((mode === "local" || mode === "oidc" || !!userId) && query.isLoading), config: config.data,
    signIn: async (id) => {
      if (mode === "local") { await postJson(`/api/auth/demo/${id}`, {}); authenticated(id); }
      else { session.set(id); clearPrivate(); home(); setUserId(id); }
    },
    signOut: async () => {
      if (mode === "local") await postJson("/api/auth/logout", {});
      session.clear(); clearPrivate(); home(); setUserId(null); setAuthGeneration((n) => n+1);
    },
    login: async (email, password) => {
      const result = await postJson<{ user_id: string }>("/api/auth/login", { email, password });
      authenticated(result.user_id);
    },
    register: async (name, email, password) => {
      const result = await postJson<{ user_id: string }>("/api/auth/register", { name, email, password });
      authenticated(result.user_id);
    },
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext);

export const AREAS = {
  admin: { label: "Admin panel", path: "/admin", groups: ["doc-admins", "compliance"] },
  search: { label: "Search", path: "/search", groups: ["all-staff"] },
  assistant: { label: "Assistant", path: "/assistant", groups: ["all-staff"] },
  library: { label: "Library", path: "/library", groups: ["doc-admins"] },
  compliance: { label: "Compliance", path: "/compliance", groups: ["compliance"] },
  operations: { label: "Operations", path: "/ops", groups: ["operators", "doc-admins"] },
  settings: { label: "Settings", path: "/settings", groups: ["all-staff", "operators", "doc-admins", "compliance"] },
} as const;
export type Area = keyof typeof AREAS;

/** The hospital name to show: from the signed-in profile, else the public sign-in config. */
export function useHospital(): Hospital | undefined {
  const { me, config } = useSession();
  return me?.hospital ?? config?.hospital;
}

export function canUse(me: Me | null, area: Area) {
  return !!me && AREAS[area].groups.some((g) => me.groups.includes(g));
}

export function homeFor(me: Me): string {
  if (canUse(me, "admin")) return "/admin";
  if (canUse(me, "search")) return "/search";
  return "/ops";
}
