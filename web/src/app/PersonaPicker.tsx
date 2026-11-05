import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Persona } from "../api/types";
import { ErrorState, Skeleton } from "../components/States";
import { useHospital, useSession } from "./session";

export function PersonaPicker() {
  const { signIn } = useSession();
  const hospital = useHospital();
  const personas = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/api/personas") });
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <p className="font-serif text-lg text-scrub-deep">DistriRAG{hospital && <> · {hospital.name}</>}</p>
      <h1 className="mt-2 max-w-2xl font-serif text-2xl leading-tight">Choose who you are for this demo</h1>
      <p className="mt-3 max-w-2xl text-ink-soft">
        Each person sees only the hospital documents their role allows. All documents are synthetic.
      </p>
      {personas.isLoading && <div className="mt-8"><Skeleton lines={4} /></div>}
      {personas.error && <div className="mt-8"><ErrorState error={personas.error} /></div>}
      <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {personas.data?.map((p) => (
          <li key={p.user_id}>
            <button
              type="button"
              aria-label={`Sign in as ${p.name}`}
              onClick={() => signIn(p.user_id)}
              className="h-full w-full rounded-lg border border-rule bg-card p-4 text-left hover:border-scrub"
            >
              <span className="block font-serif text-lg font-semibold">{p.name}</span>
              <span className="block text-sm text-ink-soft">{p.role}</span>
              {p.department && <span className="block text-xs text-ink-soft">{p.department}</span>}
              <span className="mt-3 flex flex-wrap gap-1">
                {p.groups.map((g) => <span key={g} className="rounded bg-paper px-1.5 py-0.5 text-xs">{g}</span>)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
