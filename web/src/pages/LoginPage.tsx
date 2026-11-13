import { ArrowRight, Waypoints } from "lucide-react";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useHospital, useSession } from "../app/session";
import { ErrorState } from "../components/States";

export default function LoginPage() {
  const { config, login, register, signIn } = useSession();
  const hospital = useHospital();
  const location = useLocation();
  const registering = location.pathname === "/register";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  if (config?.mode === "oidc") return <main className="mx-auto max-w-xl px-6 py-20">
    <h1 className="text-[1.6rem] font-semibold tracking-tight">Organization sign-in</h1>
    <p className="mt-4 text-ink-soft">Sign in through {hospital ? `${hospital.name}'s` : "your organization's"} identity provider to access this workspace.</p>
  </main>;
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError(null);
    if (registering && password !== confirmation) { setError(new Error("Passwords must match.")); return; }
    setBusy(true);
    try { if (registering) await register(name, email, password); else await login(email, password); }
    catch (failure) { setError(failure); } finally { setBusy(false); }
  }
  async function demo(id: string) {
    setBusy(true); setError(null);
    try { await signIn(id); } catch (failure) { setError(failure); } finally { setBusy(false); }
  }
  const inputClass = "mt-1.5 w-full rounded-xl border border-rule bg-card px-3.5 py-2.5 text-[0.95rem] outline-none focus:border-scrub/60 focus:ring-4 focus:ring-scrub/10";
  return (
    <main className="rail-wash flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-[26rem]">
        <div className="mb-7 flex flex-col items-center text-center">
          <span aria-hidden className="btn-primary grid size-11 place-items-center rounded-xl"><Waypoints size={22} strokeWidth={2.2} /></span>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">
            {registering ? "Create your account" : <>Welcome to Distri<span className="text-scrub">RAG</span></>}
          </h1>
          {hospital && <p className="mt-2 text-sm font-semibold text-scrub-deep">{hospital.name} · {hospital.campus}</p>}
          <p className="mt-1 text-sm text-ink-soft">Answers from your hospital's approved documents.</p>
        </div>
        <div className="rounded-2xl border border-rule bg-card/80 p-6 shadow-xl shadow-black/5 backdrop-blur">
          <form onSubmit={submit} className="space-y-3.5">
            {registering && <label className="block text-sm font-medium">Full name
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required minLength={2} maxLength={100} /></label>}
            <label className="block text-sm font-medium">Email address
              <input className={inputClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required maxLength={254} placeholder="you@hospital.org" /></label>
            <label className="block text-sm font-medium">Password
              <input className={inputClass} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                autoComplete={registering ? "new-password" : "current-password"} required minLength={registering ? 12 : undefined} maxLength={128} /></label>
            {registering && <>
              <label className="block text-sm font-medium">Confirm password
                <input className={inputClass} type="password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="new-password" required maxLength={128} /></label>
              <p className="text-xs text-ink-soft">At least 12 characters.</p>
            </>}
            {error != null && <ErrorState error={error} />}
            <button type="submit" disabled={busy || (registering && !config?.registration_enabled)}
              className="btn-primary flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-semibold">
              {busy ? "Please wait…" : registering ? "Create account" : "Sign in"}
              {!busy && <ArrowRight aria-hidden size={15} />}
            </button>
          </form>
          {!!config?.demo_accounts.length && <section className="mt-6">
            <div className="flex items-center gap-3 text-xs text-ink-soft">
              <span className="h-px flex-1 bg-rule" />or try a demo account<span className="h-px flex-1 bg-rule" />
            </div>
            <div className="mt-3 grid gap-1.5">
              {config.demo_accounts.map((person) => <button key={person.user_id} disabled={busy} onClick={() => demo(person.user_id)}
                aria-label={`Sign in as ${person.name}`}
                className="group flex items-center gap-3 rounded-xl border border-rule bg-paper px-3 py-2 text-left transition-colors hover:border-scrub/40 hover:bg-scrub-wash disabled:opacity-50">
                <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-full bg-bubble text-xs font-bold text-scrub-deep">
                  {person.name.replace(/^Dr\.?\s+/i, "").split(/\s+/).map((w) => w[0]).slice(0, 2).join("")}
                </span>
                <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{person.name}</span>
                  <span className="block truncate text-xs text-ink-soft">{person.role}</span></span>
                <ArrowRight aria-hidden size={14} className="text-ink-soft opacity-0 transition-opacity group-hover:opacity-100" />
              </button>)}
            </div>
          </section>}
        </div>
        <p className="mt-5 text-center text-sm text-ink-soft">{registering ? "Already have an account? " : "New here? "}
          <Link className="font-semibold text-scrub hover:underline" to={registering ? "/login" : "/register"}>{registering ? "Sign in" : "Create an account"}</Link></p>
      </div>
    </main>
  );
}
