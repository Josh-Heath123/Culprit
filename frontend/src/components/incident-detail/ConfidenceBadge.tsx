import { Badge } from "@/components/ui/badge";
import type { Confidence } from "@/lib/types";

/** High -> the confident accent ("this is the answer"). Medium -> a
 * plain neutral badge, no color claim either way. Low -> the one
 * deliberate use of the severity/warning amber outside the timeline: a
 * low-confidence hypothesis is a genuine "trust this less" signal, not
 * decoration. Red is never used here — Low confidence isn't a severity
 * of the incident itself. */
export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  if (confidence === "High") {
    return <Badge variant="primary">High confidence</Badge>;
  }
  if (confidence === "Low") {
    return <Badge variant="warning">Low confidence</Badge>;
  }
  return <Badge variant="outline">Medium confidence</Badge>;
}
