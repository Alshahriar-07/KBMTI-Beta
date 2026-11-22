import { Database, FlaskConical, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { DataRow } from "@/components/ui/DataRow";
import { EmptyState } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { formatBrokerTime } from "@/lib/format";
import type { BacktestSummary, DatasetVersion, LearningStatus, ModelRecord } from "@/lib/types";

export function LearningPage() {
  const status = usePolling<LearningStatus>("learning-status", () => api.learningStatus(), 30_000);
  const datasets = usePolling<{ datasets: DatasetVersion[]; count: number }>(
    "learning-datasets",
    () => api.learningDatasets(),
    30_000,
  );
  const backtests = usePolling<{ backtests: BacktestSummary[]; count: number }>(
    "learning-backtests",
    () => api.learningBacktests(),
    30_000,
  );
  const models = usePolling<{ models: ModelRecord[]; active: ModelRecord | null; count: number; note: string }>(
    "learning-models",
    () => api.learningModels(),
    30_000,
  );

  return (
    <div className="scroll-area h-full">
      <div className="border-b border-line bg-surface px-3 py-2.5">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-2">
          <span className="label-xs">Learning and evaluation</span>
          <Badge tone="warning">Promotion requires approval</Badge>
          <Badge tone="muted">No auto-training</Badge>
          <span className="num ml-auto text-[9.5px] text-ink-faint">
            datasets {status.data?.datasets ?? "—"} · backtests {status.data?.backtests ?? "—"}
          </span>
        </div>
      </div>

      <div className="mx-auto grid max-w-[1500px] gap-2 p-2 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-2">
          <Panel title="Datasets" icon={<Database className="size-3.5" />} bodyClassName="p-0">
            {datasets.loading && !datasets.data ? (
              <div className="flex items-center justify-center gap-2 py-8 text-[10.5px] text-ink-faint">
                <Spinner /> Loading datasets…
              </div>
            ) : !datasets.data?.datasets.length ? (
              <EmptyState
                icon={Database}
                title="No dataset versions"
                description="Prepare a dataset from stored market snapshots. The builder blocks duplicates and leakage."
              />
            ) : (
              datasets.data.datasets.map((dataset) => (
                <div key={dataset.dataset_id} className="border-b border-line-soft/70 px-3 py-2 last:border-b-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px] font-medium text-ink">{dataset.name}</span>
                    <Badge tone={dataset.status === "VALID" ? "success" : "danger"}>{dataset.status}</Badge>
                    <span className="num ml-auto text-[9px] text-ink-faint">{dataset.manifest_hash.slice(0, 12)}…</span>
                  </div>
                  <p className="mt-1 text-[9.5px] text-ink-faint">
                    {dataset.dataset_id} · {formatBrokerTime(dataset.created_at)}
                  </p>
                </div>
              ))
            )}
          </Panel>

          <Panel title="Backtests" icon={<FlaskConical className="size-3.5" />} bodyClassName="p-0">
            {!backtests.data?.backtests.length ? (
              <EmptyState
                icon={FlaskConical}
                title="No backtest reports"
                description="Run a chronological backtest from stored candles. Results include costs and sealed-test notes."
              />
            ) : (
              backtests.data.backtests.map((run) => {
                const metrics = run.metrics as Record<string, number | null>;
                return (
                  <div key={run.backtest_id} className="border-b border-line-soft/70 px-3 py-2 last:border-b-0">
                    <div className="flex items-center gap-2">
                      <span className="num text-[10.5px] text-ink">{run.backtest_id}</span>
                      <Badge tone="info">{run.status}</Badge>
                      <span className="ml-auto text-[9px] text-ink-faint">{formatBrokerTime(run.created_at)}</span>
                    </div>
                    <div className="mt-1 grid grid-cols-2 gap-x-3 text-[9.5px] text-ink-faint sm:grid-cols-4">
                      <span>Trades {metrics.trades ?? 0}</span>
                      <span>Win rate {metrics.win_rate ?? "—"}</span>
                      <span>Expectancy {metrics.expectancy_r ?? "—"}R</span>
                      <span>Max DD {metrics.max_drawdown_r ?? "—"}R</span>
                    </div>
                  </div>
                );
              })
            )}
          </Panel>
        </div>

        <div className="space-y-2">
          <Panel title="Model registry" icon={<ShieldCheck className="size-3.5" />} bodyClassName="p-0">
            {models.data?.active ? (
              <DataRow label="Active" value={models.data.active.name} toneClassName="text-bull" />
            ) : (
              <DataRow label="Active model" value="base Qwen only" />
            )}
            <DataRow label="Registered" value={models.data?.count ?? 0} />
            {models.data?.models.slice(0, 6).map((model) => (
              <DataRow key={model.model_id} label={model.name} value={model.status} />
            ))}
            <div className="px-3 py-2 text-[9px] leading-relaxed text-ink-faint">{models.data?.note}</div>
          </Panel>

          <Panel title="Paper-trading gate" bodyClassName="p-0">
            <DataRow label="Training available" value={status.data?.training_available ? "yes" : "no"} />
            <DataRow label="Approved outcomes" value={status.data?.approved_outcomes ?? 0} />
            <DataRow label="Execution" value={status.data?.execution ?? "DISABLED"} />
            <p className="px-3 py-2 text-[9px] leading-relaxed text-ink-faint">{status.data?.training_reason}</p>
          </Panel>
        </div>
      </div>
    </div>
  );
}
