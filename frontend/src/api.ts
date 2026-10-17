import type { Action, Bootstrap, Investigation, Ripple, Source } from "./types";
export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
async function request<T>(path: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 65000);
  try {
    const response = await fetch(`/api${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      throw new ApiError(
        "Relay could not reach the company graph. Check the backend and try again.",
        response.status,
      );
    }
    if (!response.ok) {
      const detail = (data as { detail?: unknown }).detail;
      throw new ApiError(
        typeof detail === "string"
          ? detail
          : "This request could not be completed. Check your input and try again.",
        response.status,
      );
    }
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted)
      throw new ApiError(
        "This request took too long. Your input is preserved; try again.",
      );
    throw new ApiError(
      "Relay is offline. Check the backend connection and try again.",
    );
  } finally {
    clearTimeout(timeout);
  }
}
export const api = {
  bootstrap: () => request<Bootstrap>("/bootstrap"),
  investigate: (question: string, session_id: string) =>
    request<Investigation>("/investigate", { question, session_id }),
  ripple: (origin_id: string, mitigation: boolean) =>
    request<Ripple>("/ripple", { origin_id, mitigation }),
  memory: () => request<{ items: Investigation[] }>("/memory"),
  actions: () => request<{ items: Action[] }>("/actions"),
  transition: (id: string, action: "approve" | "complete") =>
    request<Action>(`/actions/${encodeURIComponent(id)}/${action}`, {}),
  source: (id: string) => request<Source>(`/sources/${encodeURIComponent(id)}`),
  addSource: (title: string, content: string) =>
    request<Source>("/sources", { title, content, type: "document" }),
};
export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong. Try again.";
export const formatDate = (value: string) =>
  new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(
    new Date(value),
  );
