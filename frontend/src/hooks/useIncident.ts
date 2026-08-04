import { useQuery } from "@tanstack/react-query";

import { fetchIncident } from "@/lib/api";

export function useIncident(id: string | null) {
  return useQuery({
    queryKey: ["incident", id],
    queryFn: () => fetchIncident(id as string),
    enabled: id !== null,
    // A pending narrative can complete between polls without the user
    // doing anything — keep it live while a detail panel is open rather
    // than requiring a manual refresh to see it flip from pending to ready.
    refetchInterval: (query) => (query.state.data?.root_cause_status === "pending" ? 4_000 : false),
  });
}
