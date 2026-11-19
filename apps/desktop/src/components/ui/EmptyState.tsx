import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-6 py-9 text-center",
        className,
      )}
    >
      <Icon className="size-5 text-ink-faint/70" aria-hidden />
      <p className="text-[11.5px] font-medium text-ink-muted">{title}</p>
      <p className="mx-auto max-w-sm text-[10.5px] leading-relaxed text-ink-faint">
        {description}
      </p>
      {action}
    </div>
  );
}
