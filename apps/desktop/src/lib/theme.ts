export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "kbmti.theme";

export function normalizeTheme(value: unknown): Theme | null {
  return value === "light" || value === "dark" ? value : null;
}

export function readStoredTheme(): Theme {
  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY)) ?? "dark";
  } catch {
    return "dark";
  }
}

/** Apply the theme to the document without remounting the React tree. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  document
    .querySelector('meta[name="color-scheme"]')
    ?.setAttribute("content", theme === "light" ? "light" : "dark");
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "light" ? "#F4F6F8" : "#0B0D0F");
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage is optional; the active theme still applies for this session.
  }
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.has("theme")) {
      url.searchParams.delete("theme");
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    }
  } catch {
    // A malformed URL must never prevent the theme from applying.
  }
}
