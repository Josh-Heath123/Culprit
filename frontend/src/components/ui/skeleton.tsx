import { cn } from "@/lib/utils";

/** A loading placeholder. Pulses unless the reader asked for reduced
 * motion (index.css). Hidden from assistive technology: the region it sits
 * in carries aria-busy and a text label instead. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden
      className={cn("animate-pulse rounded-md bg-surface-2", className)}
      {...props}
    />
  );
}

export { Skeleton };
