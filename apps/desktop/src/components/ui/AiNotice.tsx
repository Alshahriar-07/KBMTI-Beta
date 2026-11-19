import type { ReactNode } from "react";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

interface AiNoticeProps {
  title?: string;
  children?: ReactNode;
  compact?: boolean;
  className?: string;
}

export function AiNotice({
  title = "PATRON model intelligence is active",
  children = "Forecasts are produced by the trained PATRON model over Binance BTC/USDT 15m data. Answers in AI Chat are deterministic text grounded in that output, not a language model. Nothing here is financial advice.",
  compact = false,
  className,
}: AiNoticeProps) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 border-y border-line-soft border-l-[3px] border-l-primary bg-light-blue/60",
        compact ? "px-3 py-1.5" : "px-3 py-2",
        className,
      )}
    >
      <Info className="mt-[2px] size-3 shrink-0 text-primary" aria-hidden />
      <div className="min-w-0">
        <p className="text-[10.5px] font-semibold tracking-[0.01em] text-ink">{title}</p>
        <p className="mt-0.5 text-[10.5px] leading-relaxed text-ink-muted">{children}</p>
      </div>
    </div>
  );
}
