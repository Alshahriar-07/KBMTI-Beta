import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Tone = "neutral" | "success" | "danger" | "warning" | "info" | "muted" | "accent";

const TONES: Record<Tone, string> = {
  neutral: "border-line bg-surface-2 text-ink-muted",
  success: "border-bull/25 bg-bull/10 text-bull",
  danger: "border-bear/25 bg-bear/10 text-bear",
  warning: "border-warn/25 bg-warn/10 text-warn",
  info: "border-primary/20 bg-primary/10 text-primary",
  accent: "border-primary/20 bg-primary/10 text-primary",
  muted: "border-line-soft bg-transparent text-ink-faint",
};

interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
  className?: string;
  title?: string;
}

export function Badge({ children, tone = "neutral", dot = false, className, title }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-[20px] shrink-0 items-center gap-1.5 rounded-[5px] border px-2 text-[9.5px] font-medium tracking-[0.015em] transition-colors duration-150",
        TONES[tone],
        className,
      )}
    >
      {dot && <span className="size-1.5 shrink-0 rounded-full bg-current" />}
      {children}
    </span>
  );
}
