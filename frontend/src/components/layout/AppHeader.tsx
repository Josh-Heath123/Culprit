import { MenuIcon } from "lucide-react";
import { useState } from "react";
import { Link, NavLink } from "react-router-dom";

import { ChangePasswordDialog } from "@/components/auth/ChangePasswordDialog";
import { Brand } from "@/components/layout/Brand";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { logout } from "@/lib/api";
import { cn } from "@/lib/utils";

/** The one header (Phase 32.1). Glass, because it sits over the page as
 * it scrolls. Below 768 px the links fold into a menu rather than
 * shrinking, and below 1024 px the account actions do. Every signed-in
 * page has it (components/layout/Page.tsx). */
interface Item {
  to: string;
  label: string;
  admin?: boolean;
  /** An earlier engine's record, still readable (Phase 32 part 2). */
  history?: boolean;
}

const ITEMS: Item[] = [
  { to: "/investigations", label: "Investigations" },
  { to: "/incidents", label: "Incidents", history: true },
  { to: "/postmortems", label: "Postmortems" },
  { to: "/settings/services", label: "Services", admin: true },
  { to: "/settings/users", label: "Users", admin: true },
  { to: "/settings/agents", label: "Agents", admin: true },
];

export function AppHeader() {
  const { data: currentUser } = useCurrentUser();
  const [changingPassword, setChangingPassword] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const items = ITEMS.filter((item) => !item.admin || currentUser?.role === "admin");

  return (
    <header className="sticky top-0 z-40 border-b border-glass-line bg-glass backdrop-blur-glass">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Link to="/investigations" className="flex shrink-0 items-center gap-2 rounded-md">
          <Brand />
        </Link>

        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {items.map((item) => (
            <NavItem key={item.to} item={item} />
          ))}
        </nav>

        <div className="min-w-0 flex-1" />

        {currentUser ? (
          <div className="hidden items-center gap-1 lg:flex">
            <span className="flex items-center gap-1.5 px-2 text-xs text-fg-muted">
              {currentUser.username}
              <Badge variant={currentUser.role === "admin" ? "primary" : "outline"}>{currentUser.role}</Badge>
            </span>
            <Button variant="ghost" size="sm" onClick={() => setChangingPassword(true)}>
              Change password
            </Button>
            <Button variant="ghost" size="sm" onClick={logout}>
              Log out
            </Button>
          </div>
        ) : null}

        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          aria-label="Open menu"
          onClick={() => setMenuOpen(true)}
        >
          <MenuIcon />
        </Button>
      </div>

      <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
        <DialogContent
          aria-describedby={undefined}
          className="top-16 max-w-none p-2"
        >
          <DialogTitle className="px-3 pt-2 pb-1 text-2xs tracking-widest text-fg-subtle uppercase">
            Menu
          </DialogTitle>
          <nav aria-label="Main" className="flex flex-col">
            {items.map((item) => (
              <DialogClose asChild key={item.to}>
                <NavItem item={item} block />
              </DialogClose>
            ))}
          </nav>
          {currentUser ? (
            <div className="mt-2 flex flex-col border-t border-line pt-2">
              <span className="flex items-center gap-1.5 px-3 py-2 text-xs text-fg-muted">
                {currentUser.username}
                <Badge variant={currentUser.role === "admin" ? "primary" : "outline"}>{currentUser.role}</Badge>
              </span>
              <Button
                variant="ghost"
                className="justify-start"
                onClick={() => {
                  setMenuOpen(false);
                  setChangingPassword(true);
                }}
              >
                Change password
              </Button>
              <Button variant="ghost" className="justify-start" onClick={logout}>
                Log out
              </Button>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      {changingPassword ? <ChangePasswordDialog onClose={() => setChangingPassword(false)} /> : null}
    </header>
  );
}

function NavItem({ item, block = false, ...props }: { item: Item; block?: boolean } & React.ComponentProps<"a">) {
  return (
    <NavLink
      {...props}
      to={item.to}
      end={item.to === "/incidents"}
      className={({ isActive }) =>
        cn(
          "rounded-md px-2.5 py-1.5 text-sm transition-colors duration-150",
          block && "px-3 py-2.5",
          isActive ? "bg-surface-3 text-fg" : "text-fg-muted hover:bg-surface-2 hover:text-fg",
        )
      }
    >
      {item.label}
      {item.history ? <span className="ml-1 text-2xs text-fg-subtle">history</span> : null}
    </NavLink>
  );
}
