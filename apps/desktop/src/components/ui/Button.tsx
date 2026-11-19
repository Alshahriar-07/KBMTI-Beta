import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary:
    "border-primary bg-primary text-primary-ink shadow-[0_1px_2px_rgba(0,0,0,0.2)] hover:border-primary-deep hover:bg-primary-deep hover:text-white",
  secondary:
    "border-line bg-surface text-ink hover:border-line-strong hover:bg-surface-2",
  ghost: "border-transparent bg-transparent text-ink-muted hover:bg-hover hover:text-ink",
  danger:
    "border-bear/25 bg-bear/[0.06] text-bear hover:border-bear/40 hover:bg-bear/10",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 text-[10.5px] gap-1.5",
  md: "h-8 px-3.5 text-[11px] gap-1.5",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
}

export function Button({
  children,
  variant = "secondary",
  size = "md",
  icon,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-[6px] border font-medium",
        "transition-[color,background-color,border-color,transform] duration-150 ease-out active:translate-y-px",
        "disabled:pointer-events-none disabled:opacity-40",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}
