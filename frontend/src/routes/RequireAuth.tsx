import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuthToken } from "@/hooks/useAuth";

/** Gate for every route that needs a session. No token — including right
 * after lib/api.ts's request() clears one on a 401 — means an immediate
 * redirect to /login, carrying the route the user was actually trying to
 * reach as `?next=` so LoginScreen can send them back after signing in. */
export function RequireAuth() {
  const token = useAuthToken();
  const location = useLocation();

  if (!token) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return <Outlet />;
}
