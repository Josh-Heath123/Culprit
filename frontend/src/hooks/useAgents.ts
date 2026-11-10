import { useQuery } from "@tanstack/react-query";

import { fetchAgents } from "@/lib/api";
import type { AgentSummary } from "@/lib/types";

/** Every paired agent. Polled so a newly paired agent appears, and its last
 * signed request moves, without a reload; mutations invalidate it directly. */
export function useAgents({ enabled = true }: { enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
    refetchInterval: 5_000,
    enabled,
  });
  const agents: AgentSummary[] = query.data?.items ?? [];
  return { ...query, agents };
}
