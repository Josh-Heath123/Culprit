import { useInfiniteQuery } from "@tanstack/react-query";

import { fetchIncidents } from "@/lib/api";
import type { IncidentSummary } from "@/lib/types";

const PAGE_SIZE = 50;

/** Accumulates pages into one flat, already-loaded list — this is what
 * both the timeline (needs every loaded anomaly across all incidents)
 * and the command palette (client-side search over already-loaded
 * incidents, per Phase 8's scope) read from. Pagination itself (the
 * actual limit/offset requests) still goes through GET /incidents one
 * page at a time; nothing here requests "all incidents ever" in one call.
 */
export function useIncidents() {
  const query = useInfiniteQuery({
    queryKey: ["incidents"],
    queryFn: ({ pageParam }) => fetchIncidents(PAGE_SIZE, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const loaded = lastPage.offset + lastPage.items.length;
      return loaded < lastPage.total ? loaded : undefined;
    },
    refetchInterval: 15_000,
  });

  const incidents: IncidentSummary[] = query.data?.pages.flatMap((page) => page.items) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  return { ...query, incidents, total };
}
