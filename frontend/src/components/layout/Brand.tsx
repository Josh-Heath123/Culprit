/** The mark: a measuring ring with its four ticks, and the culprit at its
 * centre in lime — what a walk finds (DELIVERY_PLAN I2; the same drawing
 * as public/favicon.svg and docs/brand/mark.svg). */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden focusable="false" className={className}>
      <circle cx="16" cy="16" r="9" className="fill-none stroke-fg" strokeWidth="2" />
      <path d="M16 2.5v5M16 24.5v5M2.5 16h5M24.5 16h5" className="fill-none stroke-fg-subtle" strokeWidth="2" strokeLinecap="round" />
      <circle cx="16" cy="16" r="4" className="fill-culprit" />
    </svg>
  );
}

/** The brand: the mark and the name. One component, so every page that
 * shows it shows the same thing. */
export function Brand({ size = "default" }: { size?: "default" | "large" }) {
  return (
    <span className="flex items-center gap-2">
      <Mark className={size === "large" ? "size-7" : "size-5"} />
      <span className={size === "large" ? "text-xl font-bold tracking-tight text-fg" : "text-sm font-bold tracking-tight text-fg"}>
        Culprit
      </span>
    </span>
  );
}
