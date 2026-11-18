import { AppHeader } from "@/components/layout/AppHeader";
import { Brand } from "@/components/layout/Brand";
import { Graticule } from "@/components/layout/Graticule";
import { SourceLink } from "@/components/layout/SourceLink";
import { Label } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Every signed-in page: the shared header, then one main column, with a
 * page title and an optional description and actions. Pages put their
 * content inside; none draws its own header or chooses its own width.
 * On a list the title is the screen's editorial moment (I3), in Inter 700
 * at the title step. The one exception is the investigation view, whose
 * heading is its answer (components/investigation/Diagnosis.tsx); it uses
 * AppHeader and the same column width directly. */
export function Page({
  title,
  description,
  actions,
  eyebrow,
  children,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** A small label above the title, e.g. "History" or "Settings". */
  eyebrow?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader />
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6 sm:py-10">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex min-w-0 flex-col gap-2">
            {eyebrow ? <Label>{eyebrow}</Label> : null}
            <h1 className="text-title font-bold text-fg sm:text-display">{title}</h1>
            {description ? (
              <div className="max-w-2xl text-sm leading-relaxed text-fg-muted">{description}</div>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
        {children}
      </main>
      <SourceLink />
    </div>
  );
}

/** A page with no session behind it — sign-in, not found, admins only:
 * the brand, then one centred panel, over the graticule (I4). `glow` adds
 * the violet radial glow, which belongs to the sign-in page alone. */
export function Standalone({ children, glow = false }: { children: React.ReactNode; glow?: boolean }) {
  return (
    <div className="relative isolate flex min-h-screen flex-col overflow-hidden">
      <Graticule className="-z-10" />
      {glow ? (
        <div
          aria-hidden
          className={cn("glow-violet pointer-events-none absolute top-1/2 left-1/2 -z-10 size-full max-w-3xl -translate-x-1/2 -translate-y-1/2")}
          data-testid="glow"
        />
      ) : null}
      <main className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-10">
        <Brand size="large" />
        {children}
      </main>
      <SourceLink />
    </div>
  );
}
