import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** A small label. The status variants (pass, fail, ...) exist for the
 * badges in status.tsx, which always add an icon and the word — use those
 * for a verdict or a severity, never a bare coloured Badge. */
const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-2xs font-medium leading-none whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "border-line bg-surface-2 text-fg-muted",
        outline: "border-line-strong text-fg-muted",
        primary: "border-brand-line bg-brand-tint text-brand",
        highlight: "border-highlight-line bg-highlight-tint text-highlight",
        pass: "border-pass-line bg-pass-tint text-pass",
        fail: "border-fail-line bg-fail-tint text-fail",
        inconclusive: "border-inconclusive-line bg-inconclusive-tint text-inconclusive",
        refused: "border-refused-line bg-refused-tint text-refused",
        breaks: "border-breaks-line bg-breaks-tint text-breaks",
        degrades: "border-degrades-line bg-degrades-tint text-degrades",
        cosmetic: "border-cosmetic-line bg-cosmetic-tint text-cosmetic",
        unknown: "border-unknown-line bg-unknown-tint text-unknown",
        // Kept for the routes part 2 has not redesigned yet.
        warning: "border-degrades-line bg-degrades-tint text-degrades",
        destructive: "border-fail-line bg-fail-tint text-fail",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
