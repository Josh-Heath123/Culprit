import { useQuery } from "@tanstack/react-query";

import { fetchUsers } from "@/lib/api";
import type { UserOut } from "@/lib/types";

/** Same conventions as useServices.ts — /settings/users is an admin-only
 * page, so this only ever runs there; mutations invalidate this query
 * directly (see SettingsUsers.tsx), the poll is just a backstop for a
 * second admin's changes showing up. */
export function useUsers() {
  const query = useQuery({
    queryKey: ["users"],
    queryFn: fetchUsers,
    refetchInterval: 30_000,
  });

  const users: UserOut[] = query.data?.items ?? [];
  return { ...query, users };
}
