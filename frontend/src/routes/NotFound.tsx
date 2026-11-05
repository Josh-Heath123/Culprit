import { Link, useLocation } from "react-router-dom";

import { Standalone } from "@/components/layout/Page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/** A real 404, not the SPA silently falling through to the dashboard or
 * the login screen. Says what is actually wrong — this path, nothing here.
 * Caddy's `try_files {path} /index.html` serves the SPA shell with a 200
 * for any unmatched path; this is what renders inside it. */
export function NotFound() {
  const location = useLocation();

  return (
    <Standalone>
      <Card className="flex w-full max-w-md flex-col items-center gap-3 px-6 py-10 text-center" data-testid="not-found">
        <span className="font-mono text-2xs tracking-widest text-fg-subtle uppercase">404</span>
        <h1 className="text-lg font-semibold text-fg">Nothing lives at this URL.</h1>
        <p className="font-mono text-xs wrap-anywhere text-fg-muted">{location.pathname}</p>
        <Button asChild variant="outline" size="sm" className="mt-2">
          <Link to="/investigations">Go to investigations</Link>
        </Button>
      </Card>
    </Standalone>
  );
}
