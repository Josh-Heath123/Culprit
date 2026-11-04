import { useQuery } from "@tanstack/react-query";

import { ApiError, fetchInvestigationTree, fetchInvestigations } from "@/lib/api";

/** The newest 100. There is no "load more" yet: an investigation is one
 * `culprit diagnose` run, posted by hand or by CI, not a stream. */
export function useInvestigations() {
  return useQuery({
    queryKey: ["investigations"],
    queryFn: () => fetchInvestigations(100),
    refetchInterval: 30_000,
  });
}

/** No refetch interval: a stored investigation never changes — the tables
 * are append-only and investigation-writer has no UPDATE. */
export function useInvestigationTree(id: string) {
  return useQuery({
    queryKey: ["investigation", id],
    queryFn: () => fetchInvestigationTree(id),
    // A 404 will be a 404 again: retry only what might succeed.
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 1,
  });
}
