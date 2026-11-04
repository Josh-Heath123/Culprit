import { useMemo } from "react";
import { AxisBottom } from "@visx/axis";
import { GridColumns } from "@visx/grid";
import { Group } from "@visx/group";
import { scaleBand, scaleTime } from "@visx/scale";

import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useElementSize } from "@/hooks/useElementSize";
import { useComponents } from "@/hooks/useModel";
import { markRadiusFor, severityColorVar, severityFor } from "@/lib/severity";
import type { ComponentOut, IncidentSummary } from "@/lib/types";

interface TimelineProps {
  incidents: IncidentSummary[];
  selectedIncidentId: string | null;
  onSelectIncident: (id: string) => void;
}

type Lane = Pick<ComponentOut, "name" | "disabled">;

interface TimelineChartProps extends TimelineProps {
  services: Lane[];
  width: number;
  height: number;
}

const MARGIN = { top: 12, right: 24, bottom: 28, left: 140 };
const LANE_PADDING = 0.35;

/** Lane-per-service layout, dense marks, cross-lane incident bands —
 * this is the product's signature view (Section 3), not a generic line
 * chart with hover tooltips as the primary interaction. Auto-sized to
 * its container (see src/hooks/useElementSize.ts); no fixed pixel
 * dimensions. */
export function Timeline(props: TimelineProps) {
  const { ref, width, height } = useElementSize<HTMLDivElement>();
  // One lane per registered component. GET /services served exactly
  // this list (every component, whatever its kind) until Phase 30.
  //
  // /model is admin-only, so for a member that request could only 403
  // and the timeline drew no lanes at all — incidents counted in the
  // header, nothing on the chart (Phase 31.2 truth pass). A member's
  // lanes are the services the incidents themselves name instead.
  const { data: me } = useCurrentUser();
  const isAdmin = me?.role === "admin";
  const { components } = useComponents({ enabled: isAdmin });
  const services = useMemo<Lane[]>(() => {
    if (isAdmin) return components;
    const named = new Set<string>();
    for (const incident of props.incidents) {
      incident.services.forEach((s) => named.add(s));
      incident.anomalies.forEach((a) => named.add(a.service_name));
    }
    return [...named].sort().map((name) => ({ name, disabled: false }));
  }, [isAdmin, components, props.incidents]);
  return (
    <div ref={ref} className="h-full w-full min-h-64">
      {width > 0 && height > 0 ? (
        <TimelineChart {...props} services={services} width={width} height={height} />
      ) : null}
    </div>
  );
}

function TimelineChart({
  incidents,
  selectedIncidentId,
  onSelectIncident,
  services,
  width,
  height,
}: TimelineChartProps) {
  const innerWidth = Math.max(0, width - MARGIN.left - MARGIN.right);
  const innerHeight = Math.max(0, height - MARGIN.top - MARGIN.bottom);

  // Lanes are only active (non-disabled) services, in the order the
  // registry API already returns them (sort_order, then name) — a
  // disabled service stops showing a lane (docs/SELF_HOSTED_PLAN.md
  // Phase 14, step 9), even though its historical incidents remain
  // fully visible. `knownServices` below deliberately stays built from
  // the FULL fetched list, disabled included: an anomaly can legitimately
  // arrive from a service that was disabled a second ago, and the guard
  // it feeds is about dropping anomalies from services this install has
  // never heard of at all, not ones mid-disablement.
  const laneServiceNames = useMemo(
    () => services.filter((s) => !s.disabled).map((s) => s.name),
    [services],
  );

  const { xScale, yScale, bands, marks } = useMemo(() => {
    const now = Date.now();
    // closed_at too: a band ends at closed_at when there is one (below),
    // and an incident closes a quiet window after its last anomaly, so
    // leaving it out of the domain drew the newest closed incident's band
    // past the axis and under the detail panel, where it could not be
    // clicked (Phase 31.2 truth pass).
    const allTimes = incidents.flatMap((incident) => [
      new Date(incident.opened_at).getTime(),
      new Date(incident.last_anomaly_at).getTime(),
      ...(incident.closed_at ? [new Date(incident.closed_at).getTime()] : []),
      ...incident.anomalies.map((a) => new Date(a.detected_at).getTime()),
    ]);
    const minTime = allTimes.length ? Math.min(...allTimes) : now - 4 * 60 * 60 * 1000;
    const maxTime = allTimes.length ? Math.max(...allTimes) : now;
    const pad = Math.max((maxTime - minTime) * 0.05, 60_000);

    const xScale = scaleTime({
      domain: [new Date(minTime - pad), new Date(maxTime + pad)],
      range: [0, innerWidth],
    });
    const yScale = scaleBand<string>({
      domain: laneServiceNames,
      range: [0, innerHeight],
      padding: LANE_PADDING,
    });

    const knownServices = new Set<string>(services.map((s) => s.name));

    const bands = incidents
      .map((incident) => {
        const laneServices = incident.services.filter((s) => knownServices.has(s));
        if (laneServices.length === 0) return null;
        const ys = laneServices.map((s) => yScale(s) ?? 0);
        const y0 = Math.min(...ys);
        const y1 = Math.max(...ys) + yScale.bandwidth();
        const x0 = xScale(new Date(incident.opened_at));
        const x1 = Math.max(xScale(new Date(incident.closed_at ?? incident.last_anomaly_at)), x0 + 4);
        return { incident, x0, x1, y0, y1 };
      })
      .filter((b): b is NonNullable<typeof b> => b !== null);

    const marks = incidents.flatMap((incident) =>
      incident.anomalies
        .filter((a) => knownServices.has(a.service_name))
        .map((anomaly) => ({
          anomaly,
          incidentId: incident.id,
          cx: xScale(new Date(anomaly.detected_at)),
          cy: (yScale(anomaly.service_name) ?? 0) + yScale.bandwidth() / 2,
        })),
    );

    return { xScale, yScale, bands, marks };
  }, [incidents, services, laneServiceNames, innerWidth, innerHeight]);

  return (
    <svg width={width} height={height} role="img" aria-label="Incident timeline by service">
      <Group left={MARGIN.left} top={MARGIN.top}>
        <GridColumns
          scale={xScale}
          height={innerHeight}
          stroke="var(--border)"
          strokeOpacity={0.5}
          numTicks={8}
        />

        {laneServiceNames.map((service) => {
          const y = yScale(service) ?? 0;
          return (
            <g key={service}>
              <line
                x1={0}
                x2={innerWidth}
                y1={y + yScale.bandwidth()}
                y2={y + yScale.bandwidth()}
                stroke="var(--border)"
                strokeOpacity={0.5}
              />
              <text
                x={-12}
                y={y + yScale.bandwidth() / 2}
                dy="0.35em"
                textAnchor="end"
                className="fill-muted-foreground font-mono text-[11px]"
              >
                {service}
              </text>
            </g>
          );
        })}

        {bands.map(({ incident, x0, x1, y0, y1 }) => {
          const selected = incident.id === selectedIncidentId;
          return (
            <rect
              key={incident.id}
              x={x0}
              y={y0 - 4}
              width={Math.max(x1 - x0, 4)}
              height={y1 - y0 + 8}
              rx={4}
              className={
                selected
                  ? "cursor-pointer fill-primary/15 stroke-primary"
                  : "cursor-pointer fill-secondary/50 stroke-border hover:fill-secondary/80"
              }
              strokeWidth={selected ? 1.5 : 1}
              onClick={() => onSelectIncident(incident.id)}
            />
          );
        })}

        {marks.map(({ anomaly, incidentId, cx, cy }) => {
          const severity = severityFor(anomaly.score);
          return (
            <circle
              key={anomaly.id}
              cx={cx}
              cy={cy}
              r={markRadiusFor(anomaly.score)}
              fill={severityColorVar(severity)}
              fillOpacity={0.9}
              stroke="var(--background)"
              strokeWidth={1}
              className="cursor-pointer"
              onClick={() => onSelectIncident(incidentId)}
            >
              <title>
                {anomaly.metric_name} on {anomaly.service_name}: z={anomaly.score.toFixed(2)}
              </title>
            </circle>
          );
        })}

        <AxisBottom
          top={innerHeight}
          scale={xScale}
          numTicks={8}
          stroke="var(--border)"
          tickStroke="var(--border)"
          tickLabelProps={() => ({
            className: "fill-muted-foreground font-mono text-[10px]",
            textAnchor: "middle",
          })}
        />
      </Group>
    </svg>
  );
}
