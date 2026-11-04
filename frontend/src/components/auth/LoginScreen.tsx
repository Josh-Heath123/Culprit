import { useState } from "react";

import { Standalone } from "@/components/layout/Page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { login } from "@/lib/api";

/** Shown whenever hooks/useAuth.ts's useAuthToken() is null — no token
 * yet, or one that just got dropped after a 401 (see lib/api.ts's
 * request()). The error line is the backend's own rejection reason, not a
 * generic "Something went wrong." */
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
    <Standalone>
      <Card surface="glass" className="w-full max-w-sm p-6 sm:p-8">
        <h1 className="text-lg font-semibold text-fg">Sign in</h1>
        <p className="mt-1 text-sm text-fg-muted">to this Culprit control plane.</p>
        <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="username" className="text-xs font-medium text-fg-muted">
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

          <div className="flex flex-col gap-1.5">
            <label htmlFor="password" className="text-xs font-medium text-fg-muted">
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

          {error ? (
            <p role="alert" className="rounded-md border border-fail-line bg-fail-tint px-3 py-2 text-xs text-fail">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={isSubmitting || !username || !password} className="mt-1 w-full">
            {isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </Standalone>
  );
}
