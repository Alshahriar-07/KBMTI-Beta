import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  Moon,
  PlugZap,
  RefreshCw,
  Settings2,
  Sun,
  Unplug,
  Wifi,
  WifiOff,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { usePolling } from "@/hooks/usePolling";
import { ApiError, api } from "@/lib/api";
import { formatAge, formatClock, formatTimeOnly } from "@/lib/format";
import type { ChartSettings, PatronStatus } from "@/lib/types";
import { useMarket } from "@/state/market-context";
import { useTheme } from "@/state/theme-context";
import { cn } from "@/lib/utils";

const TITLES: Record<string, string> = {
  "/": "Overview",
  "/chart": "Market Analysis",
  "/signals": "Signal Research",
  "/chat": "AI Assistant",
  "/history": "Forecasting",
  "/replay": "Replay",
  "/settings": "Settings",
  "/diagnostics": "Model Status",
};

const QUICK_LAYERS: Array<{ key: keyof ChartSettings; label: string }> = [
  { key: "show_ema", label: "EMA" },
  { key: "show_bollinger", label: "BB" },
  { key: "show_volume", label: "VOL" },
  { key: "show_rsi", label: "RSI" },
  { key: "show_macd", label: "MACD" },
];

function Divider() {
  return <span className="h-[18px] w-px shrink-0 bg-line-soft" aria-hidden />;
}

/**
 * One horizontal strip for everything market-related: symbol, timeframe, chart
 * layers, connection, freshness, refresh. No page hero, no wasted vertical space.
 */
export function MarketToolbar({ pathname }: { pathname: string }) {
  const {
    stream,
    settings,
    symbols,
    timeframes,
    selectSymbol,
    selectTimeframe,
    refreshMarket,
    disconnectMarket,
    reconnectMarket,
    providerLabel,
    saveSettings,
  } = useMarket();
  const { theme, toggleTheme } = useTheme();
  const [clock, setClock] = useState(() => new Date());
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const patron = usePolling<PatronStatus>("toolbar-patron", () => api.patronStatus(), 4_000);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const status = stream.status;
  const snapshot = stream.snapshot;
  const symbol = settings?.symbol ?? snapshot?.symbol ?? "—";
  const timeframe = settings?.timeframe ?? snapshot?.timeframe ?? "M15";
  const chart = settings?.chart;
  const connected = status?.connected ?? false;
  const shortProvider = status?.provider === "mt5" ? "MT5" : "Binance";
  const btcSymbols = symbols?.symbols.filter((entry) => entry.btc_like) ?? [];
  const symbolOptions = btcSymbols.length
    ? btcSymbols
    : symbol !== "—"
      ? [{ name: symbol } as { name: string }]
      : [];

  const lastData = snapshot?.tick_time_iso ?? snapshot?.last_update ?? null;
  const lastDataMs = lastData ? new Date(lastData).getTime() : Number.NaN;
  const ageSeconds = Number.isNaN(lastDataMs) ? null : (clock.getTime() - lastDataMs) / 1000;

  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    try {
      await action();
    } finally {
      setBusy(null);
    }
  };

  const toggleLayer = async (key: keyof ChartSettings) => {
    if (!chart) return;
    try {
      await saveSettings({ chart: { [key]: !chart[key] } });
      setActionError(null);
    } catch (cause) {
      setActionError(
        cause instanceof ApiError ? cause.message : "Chart layer setting could not be saved.",
      );
    }
  };

  const toggleAppearance = () => {
    const next = theme === "dark" ? "light" : "dark";
    toggleTheme();
    void saveSettings({ ui: { theme: next } })
      .then(() => setActionError(null))
      .catch((cause) =>
        setActionError(
          cause instanceof ApiError ? cause.message : "Theme preference could not be saved.",
        ),
      );
  };

  const transportLabel =
    stream.transport === "open"
      ? "Live"
      : stream.transport === "connecting"
        ? "Linking"
        : stream.transport === "reconnecting"
          ? "Retry"
          : "Down";

  return (
    <header className="flex h-[50px] shrink-0 items-center gap-2.5 border-b border-line bg-surface px-3.5">
      <h1 className="hidden shrink-0 text-[13.5px] font-semibold tracking-[-0.01em] text-ink min-[1280px]:block">
        {TITLES[pathname] ?? "KBMTI"}
      </h1>
      <Divider />

      <div className="relative shrink-0">
        <label className="sr-only" htmlFor="toolbar-symbol">
          Market symbol
        </label>
        <select
          id="toolbar-symbol"
          value={symbol}
          disabled={!symbolOptions.length}
          onChange={(event) => void run("symbol", () => selectSymbol(event.target.value))}
          className="num h-8 w-[124px] appearance-none rounded-[7px] border border-line bg-surface-2 pr-6 pl-2.5 text-[11px] font-medium text-ink transition-colors duration-150 hover:border-line-strong disabled:opacity-50"
        >
          {symbolOptions.length ? (
            symbolOptions.map((entry) => (
              <option key={entry.name} value={entry.name} className="bg-surface text-ink">
                {entry.name}
              </option>
            ))
          ) : (
            <option value="—">No symbol</option>
          )}
        </select>
        <ChevronDown
          className="pointer-events-none absolute top-1/2 right-1.5 size-3 -translate-y-1/2 text-ink-faint"
          aria-hidden
        />
      </div>

      <Segmented
        ariaLabel="Chart timeframe"
        value={timeframe}
        options={timeframes.map((option) => ({ value: option.value, label: option.value }))}
        onChange={(value) => void run("timeframe", () => selectTimeframe(value))}
        disabled={!connected}
      />

      <Divider />

      <div className="hidden shrink-0 items-center gap-0.5 min-[1360px]:flex">
        {QUICK_LAYERS.map(({ key, label }) => {
          const active = Boolean(chart?.[key]);
          return (
            <button
              key={key}
              type="button"
              aria-pressed={active}
              aria-label={`${active ? "Hide" : "Show"} ${label} on chart`}
              disabled={!chart}
              onClick={() => void toggleLayer(key)}
              className={cn(
                "h-6 rounded-[5px] px-1.5 text-[9.5px] font-medium transition-colors duration-150 disabled:opacity-40",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-ink-faint hover:bg-hover hover:text-ink",
              )}
            >
              {label}
            </button>
          );
        })}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-2.5">
        {actionError && (
          <span title={actionError} className="text-warn">
            <AlertTriangle className="size-3.5" aria-hidden />
            <span className="sr-only">{actionError}</span>
          </span>
        )}

        <Badge
          tone={connected ? "info" : "warning"}
          dot
          title={status?.last_error ?? `${providerLabel} market data status`}
        >
          {shortProvider} {connected ? "live" : "offline"}
        </Badge>

        <Badge
          tone={patron.data?.ready ? "success" : "warning"}
          dot
          className="hidden min-[1240px]:inline-flex"
          title={
            patron.data?.last_error ??
            patron.data?.message ??
            "PATRON numerical forecasting model status"
          }
        >
          PATRON {(patron.data?.state ?? "offline").toLowerCase()}
        </Badge>

        <span
          className="hidden items-center gap-1.5 text-[9.5px] text-ink-faint 2xl:flex"
          title={`Market stream: ${stream.transport}`}
        >
          {stream.transport === "open" ? (
            <Wifi className="size-3 text-primary/80" aria-hidden />
          ) : (
            <WifiOff className="size-3 text-warn/80" aria-hidden />
          )}
          {transportLabel}
        </span>

        <Divider />

        <div className="hidden text-right leading-tight sm:block">
          <p className="num text-[10.5px] text-ink-muted">{formatTimeOnly(lastData)}</p>
          <p className="text-[8.5px] text-ink-faint">{formatAge(ageSeconds)}</p>
        </div>

        <div className="hidden text-right leading-tight 2xl:block">
          <p className="num text-[10.5px] text-ink-muted">{formatClock(clock)}</p>
          <p className="text-[8.5px] text-ink-faint">Local</p>
        </div>

        <Divider />

        <button
          type="button"
          onClick={toggleAppearance}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          className="inline-flex size-7 shrink-0 items-center justify-center rounded-[6px] text-ink-muted transition-colors duration-150 hover:bg-hover hover:text-ink"
        >
          {theme === "dark" ? (
            <Sun className="size-3.5" aria-hidden />
          ) : (
            <Moon className="size-3.5" aria-hidden />
          )}
        </button>

        <Link
          to="/settings"
          aria-label="Open settings"
          title="Settings"
          className="inline-flex size-7 items-center justify-center rounded-[6px] text-ink-muted transition-colors duration-150 hover:bg-hover hover:text-ink"
        >
          <Settings2 className="size-3.5" aria-hidden />
        </Link>

        <Button
          size="sm"
          variant="ghost"
          aria-label="Refresh market data"
          disabled={busy === "refresh"}
          onClick={() => void run("refresh", refreshMarket)}
          icon={<RefreshCw className={cn("size-3.5", busy === "refresh" && "animate-spin")} />}
        />

        {connected ? (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Disconnect from ${providerLabel}`}
            disabled={busy === "disconnect"}
            onClick={() => void run("disconnect", disconnectMarket)}
            icon={<Unplug className="size-3.5" />}
          >
            <span className="hidden 2xl:inline">Detach</span>
          </Button>
        ) : (
          <Button
            size="sm"
            variant="primary"
            disabled={busy === "connect"}
            onClick={() => void run("connect", reconnectMarket)}
            icon={<PlugZap className="size-3.5" />}
          >
            Reconnect {shortProvider}
          </Button>
        )}
      </div>
    </header>
  );
}
