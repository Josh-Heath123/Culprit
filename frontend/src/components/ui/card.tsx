import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** A surface. `solid` is for data — the fault tree, readings, lists —
 * where readability wins. `glass` is for a layer that sits over content;
 * never for dense data. */
const cardVariants = cva("rounded-lg border", {
  variants: {
    surface: {
      solid: "border-line bg-surface-1",
      raised: "border-line bg-surface-2 shadow-raised",
      glass: "border-glass-line bg-glass shadow-glass backdrop-blur-glass",
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

/** A card's title row: a small uppercase heading and an optional trailing
 * slot (a count, a badge). A real heading, so the page outline can be
 * navigated by assistive technology. */
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
      <h2 id={id} className="text-2xs font-semibold tracking-widest text-fg-subtle uppercase">
        {title}
      </h2>
      {trailing}
    </div>
  );
}

function CardBody({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-4 py-4 sm:px-5", className)} {...props} />;
}

export { Card, CardBody, CardHeader };
