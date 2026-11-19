import { AlertTriangle } from "lucide-react";
import { useEffect, useRef } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { MarketToolbar } from "@/components/layout/MarketToolbar";
import { Sidebar } from "@/components/layout/Sidebar";
import { StatusBar } from "@/components/layout/StatusBar";
import { Spinner } from "@/components/ui/Spinner";
import { normalizeTheme } from "@/lib/theme";
import { useMarket } from "@/state/market-context";
import { useTheme } from "@/state/theme-context";

export function AppShell() {
  const location = useLocation();
  const { settings, settingsError, settingsLoading } = useMarket();
  const { setTheme } = useTheme();
  const themeSynced = useRef(false);

  // The backend is the durable source of truth; the URL/localStorage theme is
  // only the pre-paint hint supplied by the native launcher.
  useEffect(() => {
    if (themeSynced.current || !settings) return;
    themeSynced.current = true;
    const stored = normalizeTheme(settings.ui?.theme);
    if (stored) setTheme(stored);
  }, [settings, setTheme]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-app">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <MarketToolbar pathname={location.pathname} />
        {settingsError && (
          <div className="flex shrink-0 items-start gap-2 border-b border-warn/20 bg-warn/[0.04] px-3 py-1.5 text-[10.5px] text-warn/90">
            <AlertTriangle className="mt-[1px] size-3 shrink-0" aria-hidden />
            <p className="leading-relaxed">{settingsError}</p>
          </div>
        )}
        <main className="min-h-0 flex-1 overflow-hidden bg-app">
          {settingsLoading ? (
            <div className="flex h-full items-center justify-center gap-2 text-[10.5px] text-ink-faint">
              <Spinner />
              Connecting to the local backend…
            </div>
          ) : (
            <Outlet />
          )}
        </main>
        <StatusBar />
      </div>
    </div>
  );
}
