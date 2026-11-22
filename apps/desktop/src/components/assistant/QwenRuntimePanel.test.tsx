import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QwenRuntimePanel } from "@/components/assistant/QwenRuntimePanel";
import type { KieStatus } from "@/lib/types";

function status(overrides: Partial<KieStatus> = {}): KieStatus {
  return {
    enabled: true,
    available: true,
    artifacts_available: true,
    state: "ready",
    health_state: "READY",
    health_message: "Qwen inference is verified with 37/37 layers on vulkan.",
    health: {
      state: "READY",
      ready: true,
      message: "Qwen inference is verified with 37/37 layers on vulkan.",
      backend: "vulkan",
      gpu_name: "AMD Radeon RX 580 2048SP",
      gpu_offloaded: true,
      offloaded_layers: 37,
      total_layers: 37,
      context_size: 4096,
      initialization_seconds: 3.302,
      last_error: null,
      last_inference_error: null,
      smoke_test: { ok: true, generated_tokens: 4 },
    },
    ready: true,
    backend: "vulkan",
    accelerated: true,
    model_name: "qwen3 4B Q4_K - Medium",
    quantization: "Q4_K_M",
    runtime_version: "b12503",
    gpu_name: "AMD Radeon RX 580 2048SP",
    vram_mb: 3272.7,
    vram_budget_mb: 4096,
    offloaded_layers: 37,
    total_layers: 37,
    context_size: 4096,
    initialization_seconds: 3.302,
    last_error: null,
    last_inference_error: null,
    ...overrides,
  };
}

describe("QwenRuntimePanel", () => {
  it("shows verified AMD Vulkan readiness from backend status", () => {
    render(<QwenRuntimePanel status={status()} error={null} retrying={false} onRetry={() => {}} />);
    expect(screen.getByText("Qwen Ready")).toBeInTheDocument();
    expect(screen.getByText("AMD Vulkan GPU")).toBeInTheDocument();
    expect(screen.getByText(/AMD Radeon RX 580 2048SP/)).toBeInTheDocument();
    expect(screen.getByText(/qwen3 4B/)).toBeInTheDocument();
    expect(screen.getByText("37 / 37 layers")).toBeInTheDocument();
    expect(screen.getByText("3273 MB / 4096 MB budget")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry qwen/i })).not.toBeInTheDocument();
  });

  it("shows initialization without claiming readiness", () => {
    render(
      <QwenRuntimePanel
        status={status({
          available: false,
          ready: false,
          health_state: "INITIALIZING",
          health_message: "Initializing Qwen on the Vulkan backend.",
        })}
        error={null}
        retrying={false}
        onRetry={() => {}}
      />,
    );
    expect(screen.getAllByText("Initializing Qwen…").length).toBeGreaterThan(0);
    expect(screen.queryByText("Qwen Ready")).not.toBeInTheDocument();
    expect(screen.queryByText("AMD Vulkan GPU")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /initializing qwen/i })).toBeDisabled();
  });

  it("shows the real GPU failure and allows a controlled retry", () => {
    const onRetry = vi.fn();
    render(
      <QwenRuntimePanel
        status={status({
          available: false,
          ready: false,
          accelerated: false,
          health_state: "GPU_BACKEND_UNAVAILABLE",
          health_message: "Vulkan is unavailable: no Vulkan device",
          last_error: "no Vulkan device",
        })}
        error={null}
        retrying={false}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText("GPU Backend Unavailable")).toBeInTheDocument();
    expect(screen.getAllByText(/no Vulkan device/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /retry qwen/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
