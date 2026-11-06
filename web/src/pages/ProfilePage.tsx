import { Building2, IdCard, KeyRound, LogOut, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { initials } from "../app/Shell";
import { AREAS, canUse, useHospital, useSession, type Area } from "../app/session";

const GROUPS: Record<string, string> = {
  "all-staff": "Documents released to every member of staff",
  clinical: "Clinical policies and procedures",
  physicians: "Physician-only clinical references",
  nursing: "Nursing procedures and care standards",
  pharmacy: "Medication and pharmacy references",
  "doc-admins": "Uploads and manages the document library",
  compliance: "Approves documents and reviews the audit trail",
  operators: "Runs the platform and its processing pipeline",
};

const PROFILES: Record<string, string> = {
  lite: "Lite (no models)", airgapped: "Air-gapped", hybrid: "Hybrid", cloud: "Cloud",
};

function Section({ title, icon: Icon, children }: { title: string; icon: typeof IdCard; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-rule bg-card p-5 shadow-sm">
      <h2 className="mb-4 flex items-center gap-2 text-[0.7rem] font-semibold uppercase tracking-wider text-ink-soft">
        <Icon aria-hidden size={14} className="text-scrub" />{title}
      </h2>
      {children}
    </section>
  );
}

function Field({ label, value }: { label: string; value?: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-soft">{label}</dt>
      <dd className="mt-0.5 break-words text-sm font-medium text-ink">{value || <span className="text-ink-soft">Not set</span>}</dd>
    </div>
  );
}

export default function ProfilePage() {
  const { me, signOut, config } = useSession();
  const hospital = useHospital();
  if (!me) return null;
  const areas = (Object.keys(AREAS) as Area[]).filter((a) => canUse(me, a));
  const since = me.member_since
    ? new Date(me.member_since).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : null;
  const account = config?.mode === "local" ? (me.is_demo ? "Demo account" : "Local account")
    : config?.mode === "oidc" ? "Organization single sign-on" : "Demo persona";

  return (
    <div className="max-w-3xl space-y-6">
      <header className="flex flex-wrap items-center gap-4">
        <span aria-hidden className="btn-primary grid size-16 shrink-0 place-items-center rounded-full text-xl font-bold">
          {initials(me.name)}
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight">{me.name}</h1>
          <p className="text-sm text-ink-soft">
            {[me.role, me.department, hospital?.name].filter(Boolean).join(" · ")}
          </p>
        </div>
        <button type="button" onClick={signOut}
                className="flex items-center gap-2 rounded-lg border border-rule px-3 py-1.5 text-sm text-ink-soft hover:bg-bubble hover:text-ink">
          <LogOut aria-hidden size={14} />{config?.mode === "local" ? "Sign out" : "Switch person"}
        </button>
      </header>

      <Section title="Personal details" icon={IdCard}>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Field label="Full name" value={me.name} />
          <Field label="Job title" value={me.role} />
          <Field label="Department" value={me.department} />
          <Field label="Email" value={me.email} />
          <Field label="User ID" value={<code className="text-[0.8rem]">{me.user_id}</code>} />
          <Field label="Account type" value={account} />
          {since && <Field label="Member since" value={since} />}
        </dl>
      </Section>

      <Section title="Hospital" icon={Building2}>
        {hospital ? (
          <dl className="grid gap-4 sm:grid-cols-3">
            <Field label="Hospital" value={hospital.name} />
            <Field label="Campus" value={hospital.campus} />
            <Field label="Facility code" value={<code className="text-[0.8rem]">{hospital.code}</code>} />
          </dl>
        ) : <p className="text-sm text-ink-soft">No hospital is configured for this deployment.</p>}
      </Section>

      <Section title="Access" icon={KeyRound}>
        <h3 className="text-xs text-ink-soft">Groups</h3>
        <ul className="mt-2 space-y-2">
          {me.groups.map((g) => (
            <li key={g} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
              <span className="rounded-full bg-scrub/10 px-2.5 py-0.5 text-xs font-medium text-scrub-deep">{g}</span>
              <span className="text-sm text-ink-soft">{GROUPS[g] ?? "Custom group"}</span>
            </li>
          ))}
        </ul>
        {me.roles.length > 0 && (
          <p className="mt-4 text-sm"><span className="text-ink-soft">Administrative roles: </span>{me.roles.join(", ")}</p>
        )}
        <h3 className="mt-5 text-xs text-ink-soft">Areas you can open</h3>
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {areas.map((a) => (
            <li key={a}>
              <Link to={AREAS[a].path} className="block rounded-lg border border-rule px-2.5 py-1 text-sm hover:border-scrub/50 hover:bg-bubble">
                {AREAS[a].label}
              </Link>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Assistant" icon={Sparkles}>
        <dl className="grid gap-4 sm:grid-cols-3">
          <Field label="Deployment" value={PROFILES[me.profile] ?? me.profile} />
          <Field label="Language model" value={me.llm_model ? `${me.llm_provider} · ${me.llm_model}` : me.llm_provider} />
          <Field label="Runs" value={me.llm_external ? "External provider" : "Inside the hospital network"} />
        </dl>
      </Section>
    </div>
  );
}
