import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn("inline-flex text-ink-faint", className)}
    >
      <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
    </span>
  );
}
