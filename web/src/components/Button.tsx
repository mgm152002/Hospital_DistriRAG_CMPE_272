import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "quiet" | "danger";
const styles: Record<Variant, string> = {
  primary: "btn-primary",
  quiet: "bg-card text-ink border border-rule hover:bg-bubble disabled:text-past",
  danger: "bg-failed text-white hover:brightness-90 disabled:bg-past",
};

export function Button({ variant = "primary", className = "", ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${styles[variant]} ${className}`}
    />
  );
}
