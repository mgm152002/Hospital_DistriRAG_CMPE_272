import { useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";
const KEY = "distrirag-theme";

function stored(): Theme {
  try {
    const value = window.localStorage?.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

/** Light, dark or follow the system; remembered on this device. */
export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(stored);
  useEffect(() => {
    applyTheme(theme);
    try { window.localStorage?.setItem(KEY, theme); } catch { /* private mode */ }
  }, [theme]);
  return [theme, setTheme];
}

applyTheme(typeof window === "undefined" ? "system" : stored());
