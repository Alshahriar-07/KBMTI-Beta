import { Activity, ClipboardList, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { GroupLabel, Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { formatBrokerTime, formatPrice } from "@/lib/format";
import type { JournalRecord, JournalRecordsResponse, OutcomeSummary } from "@/lib/types";

const STATUS_TONE = {
  OPEN: "info",
  CLOSED: "muted",
  EXPIRED: "warning",
  CANCELLED: "warning",
} as const;

const OUTCOME_TONE: Record<string, "success" | "danger" | "warning" | "muted"> = {
  SUCCESS: "success",
  LOSS: "danger",
  BREAKEVEN: "muted",
  INVALID_SETUP: "warning",
  EXECUTION_ERROR: "danger",
  INSUFFICIENT_DATA: "warning",
};

function rValue(record: JournalRecord): string {
  if (record.r_multiple === null) return "—";
  const value = Number(record.r_multiple);
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}

export function JournalPage() {
  const records = usePolling<JournalRecordsResponse>("journal-records", () => api.journalRecords(), 15_000);
  const summary = usePolling<OutcomeSummary>("journal-summary", () => api.journalSummary(), 15_000);
  const data = records.data;

  return (
    <div className="scroll-area h-full">
      <div className="border-b border-line bg-surface px-3 py-2.5">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-2">
          <span className="label-xs">Paper and manual journal</span>
          <Badge tone="warning">No execution</Badge>
          <Badge tone="muted">Position size not calculated</Badge>
          {records.loading && <Spinner />}
          <span className="num ml-auto text-[9.5px] text-ink-faint">
            open {data?.open ?? 0} · closed {data?.closed ?? 0} · expired {data?.expired ?? 0}
          </span>
        </div>
      </div>

      <div className="mx-auto grid max-w-[1500px] gap-2 p-2 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel title="Journal records" icon={<ClipboardList className="size-3.5" />} bodyClassName="p-0">
          {records.loading && !data ? (
            <div className="flex items-center justify-center gap-2 py-8 text-[10.5px] text-ink-faint">
              <Spinner /> Loading records…
            </div>
          ) : !data?.records.length ? (
            <EmptyState
              icon={ClipboardList}
              title="No journal records"
              description={
                records.error ??
                "Accept a review-gated setup on the Assistant page, then create a paper record from /api/v1/journal/records."
              }
            />
          ) : (
            <div className="divide-y divide-line-soft">
              {data.records.map((record) => (
                <div key={record.trade_id} className="px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={record.direction === "LONG" ? "success" : "danger"}>{record.direction}</Badge>
                    <span className="text-[11px] font-medium text-ink">{record.symbol} {record.timeframe}</span>
                    <Badge tone={STATUS_TONE[record.status]}>{record.status}</Badge>
                    <Badge tone={OUTCOME_TONE[record.outcome ?? ""] ?? "muted"}>{record.outcome ?? "PENDING"}</Badge>
                    <span className="num ml-auto text-[10px] text-ink-muted">{rValue(record)}</span>
                  </div>
                  <div className="mt-1 grid gap-x-4 text-[9.5px] text-ink-faint sm:grid-cols-2 lg:grid-cols-4">
                    <span>Mode {record.mode}</span>
                    <span>Entry {formatPrice(Number(record.actual_entry ?? record.planned_entry))}</span>
                    <span>Stop {formatPrice(Number(record.stop_loss))}</span>
                    <span>TP1 {formatPrice(Number(record.tp1))}</span>
                    <span>Opened {formatBrokerTime(record.opened_at)}</span>
                    <span>Closed {formatBrokerTime(record.closed_at)}</span>
                    <span>MFE {record.mfe ?? "—"}R · MAE {record.mae ?? "—"}R</span>
                    <span>Strategy v{record.strategy_version} · {record.strategy_validation_status}</span>
                  </div>
                  {record.notes && <p className="mt-1 text-[9.5px] text-ink-faint">{record.notes}</p>}
                </div>
              ))}
            </div>
          )}
        </Panel>

        <div className="space-y-2">
          <Panel title="Outcome review" icon={<Activity className="size-3.5" />} bodyClassName="p-0">
            <GroupLabel>Counts</GroupLabel>
            <div className="grid grid-cols-2 divide-x divide-line-soft">
              <div className="px-3 py-2">
                <p className="num text-[20px] font-semibold text-ink">{summary.data?.closed_or_expired ?? 0}</p>
                <p className="text-[9px] text-ink-faint">closed or expired</p>
              </div>
              <div className="px-3 py-2">
                <p className="num text-[20px] font-semibold text-ink">{summary.data?.approved_for_dataset ?? 0}</p>
                <p className="text-[9px] text-ink-faint">approved for dataset</p>
              </div>
            </div>
            <GroupLabel>Categories</GroupLabel>
            {summary.data?.categories && Object.keys(summary.data.categories).length ? (
              Object.entries(summary.data.categories).map(([category, count]) => (
                <div key={category} className="flex items-center justify-between border-b border-line-soft/70 px-3 py-1.5 last:border-b-0">
                  <span className="text-[10px] text-ink-faint">{category}</span>
                  <span className="num text-[10px] text-ink-muted">{count}</span>
                </div>
              ))
            ) : (
              <p className="px-3 py-2 text-[9.5px] text-ink-faint">No closed records yet.</p>
            )}
            <div className="flex items-start gap-1.5 border-t border-line-soft px-3 py-2 text-[9px] leading-relaxed text-ink-faint">
              <ShieldAlert className="mt-[1px] size-3 shrink-0" aria-hidden />
              Outcome counts are descriptive. They are not profitability evidence.
            </div>
          </Panel>
          <p className="px-1 text-[8.5px] leading-relaxed text-ink-faint">{data?.note}</p>
        </div>
      </div>
    </div>
  );
}
