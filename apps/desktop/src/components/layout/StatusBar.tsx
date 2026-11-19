import { ShieldCheck } from "lucide-react";

import { useMarket } from "@/state/market-context";
import { cn } from "@/lib/utils";

/** Persistent instrument-style footer: scope, transport, backend, stage. */
export function StatusBar() {
  const { stream } = useMarket();
  const transport = stream.transport;
  const transportTone =
    transport === "open" ? "bg-bull" : transport === "reconnecting" ? "bg-warn" : "bg-line-strong";
  const backendOrigin =
    (import.meta.env.VITE_BACKEND_ORIGIN as string | undefined)?.replace(/^https?:\/\//, "") ??
    "127.0.0.1:8756";

  return (
    <footer className="flex h-[24px] shrink-0 items-center gap-4 border-t border-line bg-surface px-3.5 text-[9.5px] tracking-[0.01em] text-ink-faint">
      <span className="inline-flex items-center gap-1.5 text-ink-faint/90">
        <ShieldCheck className="size-2.5" aria-hidden />
        Read-only · no order execution
      </span>
      <span className="hidden lg:inline">Not financial advice</span>

      <span className="ml-auto hidden items-center gap-1.5 sm:inline-flex">
        <span className={cn("size-1 rounded-full", transportTone)} />
        Stream {transport}
      </span>
      <span className="hidden items-center gap-1.5 md:inline-flex">
        <span className="size-1 rounded-full bg-bull/80" />
        Local backend · {backendOrigin}
      </span>
      <span className="hidden xl:inline">UTC timestamps</span>
      <span className="num tracking-normal text-ink-faint/80">PATRON · v1.2.0</span>
    </footer>
  );
}
