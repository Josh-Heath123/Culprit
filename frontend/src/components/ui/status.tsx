import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleHelpIcon,
  CircleXIcon,
  LockIcon,
  type LucideIcon,
  OctagonAlertIcon,
  TriangleAlertIcon,
  TypeIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";

/** Status, never by colour alone: each one is a colour token, an icon of
 * its own shape, and the word. The verdicts are §2.7's four; the
 * severities §2.5's four. */
export type Verdict = "pass" | "fail" | "inconclusive" | "refused";
export type Severity = "breaks_request_path" | "degrades" | "cosmetic" | "unknown";

const VERDICT: Record<Verdict, LucideIcon> = {
  pass: CircleCheckIcon,
  fail: CircleXIcon,
  inconclusive: CircleHelpIcon,
  refused: LockIcon,
};

const SEVERITY: Record<
  Severity,
  { icon: LucideIcon; variant: "breaks" | "degrades" | "cosmetic" | "unknown"; label: string }
> = {
  breaks_request_path: { icon: OctagonAlertIcon, variant: "breaks", label: "breaks request path" },
  degrades: { icon: TriangleAlertIcon, variant: "degrades", label: "degrades" },
  cosmetic: { icon: TypeIcon, variant: "cosmetic", label: "cosmetic" },
  unknown: { icon: CircleDashedIcon, variant: "unknown", label: "unknown" },
};

export function VerdictBadge({ verdict, className }: { verdict: Verdict; className?: string }) {
  const Icon = VERDICT[verdict];
  return (
    <Badge variant={verdict} className={className} data-verdict={verdict}>
      <Icon aria-hidden className="size-3" />
      {verdict}
    </Badge>
  );
}

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const { icon: Icon, variant, label } = SEVERITY[severity];
  return (
    <Badge variant={variant} className={className} data-severity={severity}>
      <Icon aria-hidden className="size-3" />
      {label}
    </Badge>
  );
}

/** A verification's verdict (Phase 34): five, a closed set, each with its
 * own tone, icon and word. `regressed` takes the breaks tone — the fix broke
 * something that worked — and `changed_underneath` the degrades one. */
export type VerificationVerdict = "verified" | "not_resolved" | "regressed" | "changed_underneath" | "inconclusive";

const VERIFICATION: Record<
  VerificationVerdict,
  { icon: LucideIcon; variant: "pass" | "fail" | "breaks" | "degrades" | "inconclusive"; label: string }
> = {
  verified: { icon: CircleCheckIcon, variant: "pass", label: "verified" },
  not_resolved: { icon: CircleXIcon, variant: "fail", label: "not resolved" },
  regressed: { icon: OctagonAlertIcon, variant: "breaks", label: "regressed" },
  changed_underneath: { icon: TriangleAlertIcon, variant: "degrades", label: "changed underneath" },
  inconclusive: { icon: CircleHelpIcon, variant: "inconclusive", label: "inconclusive" },
};

export function VerificationBadge({ verdict, className }: { verdict: VerificationVerdict; className?: string }) {
  const { icon: Icon, variant, label } = VERIFICATION[verdict];
  return (
    <Badge variant={variant} className={className} data-verification-verdict={verdict}>
      <Icon aria-hidden className="size-3" />
      {label}
    </Badge>
  );
}

/** Whether the walk reached a diagnosis and finished. A partial one is
 * where the walk stopped — the inconclusive tone, never the fail one,
 * because nothing was shown to be the fault. */
export function DiagnosisBadge({ complete, className }: { complete: boolean | null; className?: string }) {
  if (complete === null) {
    return (
      <Badge variant="unknown" className={className} data-diagnosis="none">
        <CircleDashedIcon aria-hidden className="size-3" />
        no diagnosis
      </Badge>
    );
  }
  return complete ? (
    <Badge variant="primary" className={className} data-diagnosis="complete">
      <CircleCheckIcon aria-hidden className="size-3" />
      complete
    </Badge>
  ) : (
    <Badge variant="inconclusive" className={className} data-diagnosis="partial">
      <CircleDashedIcon aria-hidden className="size-3" />
      partial
    </Badge>
  );
}
