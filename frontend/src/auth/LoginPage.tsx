import { useRef, useState } from "react";
import { GitBranch } from "lucide-react";
import { errorMessage } from "../api";
import { Button, Status } from "../components/ui";
export function LoginPage({
  onLogin,
}: {
  onLogin: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const loginRef = useRef<HTMLInputElement>(null);
  const active = useRef(false);
  return (
    <main className="login-page">
      <section className="login-card">
        <div className="brand">
          <span className="brand-mark">
            <GitBranch size={24} />
          </span>
          relay.
        </div>
        <span className="eyebrow">COMPANY WORKSPACE</span>
        <h1>Sign in to Relay</h1>
        <p>
          Use your assigned account to inspect evidence, start reviews, and
          respond to approvals.
        </p>
        <form
          noValidate
          onSubmit={async (event) => {
            event.preventDefault();
            if (active.current) return;
            if (!username.trim() || !password) {
              setError("Enter your username and password.");
              loginRef.current?.focus();
              return;
            }
            active.current = true;
            setBusy(true);
            setError("");
            try {
              await onLogin(username.trim(), password);
            } catch (err) {
              setError(errorMessage(err));
            } finally {
              setBusy(false);
              active.current = false;
            }
          }}
        >
          <label htmlFor="login-username">Username</label>
          <input
            id="login-username"
            ref={loginRef}
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            aria-invalid={!!error}
            aria-describedby={error ? "login-error" : undefined}
          />
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={!!error}
            aria-describedby={error ? "login-error" : undefined}
          />
          {error && (
            <div id="login-error">
              <Status error>{error}</Status>
            </div>
          )}
          <Button type="submit" variant="primary" busy={busy}>
            Sign in
          </Button>
        </form>
        <p className="muted">
          Accounts are provisioned by your workspace administrator.
        </p>
      </section>
    </main>
  );
}
