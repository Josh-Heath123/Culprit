import { useQuery } from "@tanstack/react-query";

import { fetchCurrentUser } from "@/lib/api";

/** Only ever called from behind RequireAuth (AppHeader.tsx, SettingsUsers.tsx)
 * — no token, no point querying. Role/disabled changes made by another
 * admin mid-session are picked up on the query's normal
 * refetch-on-focus behavior, same as everything else in src/hooks/;
 * nothing here needs to be instant, since the server itself (require_auth's
 * cache, api/app/auth/dependencies.py) already bounds how quickly a
 * disabled account's own requests start failing regardless of what this
 * hook shows. */
export function useCurrentUser() {
  return useQuery({
    queryKey: ["currentUser"],
    queryFn: fetchCurrentUser,
  });
}
