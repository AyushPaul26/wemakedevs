import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  errorMessage,
  invalidateApiSession,
  onSessionExpired,
  setApiSession,
} from "../api";
export type SessionView = {
  member: {
    id: string;
    display_name: string;
    role: "admin" | "operator" | "finance_auditor";
    department_ids: string[];
  };
  csrf_token: string;
  expires_at: string;
};
const AuthContext = createContext<{
  session: SessionView | null;
  loading: boolean;
  error: string;
  epoch: number;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}>({
  session: null,
  loading: true,
  error: "",
  epoch: 0,
  login: async () => {},
  logout: async () => {},
  refresh: async () => {},
});
export const useAuth = () => useContext(AuthContext);
export function AuthProvider({ children }: { children: ReactNode }) {
  const refreshSequence = useRef(0);
  const [session, setSession] = useState<SessionView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [epoch, setEpoch] = useState(0);
  const clear = useCallback(() => {
    invalidateApiSession();
    setSession(null);
    setEpoch((value) => value + 1);
    setError("");
  }, []);
  const refresh = useCallback(async () => {
    const request = ++refreshSequence.current;
    setLoading(true);
    setError("");
    try {
      const result = await api.request<SessionView>("/auth/session");
      if (request !== refreshSequence.current) return;
      setApiSession(result.csrf_token);
      setSession(result);
      setEpoch((value) => value + 1);
    } catch (err) {
      if (request !== refreshSequence.current) return;
      if ((err as { status?: number }).status !== 401)
        setError(errorMessage(err));
      setSession(null);
    } finally {
      if (request === refreshSequence.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    return onSessionExpired(clear);
  }, [clear, refresh]);
  useEffect(() => {
    if (!session) return;
    const delay = new Date(session.expires_at).valueOf() - Date.now();
    const timer = setTimeout(clear, Math.max(0, Math.min(delay, 2147483647)));
    return () => clearTimeout(timer);
  }, [session, clear]);
  async function login(username: string, password: string) {
    const result = await api.request<SessionView>("/auth/login", {
      method: "POST",
      body: { username, password },
    });
    setApiSession(result.csrf_token);
    setSession(result);
    setError("");
    setEpoch((value) => value + 1);
  }
  async function logout() {
    let failure = "";
    try {
      await api.request("/auth/logout", { method: "POST", body: {} });
    } catch (err) {
      if ((err as { status?: number }).status !== 401)
        failure =
          "Signed out locally. Server sign-out could not be confirmed. Retry the connection before signing in again.";
    } finally {
      refreshSequence.current++;
      clear();
      window.location.hash = "overview";
      if (failure) setError(failure);
    }
  }
  return (
    <AuthContext.Provider
      value={{ session, loading, error, epoch, login, logout, refresh }}
    >
      {children}
    </AuthContext.Provider>
  );
}
