import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  acceptTopologySuggestion,
  dismissTopologySuggestion,
  fetchTopologySuggestions,
} from "@/lib/api";
import type { TopologyEdgeRef, TopologySuggestionOut } from "@/lib/types";

/** Same 30s-poll convention as useModel.ts — a rare, deliberate admin
 * action, not something another tab needs to see within seconds. */
export function useTopologySuggestions() {
  const query = useQuery({
    queryKey: ["topology-suggestions"],
    queryFn: fetchTopologySuggestions,
    refetchInterval: 30_000,
  });

  const suggestions: TopologySuggestionOut[] = query.data?.items ?? [];
  return { ...query, suggestions };
}

export function useAcceptTopologySuggestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (edge: TopologyEdgeRef) => acceptTopologySuggestion(edge),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["topology-suggestions"] });
      // Accepting inserts a `connections` row (declared_by
      // accepted_suggestion) — the model's connection list just became
      // stale.
      queryClient.invalidateQueries({ queryKey: ["model"] });
    },
  });
}

export function useDismissTopologySuggestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (edge: TopologyEdgeRef) => dismissTopologySuggestion(edge),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["topology-suggestions"] }),
  });
}
