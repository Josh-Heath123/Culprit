import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { Hypothesis, InvestigationTree } from "@/lib/types";
import { Prose } from "@/components/ui/prose";
import { hypothesisLabel } from "@/lib/hypotheses";

const GROUPS = [
  ["supported", "Supported", "the readings confirm it"],
  ["ruled_out", "Ruled out", "a reading showed it does not hold"],
  ["unexplored", "Unexplored", "needed, and could not be tested — a refusal, or no probe could tell"],
  ["untested", "Untested", "the walk did not need them; neither ruled in nor out"],
] as const;

/** Every hypothesis the walk generated, in its four groups. Unexplored
 * and untested are kept apart: one is a gap the walk ran into, the other
 * a branch it never needed. */
export function Hypotheses({ groups }: { groups: InvestigationTree["hypotheses"] }) {
  const total = GROUPS.reduce((sum, [key]) => sum + groups[key].length, 0);
  return (
    <Card aria-labelledby="hypotheses-heading">
      <CardHeader id="hypotheses-heading" title="Hypotheses" trailing={<span className="text-2xs text-fg-subtle">{total}</span>} />
      <CardBody className="flex flex-col gap-5">
        {GROUPS.map(([key, title, caption]) => {
          const items: Hypothesis[] = groups[key];
          return (
            <section key={key} className="flex flex-col gap-2" data-testid={`hypotheses-${key}`}>
              <h3 className="text-sm font-medium text-fg">
                {title} <span className="font-mono text-xs text-fg-subtle">{items.length}</span>
              </h3>
              <p className="text-xs text-fg-muted">{caption}</p>
              {items.length > 0 ? (
                <ul className="flex flex-col divide-y divide-line rounded-md border border-line">
                  {items.map((h) => (
                    <li key={h.id} className="flex min-w-0 flex-col gap-1 px-3 py-2.5">
                      <span className="text-sm font-medium text-fg" data-testid="hypothesis-label">
                        {hypothesisLabel(h.kind)}
                      </span>
                      <span className="font-mono text-2xs text-fg-subtle">{h.kind}</span>
                      <span className="font-mono text-2xs wrap-anywhere text-fg-muted">{h.subject}</span>
                      {h.reason ? (
                        <span className="text-xs leading-relaxed text-fg-muted">
                          <Prose text={h.reason} />
                        </span>
                      ) : null}
                      {h.readings.length > 0 ? (
                        <span className="font-mono text-2xs text-fg-subtle">cites {h.readings.join(", ")}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          );
        })}
      </CardBody>
    </Card>
  );
}
