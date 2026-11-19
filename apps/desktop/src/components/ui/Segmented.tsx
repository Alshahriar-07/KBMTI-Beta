import { cn } from "@/lib/utils";

export interface SegmentedOption {
  value: string;
  label: string;
}

interface SegmentedProps {
  options: SegmentedOption[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel: string;
  size?: "sm" | "md";
  className?: string;
}

export function Segmented({
  options,
  value,
  onChange,
  disabled,
  ariaLabel,
  size = "sm",
  className,
}: SegmentedProps) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex shrink-0 items-center gap-[2px] rounded-[7px] border border-line bg-surface-2/60 p-[3px]",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            disabled={disabled}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-[5px] font-medium transition-[color,background-color,box-shadow] duration-150 disabled:opacity-40",
              size === "sm" ? "h-[24px] px-2 text-[10.5px]" : "h-[28px] px-2.5 text-[11px]",
              active
                ? "bg-surface text-ink shadow-[0_1px_2px_rgba(0,0,0,0.18)]"
                : "text-ink-faint hover:bg-hover hover:text-ink-muted",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
