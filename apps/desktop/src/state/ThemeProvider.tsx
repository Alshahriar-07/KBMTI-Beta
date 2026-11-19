import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  applyTheme,
  normalizeTheme,
  readStoredTheme,
  type Theme,
} from "@/lib/theme";
import { ThemeContext } from "@/state/theme-context";

function initialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const fromUrl = normalizeTheme(new URLSearchParams(window.location.search).get("theme"));
  return fromUrl ?? readStoredTheme();
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(initialTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    applyTheme(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  }, []);

  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
