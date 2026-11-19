import { cn } from "@/lib/utils";

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}

export function Toggle({ checked, onChange, label, description, disabled }: ToggleProps) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line-soft/80 py-2.5 last:border-b-0">
      <div className="min-w-0">
        <p className="text-[11.5px] font-medium text-ink">{label}</p>
        {description && (
          <p className="mt-0.5 text-[10px] leading-relaxed text-ink-faint">{description}</p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-[18px] w-[30px] shrink-0 rounded-full border transition-colors duration-150",
          checked ? "border-primary bg-primary" : "border-line-strong bg-surface-2",
          disabled && "opacity-40",
        )}
      >
        <span
          className={cn(
            "absolute top-[2px] size-3 rounded-full bg-white shadow-sm transition-[left] duration-150",
            checked ? "left-[16px]" : "left-[2px]",
          )}
        />
      </button>
    </div>
  );
}
