import { Link, Outlet } from "react-router-dom";

import { Standalone } from "@/components/layout/Page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useCurrentUser } from "@/hooks/useCurrentUser";

/** The settings pages are admin-only on the server (`require_admin` on
 * `/model` and `/users`). The header hides their links from a member, but
 * the URLs still resolve, and a member who reached one would get forms
 * that can only fail with a 403 (Phase 31.2 truth pass). This says so
 * instead, and mounts nothing that would send those requests. */
export function RequireAdmin() {
  const { data: me, isPending } = useCurrentUser();

  if (isPending) return null;
  if (me?.role === "admin") return <Outlet />;

  return (
    <Standalone>
      <Card className="flex w-full max-w-md flex-col items-center gap-3 px-6 py-10 text-center" data-testid="admins-only">
        <h1 className="text-lg font-semibold text-fg">This page is for admins.</h1>
        <p className="text-sm text-fg-muted">An admin can change your role under Settings → Users.</p>
        <Button asChild variant="outline" size="sm" className="mt-2">
          <Link to="/investigations">Go to investigations</Link>
        </Button>
      </Card>
    </Standalone>
  );
}
