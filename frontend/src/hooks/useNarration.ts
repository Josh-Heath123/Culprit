import { useQuery } from "@tanstack/react-query";

import { fetchNarration } from "@/lib/api";

/** An investigation's narration (Phase 35 part 2). The worker writes one
 * row per finished attempt, so the state only moves when an attempt ends:
 * from "not narrated yet", or from a failed or refused attempt that has a
 * retry left. The poll picks that up; nothing here waits on it, and every
 * state is shown as text the moment it is read. */
export function useNarration(investigationId: string) {
  return useQuery({
    queryKey: ["narration", investigationId],
    queryFn: () => fetchNarration(investigationId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const retrying = (data.state === "failed" || data.state === "refused") && data.attempts < data.max_attempts;
      return data.state === "not_narrated" || retrying ? 15_000 : false;
    },
  });
}
