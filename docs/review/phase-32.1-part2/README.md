# Phase 32.1 part 2 — every route at four widths

Taken by the end-to-end suite (`frontend/e2e/tour.spec.ts`, `just e2e`)
against a `just quickstart` stack built from this branch's tree: 14 screens
at 375, 768, 1280 and 1920 px. The same run checks each one for horizontal
overflow, keyboard focus reaching the page (or the open dialog) with a
visible outline, and any console error or failed request. Synthetic data
only: the quickstart's injected fault, the fault library's recorded walks,
and the user and postmortem the suite itself creates.

| Screen | Files |
|---|---|
| Investigations list | `investigations-*.png` |
| A complete investigation, one edge open | `investigation-complete-*.png` |
| A partial investigation | `investigation-partial-*.png` |
| Incidents (history; none recorded on a fresh install) | `incidents-*.png` |
| Command palette | `command-palette-*.png` |
| Postmortems list, new, existing | `postmortems-*.png`, `postmortem-editor-*.png`, `postmortem-existing-*.png` |
| Settings → Services | `settings-services-*.png` |
| Settings → Users | `settings-users-*.png` |
| Change password | `change-password-*.png` |
| Not found | `not-found-*.png` |
| Sign in | `sign-in-*.png` |
| A member opening an admin page | `admins-only-*.png` |

Not covered: an incident's detail panel and the postmortem editor opened from
an incident. Nothing creates incidents any more (Phase 32 part 2), so no
stack the suite runs against has one to open.
