import { useState } from "react";
import { Activity, BrainCircuit, Check, Clipboard, Database, FileTerminal, Server, Timer } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataRow } from "@/components/ui/DataRow";
import { Panel } from "@/components/ui/Panel";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { formatBrokerTime, formatBytes, formatDuration, formatTimeOnly } from "@/lib/format";
import type { Diagnostics, Health, SystemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export function DiagnosticsPage() {
  const health = usePolling<Health>("diagnostics-health", () => api.health(), 10_000);
  const diagnostics = usePolling<Diagnostics>("diagnostics", () => api.diagnostics(), 10_000);
  const system = usePolling<SystemStatus>("diagnostics-system", () => api.systemStatus(), 5000);
  const [copied, setCopied] = useState(false);

  const detail = diagnostics.data;
  const backend = detail?.backend ?? {};
  const python = detail?.python ?? {};
  const mt5 = detail?.mt5 ?? {};
  const patron = (detail?.patron ?? {}) as Record<string, unknown>;
  const patronRuntime = (patron.runtime ?? {}) as Record<string, unknown>;
  const patronChecks = (patron.checks ?? []) as Array<Record<string, unknown>>;
  const database = detail?.database ?? {};
  const tables = (database.tables ?? {}) as Record<string, number>;
  const platform = detail?.platform ?? {};
  const marketRealtime = (detail?.realtime?.market ?? {}) as Record<string, unknown>;
  const forecastRealtime = detail?.realtime?.forecast;
  const logLines = detail?.logs.recent ?? [];

  const copy = async () => {
    if (!detail) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(detail, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const tiles = [
    {
      label: "Backend",
      value: health.data?.status === "ok" ? "Running" : (health.data?.status ?? "unknown"),
      hint: `uptime ${formatDuration(health.data?.uptime_seconds)}`,
      ok: health.data?.status === "ok",
    },
    {
      label: "PATRON model",
      value: patronRuntime.ready ? "Ready" : String(patronRuntime.state ?? "unknown"),
      hint: `${String(patronRuntime.model_id ?? "patron-1.0.0")} · CPU`,
      ok: Boolean(patronRuntime.ready),
    },
    {
      label: "Database",
      value: String(database.integrity ?? "—"),
      hint: formatBytes(Number(database.size_bytes ?? 0)),
      ok: database.integrity === "ok",
    },
    {
      label: "Market feed",
      value: String((detail?.market as Record<string, unknown> | undefined)?.provider_label ?? "—"),
      hint: `${String((detail?.market as Record<string, unknown> | undefined)?.freshness ?? "unavailable")} · v${String(detail?.app?.version ?? "1.2.0")}`,
      ok: Boolean((detail?.market as Record<string, unknown> | undefined)?.connected),
    },
  ];

  return (
    <div className="scroll-area h-full">
      <div className="grid grid-cols-2 divide-x divide-line border-b border-line bg-surface md:grid-cols-4">
        {tiles.map((tile) => (
          <div key={tile.label} className="min-w-0 px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[9.5px] font-medium text-ink-faint">{tile.label}</p>
              <span
                className={cn("size-1.5 rounded-full", tile.ok ? "bg-primary" : "bg-warn")}
                aria-hidden
              />
            </div>
            <p className="mt-1 truncate text-[12.5px] font-medium text-ink">{tile.value}</p>
            <p className="mt-0.5 truncate text-[9px] text-ink-faint">{tile.hint}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-3 p-3 lg:grid-cols-2">
        <Panel
          title="Runtime"
          icon={<Server className="size-3.5" />}
          meta="backend · python · platform"
          actions={
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void copy()}
              icon={
                copied ? <Check className="size-3.5" /> : <Clipboard className="size-3.5" />
              }
            >
              {copied ? "Copied" : "Report"}
            </Button>
          }
          bodyClassName="p-3"
        >
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5">
            {[
              ["Backend host", String(backend.host ?? "—")],
              ["Backend port", String(backend.port ?? "—")],
              ["Uptime", formatDuration(Number(backend.uptime_seconds ?? 0))],
              ["Poll interval", `${backend.poll_interval_seconds ?? "—"} s`],
              ["Python", String(python.version ?? "—")],
              ["Implementation", String(python.implementation ?? "—")],
              ["Platform", String(platform.system ?? python.platform ?? "—")],
              ["CPU threads", String(system.data?.cpu.logical_cores ?? "—")],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt className="text-[9px] text-ink-faint">{label}</dt>
                <dd className="num mt-0.5 truncate text-[10px] text-ink-muted" title={value}>
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          <div className="mt-3 border-t border-line-soft pt-2.5">
            <p className="text-[9px] text-ink-faint">Database file</p>
            <p className="mt-0.5 font-mono text-[9px] break-all text-ink-muted/80">
              {String(database.path ?? "—")}
            </p>
          </div>
        </Panel>

        <Panel
          title="PATRON model"
          icon={<BrainCircuit className="size-3.5" />}
          meta={`${String(patron.status ?? "unknown")} · ${patronChecks.length} checks`}
          actions={
            <Badge tone={patronRuntime.ready ? "info" : "warning"} dot>
              {patronRuntime.ready ? "ready" : "unavailable"}
            </Badge>
          }
          bodyClassName="p-0"
        >
          <DataRow label="Model" value={String(patronRuntime.model_id ?? "patron-1.0.0")} />
          <DataRow label="State" value={String(patronRuntime.state ?? "—")} />
          <DataRow label="Device" value={String(patronRuntime.device ?? "cpu")} />
          <DataRow
            label="Parameters"
            value={
              patronRuntime.trainable_parameters
                ? Number(patronRuntime.trainable_parameters).toLocaleString()
                : "—"
            }
          />
          <DataRow label="Load time" value={patronRuntime.load_ms ? `${Number(patronRuntime.load_ms).toFixed(0)} ms` : "—"} />
          <DataRow
            label="Inferences"
            value={`${String(patronRuntime.inference_count ?? 0)} · ${String(patronRuntime.failure_count ?? 0)} failures`}
          />
          <DataRow label="Last success" value={formatBrokerTime(patronRuntime.last_success_at as string | null, true)} />
          <div className="px-3 py-2">
            {patronChecks.map((check) => (
              <div key={String(check.id)} className="flex items-start justify-between gap-2 border-b border-line-soft/60 py-1 last:border-b-0">
                <div className="min-w-0">
                  <p className="text-[9.5px] text-ink-muted">{String(check.label)}</p>
                  <p className="truncate font-mono text-[8.5px] text-ink-faint" title={String(check.detail)}>
                    {String(check.detail)}
                  </p>
                </div>
                <span
                  className={cn(
                    "shrink-0 text-[9px] font-medium capitalize",
                    check.status === "pass" ? "text-bull" : check.status === "warn" ? "text-warn" : "text-bear",
                  )}
                >
                  {String(check.status)}
                </span>
              </div>
            ))}
          </div>
          <div className="px-3 py-2.5">
            <p className="text-[9px] text-ink-faint">Last error</p>
            <p className="mt-0.5 text-[9.5px] leading-relaxed text-warn/80">
              {String(patronRuntime.last_error ?? patron.last_error ?? "None")}
            </p>
          </div>
        </Panel>

        <Panel
          title="Real-time pipeline"
          icon={<Timer className="size-3.5" />}
          meta="market socket · forecast queue"
          actions={
            <Badge tone={marketRealtime.kline_events ? "info" : "muted"} dot>
              {forecastRealtime?.mode === "event_driven" ? "event driven" : "polling"}
            </Badge>
          }
          bodyClassName="p-0"
        >
          <DataRow
            label="Last candle frame"
            value={formatTimeOnly(String(marketRealtime.last_kline_at ?? ""))}
            hint="UTC"
          />
          <DataRow
            label="Exchange to backend"
            value={
              marketRealtime.last_exchange_to_receive_ms !== null &&
              marketRealtime.last_exchange_to_receive_ms !== undefined
                ? `${Number(marketRealtime.last_exchange_to_receive_ms).toFixed(1)} ms`
                : "—"
            }
            hint={`${String(marketRealtime.kline_events ?? 0)} frames`}
          />
          <DataRow
            label="Snapshot throttle"
            value={
              marketRealtime.snapshot_throttle_ms
                ? `${String(marketRealtime.snapshot_throttle_ms)} ms`
                : "—"
            }
            hint="full UI snapshot"
          />
          <DataRow
            label="Last trigger"
            value={formatTimeOnly(String(forecastRealtime?.last_trigger_at ?? ""))}
            hint={formatTimeOnly(String(forecastRealtime?.last_trigger_bar_at ?? ""), false)}
          />
          <DataRow
            label="Queue wait"
            value={
              forecastRealtime?.queue_wait_ms !== null && forecastRealtime?.queue_wait_ms !== undefined
                ? `${Number(forecastRealtime.queue_wait_ms).toFixed(1)} ms`
                : "—"
            }
            hint={String(forecastRealtime?.state ?? "waiting")}
          />
          <DataRow
            label="Evaluation"
            value={
              forecastRealtime?.evaluation_ms !== null && forecastRealtime?.evaluation_ms !== undefined
                ? `${Number(forecastRealtime.evaluation_ms).toFixed(1)} ms`
                : "—"
            }
          />
          <DataRow
            label="PATRON inference"
            value={
              forecastRealtime?.inference_ms !== null && forecastRealtime?.inference_ms !== undefined
                ? `${Number(forecastRealtime.inference_ms).toFixed(1)} ms`
                : "—"
            }
          />
          <DataRow
            label="Trigger to forecast"
            value={
              forecastRealtime?.trigger_to_forecast_ms !== null &&
              forecastRealtime?.trigger_to_forecast_ms !== undefined
                ? `${Number(forecastRealtime.trigger_to_forecast_ms).toFixed(1)} ms`
                : "—"
            }
            hint="close → persisted"
          />
        </Panel>

        <Panel
          title="MetaTrader 5"
          icon={<Activity className="size-3.5" />}
          meta="terminal attachment"
          actions={
            <Badge tone={mt5.connected ? "info" : "warning"} dot>
              {mt5.connected ? "attached" : "offline"}
            </Badge>
          }
          bodyClassName="p-0"
        >
          <DataRow label="Selected symbol" value={String(mt5.selected_symbol ?? "—")} />
          <DataRow label="Timeframe" value={String(mt5.timeframe ?? "—")} />
          <DataRow label="Freshness" value={String(mt5.freshness ?? "—")} />
          <DataRow label="Time basis" value={String(mt5.time_basis ?? "broker_server")} />
          <DataRow label="Reconnect attempts" value={String(mt5.reconnect_attempts ?? 0)} />
          <DataRow label="MT5 package" value={String(mt5.package_version ?? "not installed")} />
          <div className="px-3 py-2.5">
            <p className="text-[9px] text-ink-faint">Last error</p>
            <p className="mt-0.5 text-[9.5px] leading-relaxed text-warn/80">
              {String(mt5.last_error ?? "None")}
            </p>
            <p className="mt-2 text-[9px] text-ink-faint">Detected terminal paths</p>
            <p className="mt-0.5 font-mono text-[9px] leading-relaxed break-all text-ink-muted/80">
              {(mt5.detected_terminal_paths as string[] | undefined)?.join(", ") || "None detected"}
            </p>
          </div>
        </Panel>

        <Panel
          title="Database tables"
          icon={<Database className="size-3.5" />}
          meta="SQLite row counts"
          actions={
            <Badge tone={database.integrity === "ok" ? "info" : "warning"}>
              {String(database.integrity ?? "unknown")}
            </Badge>
          }
          bodyClassName="p-0"
        >
          <div className="grid grid-cols-2">
            {Object.entries(tables).map(([table, count]) => (
              <div
                key={table}
                className="flex h-7 items-center justify-between gap-2 border-b border-line-soft/70 px-3 odd:border-r odd:border-r-line-soft/70"
              >
                <span className="truncate font-mono text-[9px] text-ink-faint">{table}</span>
                <span className="num text-[9.5px] text-ink-muted">{count}</span>
              </div>
            ))}
          </div>
          {!Object.keys(tables).length && (
            <p className="px-3 py-3 text-[10px] text-ink-faint">No table statistics yet.</p>
          )}
          <div className="flex items-center justify-between px-3 py-2 text-[9px]">
            <span className="text-ink-faint">Report generated</span>
            <span className="num text-ink-muted">
              {formatBrokerTime(detail?.generated_at, true)}
            </span>
          </div>
        </Panel>

        <Panel
          title="Recent log"
          icon={<FileTerminal className="size-3.5" />}
          meta={`${logLines.length} lines`}
          bodyClassName="p-0"
        >
          <div className="scroll-area max-h-[264px] bg-log p-2.5 font-mono text-[9px] leading-[1.6] text-log-ink/80">
            {logLines.length ? (
              logLines.map((line, index) => (
                <p key={`${index}-${line.slice(0, 12)}`} className="break-all">
                  <span className="mr-2 text-log-ink/40 select-none">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  {line}
                </p>
              ))
            ) : (
              <p>No log lines available.</p>
            )}
          </div>
          <p className="border-t border-line-soft px-3 py-2 font-mono text-[8.5px] break-all text-ink-faint">
            {detail?.logs.path ?? "Log file path unavailable."}
          </p>
        </Panel>
      </div>
    </div>
  );
}
