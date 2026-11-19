import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PanelProps {
  children: ReactNode;
  title?: string;
  meta?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
  className?: string;
  bodyClassName?: string;
  as?: "section" | "div" | "article";
}

/**
 * A content surface in the KBMTI workstation: dark neutral, fine border,
 * restrained elevation and a compact instrument-style header.
 */
export function Panel({
  children,
  title,
  meta,
  actions,
  icon,
  className,
  bodyClassName,
  as: Tag = "section",
}: PanelProps) {
  return (
    <Tag
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-[10px] border border-line bg-surface",
        "shadow-[0_1px_2px_rgba(0,0,0,0.16)]",
        className,
      )}
    >
      {title && (
        <header className="flex h-[34px] shrink-0 items-center gap-2 border-b border-line-soft bg-surface-2/35 px-3">
          {icon && <span className="shrink-0 text-primary">{icon}</span>}
          <h2 className="label-xs truncate text-[11px] text-ink">{title}</h2>
          {meta && <span className="ml-auto shrink-0 text-[10px] text-ink-faint">{meta}</span>}
          {actions && (
            <div className={cn("flex shrink-0 items-center gap-1", meta ? "ml-2" : "ml-auto")}>
              {actions}
            </div>
          )}
        </header>
      )}
      <div className={cn("min-h-0", bodyClassName ?? "px-3 py-3")}>{children}</div>
    </Tag>
  );
}

export function GroupLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex h-[30px] items-center border-b border-line-soft bg-surface-2/25 px-3",
        className,
      )}
    >
      <span className="text-[9.5px] font-medium tracking-[0.015em] text-ink-faint">
        {children}
      </span>
    </div>
  );
}
