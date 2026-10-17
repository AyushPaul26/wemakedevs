import type { Action, Bootstrap, Investigation, Ripple, Source } from "./types";
import type {
  SourceRef,
  SourceSummary,
  SourceDetail,
} from "./features/evidence/types";
import type {
  Approval,
  Page,
  RunCreate,
  RunInputs,
  RunSnapshot,
  WorkflowEvent,
} from "./features/workflows/types";
export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
let csrf = "";
let epoch = 0;
const inflight = new Set<AbortController>();
let expired: (() => void) | undefined;
export function onSessionExpired(callback: () => void) {
  expired = callback;
  return () => {
    if (expired === callback) expired = undefined;
  };
}
export function invalidateApiSession() {
  epoch++;
  csrf = "";
  for (const controller of inflight) controller.abort();
  inflight.clear();
}
export function setApiSession(token: string) {
  invalidateApiSession();
  csrf = token;
}
export function sessionEpoch() {
  return epoch;
}
export type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  responseKind?: "json" | "blob";
  idempotencyKey?: string;
};
async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const started = epoch;
  const controller = new AbortController();
  inflight.add(controller);
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) abort();
  const timeout = setTimeout(abort, 65000);
  const method = options.method ?? "GET";
  const headers = new Headers();
  if (csrf && method !== "GET") headers.set("X-CSRF-Token", csrf);
  if (method !== "GET" && path !== "/auth/login")
    headers.set(
      "Idempotency-Key",
      options.idempotencyKey ?? crypto.randomUUID(),
    );
  const multipart = options.body instanceof FormData;
  if (options.body !== undefined && !multipart)
    headers.set("Content-Type", "application/json");
  try {
    const response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers,
      signal: controller.signal,
      ...(options.body === undefined
        ? {}
        : {
            body: multipart
              ? (options.body as FormData)
              : JSON.stringify(options.body),
          }),
    });
    if (started !== epoch)
      throw new ApiError("Your session changed. Sign in to continue.", 401);
    if (!response.ok) {
      let detail: unknown;
      try {
        detail = (await response.json()).detail;
      } catch {
        /* Upstream may return HTML. */
      }
      // Parsing an error body yields; identity may have changed while it arrived.
      if (started !== epoch)
        throw new ApiError("Your session changed. Sign in to continue.", 401);
      if (response.status === 401 && !path.startsWith("/auth/")) {
        invalidateApiSession();
        expired?.();
      }
      throw new ApiError(
        typeof detail === "string"
          ? detail
          : response.status === 409
            ? "This record changed. Review the refreshed version and try again."
            : "This request could not be completed. Check your input and try again.",
        response.status,
      );
    }
    if (response.status === 204) return undefined as T;
    const result =
      options.responseKind === "blob"
        ? await response.blob()
        : await response.json();
    if (started !== epoch)
      throw new ApiError("Your session changed. Sign in to continue.", 401);
    return result as T;
  } catch (error) {
    if (started !== epoch)
      throw new ApiError("Your session changed. Sign in to continue.", 401);
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted)
      throw new ApiError(
        options.signal?.aborted
          ? "Request cancelled."
          : "This request took too long. Your input is preserved; try again.",
      );
    throw new ApiError(
      "Relay is offline. Check the backend connection and try again.",
    );
  } finally {
    clearTimeout(timeout);
    inflight.delete(controller);
    options.signal?.removeEventListener("abort", abort);
  }
}
const post = <T>(path: string, body: unknown, options: RequestOptions = {}) =>
  request<T>(path, { ...options, method: "POST", body });
const segment = encodeURIComponent;
const query = (values: Record<string, string | undefined>) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value) params.set(key, value);
  return params.size ? `?${params}` : "";
};
export const api = {
  request,
  bootstrap: (signal?: AbortSignal) =>
    request<Bootstrap>("/bootstrap", { signal }),
  investigate: (
    question: string,
    session_id: string,
    source_refs: SourceRef[] = [],
    run_id?: string,
  ) =>
    post<Investigation>("/investigate", {
      question,
      session_id,
      ...(source_refs.length ? { source_refs } : {}),
      ...(run_id ? { run_id } : {}),
    }),
  ripple: (origin_id: string, mitigation: boolean) =>
    post<Ripple>("/ripple", { origin_id, mitigation }),
  memory: () => request<{ items: Investigation[] }>("/memory"),
  actions: () => request<{ items: Action[] }>("/actions"),
  transition: (id: string, action: "approve" | "complete") =>
    post<Action>(`/actions/${segment(id)}/${action}`, {}),
  source: (
    id: string,
    version_id?: string,
    run_id?: string,
    signal?: AbortSignal,
  ) =>
    request<Source & SourceDetail>(
      `/sources/${segment(id)}${query({ version_id, run_id })}`,
      { signal },
    ),
  sources: (search = "", cursor?: string, signal?: AbortSignal) =>
    request<Page<SourceSummary>>(
      `/sources${query({ query: search, cursor })}`,
      { signal },
    ),
  addSource: (title: string, content: string) =>
    post<Source>("/sources", { title, content, type: "document" }),
  upload: (body: FormData, key?: string) =>
    post<{
      items: ({
        ref?: SourceRef;
        source_ref?: SourceRef;
        status?: string;
        processing_status?: string;
        error?: string;
        filename?: string;
      } & Partial<SourceRef>)[];
    }>("/attachments", body, { idempotencyKey: key }),
  runs: (cursor?: string, signal?: AbortSignal) =>
    request<Page<RunSnapshot>>(`/workflow-runs${query({ cursor })}`, {
      signal,
    }),
  run: (id: string, signal?: AbortSignal) =>
    request<RunSnapshot>(`/workflow-runs/${segment(id)}`, { signal }),
  createRun: (body: RunCreate, key?: string) =>
    post<RunSnapshot>("/workflow-runs", body, { idempotencyKey: key }),
  runControl: (
    id: string,
    control: "cancel" | "retry",
    expected_revision: number,
  ) =>
    post<RunSnapshot>(`/workflow-runs/${segment(id)}/${control}`, {
      expected_revision,
    }),
  reviseRun: (
    id: string,
    body: RunInputs & { expected_revision: number },
    key?: string,
  ) =>
    post<RunSnapshot>(`/workflow-runs/${segment(id)}/revise`, body, {
      idempotencyKey: key,
    }),
  approvals: (cursor?: string, signal?: AbortSignal) =>
    request<Page<Approval>>(`/approvals${query({ cursor })}`, { signal }),
  decide: (
    id: string,
    body: {
      decision: "approve" | "reject" | "request_changes";
      expected_revision: number;
      scope_hash: string;
      reason?: string;
    },
    key?: string,
  ) =>
    post<unknown>(`/approvals/${segment(id)}/decision`, body, {
      idempotencyKey: key,
    }),
  timeline: (id: string, cursor?: string, signal?: AbortSignal) =>
    request<Page<WorkflowEvent>>(
      `/workflow-runs/${segment(id)}/timeline${query({ cursor })}`,
      { signal },
    ),
};
export async function downloadFile(
  path: string,
  name: string,
  signal?: AbortSignal,
) {
  const blob = await request<Blob>(path, { responseKind: "blob", signal });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name.replace(/[^A-Za-z0-9._-]/g, "_");
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong. Try again.";
export const formatDate = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
      }).format(date);
};
