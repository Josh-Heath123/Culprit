import { useState } from "react";
import { Link } from "react-router-dom";

import { ChangePasswordDialog } from "@/components/auth/ChangePasswordDialog";
import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { logout } from "@/lib/api";

interface NavProps {
  totalIncidents: number;
}

export function Nav({ totalIncidents }: NavProps) {
  const { data: currentUser } = useCurrentUser();
  const [changingPassword, setChangingPassword] = useState(false);
  const isAdmin = currentUser?.role === "admin";

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
      <div className="flex items-center gap-2">
        <Link to="/" className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-primary" aria-hidden />
          <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
        </Link>
        <span className="font-mono text-xs text-muted-foreground">
          {totalIncidents} incident{totalIncidents === 1 ? "" : "s"}
        </span>
      </div>
      <div className="flex items-center gap-3">
        {/* Not admin-gated, unlike Services/Users below — any
         * authenticated team member may read and write postmortems
         * (docs/SELF_HOSTED_PLAN.md Phase 18). */}
        <Link to="/postmortems" className="text-xs text-muted-foreground hover:text-foreground">
          Postmortems
        </Link>
        {/* Hiding is UX only (docs/SELF_HOSTED_PLAN.md Phase 16) — every
         * admin route is enforced server-side (require_admin), a member
         * who guesses the URL gets a real 403, not just a missing link. */}
        {isAdmin ? (
          <>
            <Link to="/settings/services" className="text-xs text-muted-foreground hover:text-foreground">
              Services
            </Link>
            <Link to="/settings/users" className="text-xs text-muted-foreground hover:text-foreground">
              Users
            </Link>
          </>
        ) : null}
        <kbd className="rounded-sm border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
          ⌘K to jump
        </kbd>
        {currentUser ? (
          <div className="flex items-center gap-2 border-l border-border pl-3">
            <span className="text-xs text-muted-foreground">
              {currentUser.username}{" "}
              <span className="text-muted-foreground/60">({currentUser.role})</span>
            </span>
            <Button variant="ghost" size="sm" onClick={() => setChangingPassword(true)}>
              Change password
            </Button>
            <Button variant="ghost" size="sm" onClick={logout}>
              Log out
            </Button>
          </div>
        ) : null}
      </div>

      {changingPassword ? <ChangePasswordDialog onClose={() => setChangingPassword(false)} /> : null}
    </header>
  );
}
