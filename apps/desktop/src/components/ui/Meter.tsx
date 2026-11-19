import { cn } from "@/lib/utils";

interface MeterProps {
  label: string;
  percent: number | null;
  detail?: string;
  className?: string;
}

export function Meter({ label, percent, detail, className }: MeterProps) {
  const value = percent === null ? 0 : Math.max(0, Math.min(100, percent));
  const tone =
    percent === null ? "bg-line-strong" : value >= 85 ? "bg-warn" : "bg-primary";

  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10.5px] text-ink-faint">{label}</span>
        <span className="num text-[10.5px] text-ink-muted">
          {percent === null ? "n/a" : `${percent.toFixed(0)}%`}
        </span>
      </div>
      <div className="meter-track mt-1 w-full">
        <div className={cn("h-full", tone)} style={{ width: `${value}%` }} />
      </div>
      {detail && <p className="mt-1 truncate text-[9px] text-ink-faint">{detail}</p>}
    </div>
  );
}
