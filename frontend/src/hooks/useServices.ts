import { useQuery } from "@tanstack/react-query";

import { fetchServices } from "@/lib/api";
import type { ServiceOut } from "@/lib/types";

/** Same conventions as useIncidents.ts. Registering/editing a service
 * through /settings/services is a rare, deliberate admin action, not
 * something another tab needs to see within seconds — a 30s poll is
 * plenty and mutations (see SettingsServices.tsx) invalidate this query
 * directly anyway, so the person who just made the change always sees
 * it immediately regardless of the poll interval. */
export function useServices() {
  const query = useQuery({
    queryKey: ["services"],
    queryFn: fetchServices,
    refetchInterval: 30_000,
  });

  const services: ServiceOut[] = query.data?.items ?? [];
  return { ...query, services };
}
