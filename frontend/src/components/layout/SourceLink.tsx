/** Where this build's source is (Phase 33 part 3). Culprit is AGPL-3.0, and
 * section 13 asks anyone who runs a modified copy as a network service to
 * offer its users that copy's source. Every page links to it, so honouring
 * that is setting one build argument: VITE_SOURCE_URL (frontend/Dockerfile),
 * which defaults to this repository. LICENSING.md says the rest. */
export const SOURCE_URL: string = import.meta.env.VITE_SOURCE_URL || "https://github.com/Josh-Heath123/Culprit";

export function SourceLink() {
  return (
    <footer className="px-4 py-4 text-center text-2xs text-fg-subtle sm:px-6" data-testid="source-link">
      Culprit is free software under the GNU AGPL-3.0.{" "}
      <a href={SOURCE_URL} className="text-fg-muted underline underline-offset-2 hover:text-fg" rel="noreferrer">
        Source code
      </a>
    </footer>
  );
}
