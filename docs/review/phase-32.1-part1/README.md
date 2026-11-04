# Phase 32.1 part 1 — screenshots for review

The investigation list, a complete investigation and a partial one, at 375,
768, 1280 and 1920 px wide. They were taken by the end-to-end suite
(`frontend/e2e/screenshots.spec.ts`, `just e2e`) against a `just quickstart`
stack built from this branch's tree, so they show only what renders. Each
width was also checked for horizontal overflow.

| Screen | 375 | 768 | 1280 | 1920 |
|---|---|---|---|---|
| Investigation list | [list-375](list-375.png) | [list-768](list-768.png) | [list-1280](list-1280.png) | [list-1920](list-1920.png) |
| Complete investigation, one edge expanded | [complete-375](complete-375.png) | [complete-768](complete-768.png) | [complete-1280](complete-1280.png) | [complete-1920](complete-1920.png) |
| Partial investigation (a refused hypothesis) | [partial-375](partial-375.png) | [partial-768](partial-768.png) | [partial-1280](partial-1280.png) | [partial-1920](partial-1920.png) |

The data is synthetic. The complete investigation is the quickstart's
injected audience fault. The suite posts the three partial ones from
`api/tests/data/investigations/`. Two are fault-library walks. The third,
`partial-with-boundary.json`, comes from the walk in
`cli/internal/isolate`'s `TestABoundaryWithUntestedAlternativesIsWhereTheWalkStopped`. Every other route is unchanged until part 2, apart from the shared
tokens and components it inherits.
