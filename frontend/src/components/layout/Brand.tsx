/** The brand mark: the cantaloupe dot and the name. One component, so
 * every page that shows it shows the same thing. */
export function Brand() {
  return (
    <span className="flex items-center gap-2">
      <span className="size-2.5 rounded-full bg-highlight" aria-hidden />
      <span className="text-sm font-semibold tracking-tight text-fg">Culprit</span>
    </span>
  );
}
