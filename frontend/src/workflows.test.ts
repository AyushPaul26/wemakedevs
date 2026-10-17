import { describe, it, expect, vi, afterEach } from "vitest";
import { api, setApiSession, invalidateApiSession } from "./api";
import { newerSnapshot, uniqueRefs } from "./features/workflows/state";
afterEach(() => {
  invalidateApiSession();
  vi.unstubAllGlobals();
});
describe("member scoped transport", () => {
  it("sends CSRF and browser multipart without a JSON content type", async () => {
    setApiSession("token");
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    const body = new FormData();
    body.append("files", new File(["a"], "a.txt"));
    await api.request("/attachments", { method: "POST", body });
    const options = fetcher.mock.calls[0][1];
    expect(options.credentials).toBe("same-origin");
    expect(options.headers.get("X-CSRF-Token")).toBe("token");
    expect(options.headers.has("Content-Type")).toBe(false);
  });
  it("rejects a late response from a previous member", async () => {
    let finish!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      ),
    );
    const pending = api.bootstrap();
    invalidateApiSession();
    finish(new Response("{}"));
    await expect(pending).rejects.toThrow(/session changed/i);
  });
  it("does not turn a failed download into a file", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Download denied" }), {
          status: 403,
        }),
      ),
    );
    await expect(
      api.request("/artifacts/a/download", { responseKind: "blob" }),
    ).rejects.toThrow("Download denied");
  });
});
describe("workflow boundaries", () => {
  it("keeps the newest generation and revision", () => {
    const current = { generation: 2, revision: 5 };
    expect(newerSnapshot(current, { generation: 1, revision: 9 })).toBe(
      current,
    );
    expect(newerSnapshot(current, { generation: 2, revision: 4 })).toBe(
      current,
    );
    expect(newerSnapshot(current, { generation: 2, revision: 6 })).toEqual({
      generation: 2,
      revision: 6,
    });
  });
  it("deduplicates exact versions without collapsing replacement evidence", () => {
    expect(
      uniqueRefs([
        { source_id: "a", version_id: "1" },
        { source_id: "a", version_id: "1" },
        { source_id: "a", version_id: "2" },
      ]),
    ).toHaveLength(2);
  });
});

it("keeps distinct cited chunks from the same immutable version", async () => {
  const { uniqueEvidenceRefs } = await import("./features/workflows/state");
  expect(
    uniqueEvidenceRefs([
      { source_id: "s", version_id: "v", chunk_id: "one" },
      { source_id: "s", version_id: "v", chunk_id: "one" },
      { source_id: "s", version_id: "v", chunk_id: "two" },
    ]),
  ).toHaveLength(2);
});

it("does not expire a new session when an old 401 error body arrives late", async () => {
  const { onSessionExpired, sessionEpoch } = await import("./api");
  let release!: (body: unknown) => void;
  const expire = vi.fn();
  const unsubscribe = onSessionExpired(expire);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    }),
  );
  const pending = api.bootstrap();
  await vi.waitFor(() => expect(release).toBeTypeOf("function"));
  setApiSession("new-member-csrf");
  const newEpoch = sessionEpoch();
  release({ detail: "Authentication required" });
  await expect(pending).rejects.toThrow(/session changed/i);
  expect(expire).not.toHaveBeenCalled();
  expect(sessionEpoch()).toBe(newEpoch);
  unsubscribe();
});
