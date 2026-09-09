import { useQuery } from "@tanstack/react-query";

import { fetchComponents, fetchConnections } from "@/lib/api";
import type { ComponentOut, ConnectionOut } from "@/lib/types";

/** Phase 27: the system model, replacing the flat service list as what
 * Settings actually renders.
 *
 * Same conventions as useServices.ts, which this sits beside rather than
 * replaces: `/services` is a thin alias kept for one release (Phase 27
 * field 9) and other parts of the app still read it. Editing the model
 * is a rare, deliberate admin action, so a 30s poll is plenty — and
 * every mutation in SettingsServices.tsx invalidates these keys
 * directly, so the person who made the change sees it immediately
 * regardless of the interval.
 */
export function useComponents() {
  const query = useQuery({
    queryKey: ["model", "components"],
    queryFn: fetchComponents,
    refetchInterval: 30_000,
  });

  const components: ComponentOut[] = query.data?.items ?? [];
  return { ...query, components };
}

export function useConnections() {
  const query = useQuery({
    queryKey: ["model", "connections"],
    queryFn: fetchConnections,
    refetchInterval: 30_000,
  });

  const connections: ConnectionOut[] = query.data?.items ?? [];
  return { ...query, connections };
}

/** Every outgoing connection, grouped by source component name — the
 * shape the settings page renders a component's edges from. Grouping
 * here rather than filtering per row keeps it one pass instead of one
 * per component. */
export function connectionsBySource(
  connections: ConnectionOut[],
): Map<string, ConnectionOut[]> {
  const grouped = new Map<string, ConnectionOut[]>();
  for (const connection of connections) {
    const existing = grouped.get(connection.from_component);
    if (existing) existing.push(connection);
    else grouped.set(connection.from_component, [connection]);
  }
  return grouped;
}
