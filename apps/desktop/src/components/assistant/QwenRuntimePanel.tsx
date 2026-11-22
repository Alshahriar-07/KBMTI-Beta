import { Cpu, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataRow } from "@/components/ui/DataRow";
import { Panel } from "@/components/ui/Panel";
import type { KieStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

function healthLabel(state: string | undefined): string {
  switch (state) {
    case "READY":
      return "Qwen Ready";
    case "INITIALIZING":
      return "Initializing Qwen…";
    case "GPU_BACKEND_UNAVAILABLE":
      return "GPU Backend Unavailable";
    case "GPU_MEMORY_INSUFFICIENT":
      return "GPU Memory Insufficient";
    case "MODEL_NOT_FOUND":
      return "Model Not Found";
    case "MODEL_LOAD_FAILED":
      return "Model Load Failed";
    case "INFERENCE_FAILED":
      return "Inference Failed";
    case "STOPPING":
      return "Stopping Qwen";
    default:
      return "Qwen Not Initialized";
  }
}

function healthTone(state: string | undefined) {
  if (state === "READY") return "success" as const;
  if (state === "INITIALIZING" || state === "STOPPING") return "info" as const;
  if (state === "NOT_INITIALIZED") return "muted" as const;
  return "danger" as const;
}

export function QwenRuntimePanel({
  status,
  error,
  retrying,
  onRetry,
}: {
  status: KieStatus | null;
  error: string | null;
  retrying: boolean;
  onRetry: () => void;
}) {
  const state = status?.health_state;
  const ready = Boolean(status?.ready);
  const model = status?.model_name
    ? `${status.model_name}${status.quantization ? ` · ${status.quantization}` : ""}`
    : "—";
  const vram =
    status?.vram_mb != null
      ? `${Math.round(status.vram_mb)} MB${
          status.vram_budget_mb ? ` / ${status.vram_budget_mb} MB budget` : ""
        }`
      : "—";
  const layers =
    status?.offloaded_layers != null && status.total_layers != null
      ? `${status.offloaded_layers} / ${status.total_layers} layers`
      : "—";
  return (
    <Panel title="Qwen local inference" icon={<Cpu className="size-3.5" />} bodyClassName="p-0">
      <div className="flex flex-wrap items-center gap-1.5 px-3 py-2.5">
        <Badge tone={healthTone(state)} dot>
          {healthLabel(state)}
        </Badge>
        {ready && <Badge tone="info">AMD Vulkan GPU</Badge>}
      </div>
      <p className="px-3 pb-2 text-[9px] leading-relaxed text-ink-faint">
        {status?.health_message ?? "Checking the local Qwen runtime…"}
      </p>
      <DataRow label="Model" value={model} />
      <DataRow
        label="Runtime"
        value={status?.runtime_version ? `llama.cpp ${status.runtime_version}` : "—"}
      />
      <DataRow label="GPU" value={status?.gpu_name ?? "—"} />
      <DataRow label="Offload" value={layers} />
      <DataRow label="VRAM" value={vram} />
      <DataRow
        label="Context"
        value={status?.context_size != null ? `${status.context_size} tokens` : "—"}
      />
      <DataRow
        label="Init time"
        value={
          status?.initialization_seconds != null
            ? `${status.initialization_seconds.toFixed(1)} s`
            : "—"
        }
      />
      {(status?.last_error || error) && (
        <p className="border-t border-line-soft/70 px-3 py-2 text-[8.5px] leading-relaxed text-warn/90">
          {status?.last_error ?? error}
        </p>
      )}
      {!ready && (
        <div className="border-t border-line-soft/70 px-3 py-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={onRetry}
            disabled={retrying || state === "INITIALIZING"}
            icon={<RefreshCw className={cn("size-3", retrying && "animate-spin")} />}
          >
            {state === "INITIALIZING" ? "Initializing Qwen…" : "Retry Qwen"}
          </Button>
        </div>
      )}
    </Panel>
  );
}
