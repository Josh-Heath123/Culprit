import { Link, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";

/** A real 404, not the SPA silently falling through to the dashboard or
 * the login screen — that gap is exactly what this phase exists to
 * close. Same terse, specific voice as EmptyState/ErrorState (Section
 * 3): says what's actually wrong — this path, nothing here — not a
 * generic "Oops!" or a page styled like a server error. Caddy's
 * `try_files {path} /index.html` always serves the SPA shell with a 200
 * for any unmatched path; this component is what renders inside it. */
export function NotFound() {
  const location = useLocation();

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-6 text-center">
      <div className="flex items-center gap-2">
        <span className="size-2 rounded-full bg-primary" aria-hidden />
        <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
      </div>

      <div className="flex flex-col gap-1">
        <p className="text-sm text-foreground">Nothing lives at this URL.</p>
        <p className="max-w-md font-mono text-xs text-muted-foreground">{location.pathname}</p>
      </div>

      <Button asChild variant="link" size="sm">
        <Link to="/">Back to the dashboard</Link>
      </Button>
    </div>
  );
}
