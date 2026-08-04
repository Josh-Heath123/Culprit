import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { login } from "@/lib/api";

/** Shown whenever hooks/useAuth.ts's useAuthToken() is null — no token
 * yet, or one that just got dropped after a 401 (see lib/api.ts's
 * request()). Same terse, specific voice as the rest of the app: the
 * error line is the backend's own rejection reason, not a generic
 * "Something went wrong." */
export function LoginScreen() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't sign in.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-8">
      <div className="flex items-center gap-2">
        <span className="size-2 rounded-full bg-primary" aria-hidden />
        <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
      </div>

      <form onSubmit={handleSubmit} className="flex w-72 flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="username" className="text-xs font-medium text-muted-foreground">
            Username
          </label>
          <Input
            id="username"
            autoFocus
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="password" className="text-xs font-medium text-muted-foreground">
            Password
          </label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        {error ? <p className="font-mono text-xs text-destructive">{error}</p> : null}

        <Button type="submit" disabled={isSubmitting || !username || !password} className="mt-1">
          {isSubmitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </div>
  );
}
