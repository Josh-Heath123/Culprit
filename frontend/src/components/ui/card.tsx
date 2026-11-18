import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** A surface, always solid (I5). `solid` is for data — the fault tree,
 * readings, lists, forms, settings — where reading wins; `raised` lifts a
 * panel one step. Glass is not a card: it belongs to layered elements
 * (navigation, dialogs, tooltips), which scripts/check_frontend_tokens.py
 * holds to the components declared for it. */
const cardVariants = cva("rounded-lg border", {
  variants: {
    surface: {
      solid: "border-line bg-surface-1",
      raised: "border-line bg-surface-2 shadow-raised",
    },
  },
  defaultVariants: { surface: "solid" },
});

function Card({
  className,
  surface,
  ...props
}: React.ComponentProps<"section"> & VariantProps<typeof cardVariants>) {
  return <section data-slot="card" className={cn(cardVariants({ surface }), className)} {...props} />;
}

/** A card's title row: a small mono label, upper-case and letter-spaced
 * (I3), and an optional trailing slot (a count, a badge). A real heading,
 * so the page outline can be navigated by assistive technology. */
function CardHeader({
  title,
  trailing,
  id,
  className,
}: {
  title: React.ReactNode;
  trailing?: React.ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5", className)}>
      <h2 id={id} className="font-mono text-2xs font-medium tracking-label text-fg-subtle uppercase">
        {title}
      </h2>
      {trailing}
    </div>
  );
}

function CardBody({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-4 py-4 sm:px-5", className)} {...props} />;
}

/** The mono label I3 gives every section, field group and piece of
 * metadata: upper-case, letter-spaced, small. One component, so a label
 * looks the same wherever it is. */
function Label({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("font-mono text-2xs font-medium tracking-label text-fg-subtle uppercase", className)}
      {...props}
    />
  );
}

export { Card, CardBody, CardHeader, Label };
