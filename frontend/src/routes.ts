export type View =
  "overview" | "knowledge" | "memory" | "actions" | "workflows" | "approvals";
export function readRoute() {
  const [view, id] = window.location.hash.slice(1).split("/");
  return {
    view: ([
      "overview",
      "knowledge",
      "memory",
      "actions",
      "workflows",
      "approvals",
    ].includes(view)
      ? view
      : "overview") as View,
    id: id ? decodeURIComponent(id) : undefined,
  };
}
