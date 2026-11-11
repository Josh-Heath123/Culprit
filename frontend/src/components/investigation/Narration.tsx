import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { formatDateTime } from "@/lib/datetime";
import type { NarrationSegment, NarrationView } from "@/lib/types";

/** The narrator's prose for this investigation (Phase 35 part 2), labelled
 * as derived. It is never a finding: the fault tree, the readings and the
 * rubric on this page are, and the prose only restates them. The API
 * checked it against this investigation before serving it, and each
 * citation arrives already replaced by its evidence item's own text, taken
 * from the record — so a citation is shown as that text, not as anything
 * the model wrote.
 *
 * Rendered as text, always: React escapes every string, and nothing here
 * interprets markdown or HTML, so `**bold**` or `<img>` in the prose shows
 * as those characters. There is no link and no image in this component. */
export function Narration({ narration }: { narration: NarrationView | undefined }) {
  const state = narration?.state;
  return (
    <Card aria-labelledby="narration-heading" data-testid="narration" data-state={state ?? "loading"}>
      <CardHeader
        id="narration-heading"
        title="Narration"
        trailing={
          <Badge variant="outline" data-testid="narration-derived">
            Derived
          </Badge>
        }
      />
      <CardBody className="flex flex-col gap-3">
        {narration ? <NarrationBody narration={narration} /> : null}
      </CardBody>
    </Card>
  );
}

function NarrationBody({ narration }: { narration: NarrationView }) {
  const attempt = `attempt ${narration.attempts} of ${narration.max_attempts}`;
  switch (narration.state) {
    case "off":
      return (
        <p className="text-sm text-fg-muted" data-testid="narration-off">
          Narration is off. Everything on this page is the walk&apos;s own record; prose would only restate it.
        </p>
      );
    case "not_narrated":
      return (
        <p className="text-sm text-fg-muted" data-testid="narration-not-narrated">
          Not narrated yet: no attempt has finished for this investigation.
        </p>
      );
    case "failed":
      return (
        <p className="text-sm text-fg-muted" data-testid="narration-failed">
          Narration failed ({attempt}): <span className="text-fg">{narration.reason}</span>
          {narration.attempts < narration.max_attempts ? " It will be tried again." : " No further attempt is made."}
        </p>
      );
    case "refused":
      return (
        <div className="flex flex-col gap-2" data-testid="narration-refused">
          <p className="text-sm text-fg-muted">
            Narration refused ({attempt}): the prose named things this investigation does not hold, so it is not shown.
          </p>
          <ul className="flex flex-wrap gap-1.5" aria-label="What the prose named">
            {(narration.named ?? []).map((name) => (
              <li key={name}>
                <code className="rounded-sm bg-surface-2 px-1 font-mono text-code wrap-anywhere text-fg">{name}</code>
              </li>
            ))}
          </ul>
        </div>
      );
    case "complete":
      return (
        <>
          <p className="text-sm leading-relaxed whitespace-pre-line text-fg" data-testid="narration-prose">
            {(narration.segments ?? []).map((segment, index) => (
              <Segment key={index} segment={segment} />
            ))}
          </p>
          <p className="text-xs text-fg-subtle" data-testid="narration-source">
            Written by {narration.provider}
            {narration.model ? ` (${narration.model})` : ""}
            {narration.narrated_at ? ` on ${formatDateTime(narration.narrated_at)}` : ""} from this investigation&apos;s
            evidence, and checked against it. Not a finding: the fault tree and readings are.
          </p>
        </>
      );
  }
}

/** A citation is shown as the evidence item it cites, in the record's words. */
function Segment({ segment }: { segment: NarrationSegment }) {
  if (segment.evidence == null) return <>{segment.text}</>;
  return (
    <q
      className="rounded-sm border border-line bg-surface-2 px-1 text-xs text-fg-muted"
      data-testid="narration-evidence"
      data-evidence={segment.evidence}
      title={`Evidence ${segment.evidence}, from the record`}
    >
      {segment.text}
    </q>
  );
}
