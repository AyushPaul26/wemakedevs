import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("API client", () => {
  it("sends the actual mitigation choice to the backend", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ mitigation: true }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetcher);
    await api.ripple("payment-gateway", true);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/ripple",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          origin_id: "payment-gateway",
          mitigation: true,
        }),
      }),
    );
  });
  it("preserves actionable backend errors instead of producing fallback data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: "Graph unavailable. Start FalkorDB and retry.",
          }),
          { status: 503 },
        ),
      ),
    );
    await expect(api.bootstrap()).rejects.toThrow(
      "Graph unavailable. Start FalkorDB and retry.",
    );
  });
  it("handles non-JSON upstream failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("bad gateway", { status: 502 })),
    );
    await expect(api.bootstrap()).rejects.toBeInstanceOf(ApiError);
  });
  it("encodes source identifiers as a single URL path segment", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await api.source("a/b");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/sources/a%2Fb",
      expect.anything(),
    );
  });
});
