import { useEffect, useState } from "react";
import {
  Check,
  Database,
  PlugZap,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldCheck,
  SunMoon,
  Wifi,
  WifiOff,
} from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataRow } from "@/components/ui/DataRow";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { Toggle } from "@/components/ui/Toggle";
import { ApiError } from "@/lib/api";
import { formatBrokerTime, formatDuration } from "@/lib/format";
import { normalizeTheme } from "@/lib/theme";
import type { AppSettings, ChartSettings, MarketProvider } from "@/lib/types";
import { useMarket } from "@/state/market-context";
import { useTheme } from "@/state/theme-context";
import { cn } from "@/lib/utils";

const CHART_TOGGLES: Array<{ key: keyof ChartSettings; label: string; description: string }> = [
  { key: "show_ema", label: "EMA 9 / 21 / 50", description: "Overlay exponential moving averages" },
  { key: "show_bollinger", label: "Bollinger bands", description: "20-period, 2 standard deviations" },
  { key: "show_volume", label: "Market volume", description: "Histogram from the selected provider" },
  { key: "show_rsi", label: "RSI 14 pane", description: "Wilder relative strength index" },
  { key: "show_macd", label: "MACD pane", description: "12 / 26 / 9 momentum study" },
  { key: "crosshair", label: "Crosshair magnet", description: "Snap the crosshair to OHLC values" },
];

const PROVIDERS: Array<{
  id: MarketProvider;
  label: string;
  role: string;
  description: string;
}> = [
  {
    id: "binance",
    label: "Binance",
    role: "Recommended / Primary",
    description: "Public BTCUSDT spot data. No API key.",
  },
  {
    id: "mt5",
    label: "MetaTrader 5",
    role: "Optional",
    description: "Your broker terminal and broker-specific BTC symbol.",
  },
];

export function SettingsPage() {
  const {
    settings,
    timeframes,
    symbols,
    provider,
    providerLabel,
    saveSettings,
    reloadSettings,
    selectProvider,
    reconnectMarket,
  } = useMarket();
  const { theme, setTheme } = useTheme();
  const [draft, setDraft] = useState<AppSettings | null>(settings);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [terminalPath, setTerminalPath] = useState("");

  useEffect(() => {
    setDraft(settings);
    setTerminalPath(settings?.mt5.terminal_path ?? "");
  }, [settings]);

  if (!draft) {
    return (
      <p className="p-4 text-[10.5px] text-ink-faint">
        Settings are not available until the local backend connects.
      </p>
    );
  }

  const setChart = (key: keyof ChartSettings, value: boolean) => {
    setDraft({ ...draft, chart: { ...draft.chart, [key]: value } });
  };

  const market = draft.market;
  const mt5 = draft.mt5;
  const selectedProvider = (draft.provider ?? provider) as MarketProvider;
  const btcSymbols = (symbols?.symbols ?? []).filter((entry) => entry.btc_like);
  const symbolOptions = btcSymbols.length
    ? btcSymbols
    : draft.symbol
      ? [{ name: draft.symbol }]
      : [];
  const providerConnected = Boolean(market?.connected);
  const freshness = market?.freshness ?? "unavailable";

  const run = async (key: string, action: () => Promise<unknown>, success?: string) => {
    setBusy(key);
    setError(null);
    setStatus(null);
    try {
      await action();
      if (success) setStatus(success);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The action could not be completed.");
    } finally {
      setBusy(null);
    }
  };

  const chooseProvider = (next: MarketProvider) => {
    if (next === selectedProvider) return;
    setDraft({ ...draft, provider: next });
    void run(
      "provider",
      () => selectProvider(next),
      next === "binance"
        ? "Binance selected. Loading public BTC market data."
        : "MetaTrader 5 selected. Checking the terminal attachment.",
    );
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      await saveSettings({
        chart: draft.chart,
        candle_limit: draft.candle_limit,
        timeframe: draft.timeframe,
        symbol: draft.symbol ?? undefined,
      });
      setStatus("Settings saved to local SQLite.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save settings.");
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setSaving(true);
    try {
      await reloadSettings();
      setStatus("Reloaded from the backend.");
    } finally {
      setSaving(false);
    }
  };

  const chooseTheme = (value: string) => {
    const next = normalizeTheme(value);
    if (!next || next === theme) return;
    setTheme(next);
    setError(null);
    setStatus(null);
    void saveSettings({ ui: { theme: next } })
      .then(() => setStatus(`${next === "dark" ? "Dark" : "Light"} theme saved.`))
      .catch((cause) =>
        setError(
          cause instanceof ApiError ? cause.message : "The theme could not be saved to the backend.",
        ),
      );
  };

  const applyTerminalPath = () =>
    run(
      "terminal",
      () =>
        saveSettings({
          mt5: { terminal_path: terminalPath.trim() || null },
        }),
      terminalPath.trim() ? "Manual terminal path saved." : "Terminal path reset to auto-detect.",
    );

  return (
    <div className="scroll-area h-full">
      <div className="grid gap-3 p-3 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
        <div className="flex flex-col gap-3 self-start">
          <Panel
            title="Appearance"
            icon={<SunMoon className="size-3.5" />}
            meta="saved to this workstation"
            bodyClassName="px-3 py-3"
          >
            <p className="label-xs mb-1.5">Interface theme</p>
            <Segmented
              ariaLabel="Interface theme"
              size="md"
              value={theme}
              options={[
                { value: "dark", label: "Dark" },
                { value: "light", label: "Light" },
              ]}
              onChange={chooseTheme}
            />
            <p className="mt-2 text-[9px] leading-relaxed text-ink-faint">
              Applies immediately across every page, chart, dialog and forecast preview. The
              selection is restored automatically on the next launch.
            </p>
          </Panel>

          <Panel
            title="Chart layers"
            icon={<Settings2 className="size-3.5" />}
            meta="stored locally"
            actions={<Badge tone="muted">{draft.timeframe}</Badge>}
            bodyClassName="px-3 py-1"
          >
            {CHART_TOGGLES.map(({ key, label, description }) => (
              <Toggle
                key={key}
                label={label}
                description={description}
                checked={Boolean(draft.chart[key])}
                onChange={(value) => setChart(key, value)}
              />
            ))}
            <p className="py-2.5 text-[9px] leading-relaxed text-ink-faint">
              Indicators are computed server-side from the same {providerLabel} candles rendered
              on the chart. RSI and MACD open dedicated panes; the selected provider is the only
              data source.
            </p>
          </Panel>
        </div>

        <div className="flex flex-col gap-3">
          <Panel
            title="Market data"
            icon={<Database className="size-3.5" />}
            meta="single source of truth"
            actions={
              <Badge tone={providerConnected ? "info" : "warning"} dot>
                {providerConnected ? freshness : "offline"}
              </Badge>
            }
            bodyClassName="p-0"
          >
            <div className="border-b border-line-soft p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="label-xs">Provider</p>
                <span className="text-[9px] text-ink-faint">
                  {selectedProvider === "binance" ? "Primary · no API key" : "Optional · local IPC"}
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {PROVIDERS.map((option) => {
                  const active = selectedProvider === option.id;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      disabled={busy === "provider"}
                      aria-pressed={active}
                      onClick={() => chooseProvider(option.id)}
                      className={cn(
                        "min-w-0 rounded-[8px] border px-2.5 py-2 text-left transition-colors duration-150 disabled:opacity-60",
                        active
                          ? "border-primary/30 bg-primary/[0.07]"
                          : "border-line bg-surface hover:border-line-strong hover:bg-surface-2",
                      )}
                    >
                      <span className="flex items-center gap-1.5">
                        <span
                          className={cn(
                            "size-1.5 rounded-full",
                            active ? "bg-primary" : "bg-line-strong",
                          )}
                        />
                        <span className="text-[10.5px] font-semibold text-ink">{option.label}</span>
                        <span className="ml-auto text-[9px] font-medium text-primary-deep">
                          {active ? "Selected" : ""}
                        </span>
                      </span>
                      <span className="mt-1 block text-[9px] leading-snug text-ink-faint">
                        {option.role} · {option.description}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <DataRow
              label="Connection"
              value={market?.state_label ?? (providerConnected ? "Connected" : "Disconnected")}
              toneClassName={providerConnected ? "text-primary-deep" : "text-warn"}
              hint={
                selectedProvider === "binance"
                  ? market?.ws_connected
                    ? "REST + WebSocket"
                    : "REST only"
                  : undefined
              }
            />
            <DataRow label="Selected symbol" value={market?.selected_symbol ?? draft.symbol ?? "—"} />
            <DataRow label="Last update" value={formatBrokerTime(market?.last_successful_update, true)} />
            <DataRow
              label="Data freshness"
              value={freshness}
              toneClassName={freshness === "fresh" ? "text-primary-deep" : freshness === "stale" ? "text-warn" : undefined}
            />
            <DataRow
              label="WebSocket"
              value={market?.ws_connected ? "Connected" : "Disconnected"}
              toneClassName={market?.ws_connected ? "text-primary-deep" : "text-warn"}
            />
            {market?.last_error && (
              <div className="border-b border-warn/20 bg-warn/[0.05] px-3 py-2 text-[9.5px] leading-relaxed text-warn/90">
                {market.last_error}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2 p-3">
              <Button
                variant="primary"
                size="sm"
                disabled={busy === "reconnect"}
                onClick={() =>
                  void run("reconnect", reconnectMarket, `Reconnecting ${providerLabel}…`)
                }
                icon={<RefreshCw className={cn("size-3.5", busy === "reconnect" && "animate-spin")} />}
              >
                Reconnect {providerLabel}
              </Button>
              <span className="inline-flex items-center gap-1.5 text-[9px] text-ink-faint">
                {providerConnected ? (
                  <Wifi className="size-3 text-primary" aria-hidden />
                ) : (
                  <WifiOff className="size-3 text-warn" aria-hidden />
                )}
                Failures never switch provider automatically.
              </span>
            </div>
          </Panel>

          <Panel
            title="Symbol, timeframe & history"
            icon={<Settings2 className="size-3.5" />}
            meta={`${providerLabel} · stored locally`}
            bodyClassName="px-3 py-3"
          >
            <div className="space-y-3">
              <div>
                <p className="label-xs mb-1.5">Default timeframe</p>
                <Segmented
                  ariaLabel="Default timeframe"
                  size="md"
                  value={draft.timeframe}
                  options={timeframes.map((item) => ({ value: item.value, label: item.value }))}
                  onChange={(value) => setDraft({ ...draft, timeframe: value })}
                />
              </div>

              <div>
                <label htmlFor="settings-symbol" className="label-xs mb-1.5 block">
                  {selectedProvider === "binance" ? "Binance spot symbol" : "BTC broker symbol"}
                </label>
                <select
                  id="settings-symbol"
                  value={draft.symbol ?? ""}
                  onChange={(event) => setDraft({ ...draft, symbol: event.target.value })}
                  className="field num"
                >
                  {!symbolOptions.length && !draft.symbol && (
                    <option value="">
                      {selectedProvider === "binance" ? "BTCUSDT" : "No broker symbol selected"}
                    </option>
                  )}
                  {symbolOptions.map((entry) => (
                    <option key={entry.name} value={entry.name} className="bg-surface">
                      {entry.name}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-[9px] leading-relaxed text-ink-faint">
                  {selectedProvider === "binance"
                    ? "Public Binance Spot BTC pairs. BTCUSDT is selected automatically on first launch."
                    : "Symbols are discovered from the running MT5 terminal, including broker suffixes."}
                </p>
              </div>

              <div>
                <p className="label-xs mb-1.5">Candles loaded</p>
                <Segmented
                  ariaLabel="Candle limit"
                  size="md"
                  value={String(draft.candle_limit)}
                  options={["200", "300", "500", "800", "1000"].map((value) => ({
                    value,
                    label: value,
                  }))}
                  onChange={(value) => setDraft({ ...draft, candle_limit: Number(value) })}
                />
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line-soft pt-3">
              <Button
                variant="primary"
                onClick={() => void save()}
                disabled={saving || busy === "provider"}
                icon={<Check className="size-3.5" />}
              >
                {saving ? "Saving…" : "Save settings"}
              </Button>
              <Button
                variant="ghost"
                onClick={() => void reset()}
                disabled={saving}
                icon={<RotateCcw className="size-3.5" />}
              >
                Reload
              </Button>
              {status && <span className="text-[9.5px] text-primary">{status}</span>}
              {error && <span className="text-[9.5px] text-warn">{error}</span>}
            </div>
          </Panel>

          <Panel
            title="MetaTrader 5"
            icon={<PlugZap className="size-3.5" />}
            meta="optional provider"
            actions={
              <Badge tone={mt5.connected ? "info" : "warning"} dot>
                {mt5.connected ? "attached" : "offline"}
              </Badge>
            }
            bodyClassName="p-0"
          >
            <DataRow
              label="Terminal"
              value={mt5.terminal_connected ? "Connected" : "Disconnected"}
              toneClassName={mt5.terminal_connected ? "text-primary-deep" : undefined}
            />
            <DataRow
              label="Broker session"
              value={mt5.broker_connected ? "Connected" : "Disconnected"}
              toneClassName={mt5.broker_connected ? "text-primary-deep" : undefined}
            />
            <DataRow label="Provider state" value={mt5.state_label ?? "Not configured"} />
            <DataRow
              label="Detected terminals"
              value={mt5.detected_paths?.length ? `${mt5.detected_paths.length} found` : "None"}
              title={mt5.detected_paths?.join(", ")}
            />
            <DataRow
              label="Poll interval"
              value={formatDuration(mt5.poll_interval_seconds ?? 0)}
            />
            <DataRow
              label="Stale threshold"
              value={formatDuration(mt5.stale_after_seconds ?? 0)}
            />
            {mt5.last_error && (
              <div className="border-b border-warn/20 bg-warn/[0.05] px-3 py-2 text-[9.5px] leading-relaxed text-warn/90">
                {mt5.last_error}
              </div>
            )}
            <div className="border-t border-line-soft p-3">
              <label htmlFor="mt5-terminal-path" className="label-xs mb-1.5 block">
                Manual terminal path
              </label>
              <div className="flex gap-2">
                <input
                  id="mt5-terminal-path"
                  value={terminalPath}
                  onChange={(event) => setTerminalPath(event.target.value)}
                  placeholder="Auto-detect installed terminal64.exe"
                  className="field min-w-0 flex-1 font-mono text-[9.5px]"
                />
                <Button
                  size="md"
                  variant="secondary"
                  disabled={busy === "terminal"}
                  onClick={() => void applyTerminalPath()}
                >
                  Apply
                </Button>
              </div>
              <p className="mt-1.5 flex items-start gap-2 text-[9px] leading-relaxed text-ink-faint">
                <ShieldCheck className="mt-[1px] size-3 shrink-0 text-primary/75" aria-hidden />
                KBMTI never requests MT5 credentials and never places orders. It attaches to an
                already running, logged-in terminal through the local MetaTrader5 IPC bridge.
              </p>
              {mt5.detected_paths?.length ? (
                <p className="mt-1.5 font-mono text-[9px] leading-relaxed break-all text-ink-faint/80">
                  {mt5.detected_paths.join("  ·  ")}
                </p>
              ) : null}
            </div>
          </Panel>

          <Panel title="Application" meta="v1.2.0" bodyClassName="p-0">
            <DataRow label="Build" value="Native desktop · PySide6 + Qt WebEngine" />
            <DataRow label="Data mode" value="Read-only market intelligence" />
            <DataRow label="Primary provider" value="Binance Spot" />
            <DataRow label="Optional provider" value="MetaTrader 5 local IPC" />
            <DataRow label="Forecast model" value="PATRON 1.0.0 · CPU · BTC/USDT 15m" />
            <DataRow label="Storage" value="%LOCALAPPDATA%\\KBMTI\\kbmti.db" />
          </Panel>
        </div>
      </div>
    </div>
  );
}
