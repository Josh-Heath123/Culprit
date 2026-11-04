import { AppHeader } from "@/components/layout/AppHeader";
import { Brand } from "@/components/layout/Brand";

/** Every signed-in page: the shared header, then one main column, with a
 * page title and an optional description and actions. Pages put their
 * content inside; none draws its own header or chooses its own width.
 * The one exception is the investigation view, whose title is the symptom
 * in monospace with a back link above it; it uses AppHeader and the same
 * column width directly. */
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
      <main
        className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8"
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex min-w-0 flex-col gap-1.5">
            {eyebrow ? (
              <span className="text-2xs font-semibold tracking-widest text-fg-subtle uppercase">{eyebrow}</span>
            ) : null}
            <h1 className="text-xl font-semibold tracking-tight text-fg sm:text-2xl">{title}</h1>
            {description ? (
              <div className="max-w-2xl text-sm leading-relaxed text-fg-muted">{description}</div>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
        {children}
      </main>
    </div>
  );
}

/** A page with no session behind it — sign-in, not found, admins only:
 * the brand, then one centred panel. */
export function Standalone({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 px-4 py-10">
      <Brand />
      {children}
    </main>
  );
}
