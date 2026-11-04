import { Link, Outlet } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/hooks/useCurrentUser";

/** The settings pages are admin-only on the server (`require_admin` on
 * `/model` and `/users`). The nav already hides their links from a
 * member, but the URLs still resolved, and a member who reached one got
 * the admin's forms — "Create a user", "Create component" — every one of
 * which could only fail with a 403 (Phase 31.2 truth pass). This says so
 * instead, and mounts nothing that would send those requests. */
export function RequireAdmin() {
  const { data: me, isPending } = useCurrentUser();

  if (isPending) return null;
  if (me?.role === "admin") return <Outlet />;

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-6 text-center">
      <div className="flex items-center gap-2">
        <span className="size-2 rounded-full bg-primary" aria-hidden />
        <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
      </div>
      <p className="text-sm text-foreground">This page is for admins.</p>
      <Button asChild variant="link" size="sm">
        <Link to="/">Back to the dashboard</Link>
      </Button>
    </div>
  );
}
