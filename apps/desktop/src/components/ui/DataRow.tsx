import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface DataRowProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  toneClassName?: string;
  className?: string;
  title?: string;
}

/** Label left, tabular value right, hairline below — the base unit of the intel panel. */
export function DataRow({
  label,
  value,
  hint,
  toneClassName,
  className,
  title,
}: DataRowProps) {
  return (
    <div
      title={title}
      className={cn(
        "flex h-[27px] items-center justify-between gap-3 border-b border-line-soft/70 px-3 last:border-b-0",
        className,
      )}
    >
      <span className="shrink-0 text-[10.5px] text-ink-faint">{label}</span>
      <span className="flex min-w-0 items-baseline justify-end gap-1">
        {hint && <span className="truncate text-[9.5px] text-ink-faint">{hint}</span>}
        <span className={cn("num truncate text-[10.5px] font-medium text-ink", toneClassName)}>
          {value}
        </span>
      </span>
    </div>
  );
}
