import { useQuery } from "@tanstack/react-query";

import { fetchVerifications } from "@/lib/api";

/** An investigation's verifications, newest first (Phase 34 part 2). Each
 * is an append-only record; a new one appears when an agent finishes a
 * verify task, which invalidates this query, and on the poll besides — a
 * verification can also be posted by CI. */
export function useVerifications(investigationId: string) {
  return useQuery({
    queryKey: ["verifications", investigationId],
    queryFn: () => fetchVerifications(investigationId),
    refetchInterval: 30_000,
  });
}
