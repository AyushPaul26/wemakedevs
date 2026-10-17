import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../../api";
import { useAuth } from "../../auth/AuthProvider";
import { newerSnapshot } from "./state";
import type { RunSnapshot } from "./types";
export function useWorkflowRun(runId?: string) {
  const { epoch } = useAuth();
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const sequence = useRef(0);
  const accept = useCallback(
    (incoming: RunSnapshot) =>
      setRun((current) =>
        current?.id === incoming.id
          ? newerSnapshot(current, incoming)
          : incoming,
      ),
    [],
  );
  useEffect(() => {
    setRun((current) => (current?.id === runId ? current : null));
    setError("");
    if (!runId) return;
    const request = ++sequence.current;
    let controller: AbortController | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    let pollSequence = 0;
    const poll = async () => {
      if (closed) return;
      if (document.visibilityState === "hidden") {
        timer = setTimeout(poll, 2000);
        return;
      }
      const pollRequest = ++pollSequence;
      const currentController = new AbortController();
      controller = currentController;
      setLoading(true);
      try {
        const incoming = await api.run(runId, currentController.signal);
        if (
          !closed &&
          !currentController.signal.aborted &&
          sequence.current === request &&
          pollRequest === pollSequence
        ) {
          accept(incoming);
          setError("");
        }
        if (
          !closed &&
          !["completed", "cancelled", "rejected"].includes(incoming.status)
        )
          timer = setTimeout(poll, 2000);
      } catch (err) {
        if (
          !closed &&
          !currentController.signal.aborted &&
          pollRequest === pollSequence
        ) {
          setError(errorMessage(err));
          timer = setTimeout(poll, 4000);
        }
      } finally {
        if (!closed) setLoading(false);
      }
    };
    void poll();
    const visible = () => {
      if (document.visibilityState === "visible") {
        clearTimeout(timer);
        controller?.abort();
        void poll();
      }
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      closed = true;
      sequence.current++;
      controller?.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [runId, epoch, refresh, accept]);
  return {
    run,
    loading,
    error,
    refresh: () => setRefresh((value) => value + 1),
    accept,
  };
}
