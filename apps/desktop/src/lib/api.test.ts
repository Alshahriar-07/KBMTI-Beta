import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API error mapping", () => {
  it("turns a proxy 502 into a retryable upstream error with correlation id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("", {
            status: 502,
            headers: { "X-Request-ID": "proxy-request-1" },
          }),
      ),
    );

    await expect(api.kieStatus()).rejects.toMatchObject({
      name: "ApiError",
      status: 502,
      code: "UPSTREAM_UNAVAILABLE",
      requestId: "proxy-request-1",
      retryable: true,
    });
  });

  it("keeps the backend error code, request id and safe message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: {
                code: "MODEL_LOAD_FAILED",
                message: "Qwen model failed to load.",
                request_id: "backend-request-2",
              },
            }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );

    try {
      await api.kieStatus();
      throw new Error("expected failure");
    } catch (cause) {
      expect(cause).toBeInstanceOf(ApiError);
      expect(cause).toMatchObject({
        status: 503,
        code: "MODEL_LOAD_FAILED",
        message: "Qwen model failed to load.",
        requestId: "backend-request-2",
        retryable: true,
      });
    }
  });

  it("marks an unreachable local backend as retryable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("connection refused");
      }),
    );

    await expect(api.kieStatus()).rejects.toMatchObject({
      status: 0,
      code: "BACKEND_UNREACHABLE",
      retryable: true,
    });
  });
});
