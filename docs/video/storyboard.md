# Demonstration video — storyboard

One row per scene. **CLI** scenes are real terminal sessions recorded live
(not typed into an editor and pasted). **UI** scenes are taken from the
running quickstart stack, in a browser at 1280×800. Times match
[`script.md`](script.md). Data is synthetic throughout: the demo services,
the quickstart's injected fault, the fault library's recorded walks.

| # | Time | Kind | On screen | Action | Narration |
|---|---|---|---|---|---|
| 1 | 0:00–0:15 | Title | "Culprit — finds the places where your system disagrees with itself" on the midnight background, the cantaloupe dot | Fade in | Part 1, first paragraph |
| 2 | 0:15–0:45 | Diagram | The README's three-planes diagram (docs/diagrams or the Mermaid render) | Slow zoom to the "disagree" arrows | Part 1, rest |
| 3 | 0:45–1:05 | CLI | `cd cli && culprit check -f testdata/demo/culprit.yaml` | Run it; let the five findings print | `culprit check`, para 1 |
| 4 | 1:05–1:25 | CLI | Same output, scrolled to one `breaks_request_path` finding, then the "Not checked" list | Highlight the two sources and the severity reason | `culprit check`, para 2–3 |
| 5 | 1:25–1:55 | CLI | `culprit env capture` of staging and production, then `culprit diff` (the commands in README "Usage") | Run both; point at PAYMENTS_API_KEY | env capture and diff |
| 6 | 1:55–2:10 | CLI | The tail of `just quickstart`: "The injected fault has been diagnosed…" and the investigation URL | Show the last lines, not the build | `diagnose`, para 1 |
| 7 | 2:10–2:30 | CLI | `culprit diagnose` text output (from `cli/bin/quickstart-investigation.json`'s run, or rerun inside order-service) | Scroll from "Diagnosis (COMPLETE)" to the fault tree | `diagnose`, para 2 |
| 8 | 2:30–2:50 | UI | Investigations list → the complete investigation | Click the row; the ROOT label and the tree | `diagnose`, para 3 |
| 9 | 2:50–3:00 | UI | Expand the "caused by" edge | The fail reading: audience [inventory], expected inventory-service | `diagnose`, para 3 |
| 10 | 3:00–3:05 | UI | The confidence rubric | Hover the two "no" reasons | `diagnose`, para 4 |
| 11 | 3:05–3:15 | UI | Back → the partial investigation | "Walk stopped at", "Could not check" naming config.read.values | `diagnose`, para 5 |
| 12 | 3:15–3:45 | Diagram | README "How it works" flowcharts | Pan left to right | Part 3, para 1–2 |
| 13 | 3:45–4:15 | Code | `cli/internal/probe/` runner asking the ledger; `cli/cmd/culprit/check_test.go`'s network allowlist test | Two quick cuts, code at a readable size | Part 3, para 3–4 |
| 14 | 4:15–4:45 | Code + UI | `api/migrations/versions/c4e8a1f2b3d5_investigations.py` (the trigger), then the CI run page with the e2e job green | Two cuts | Part 3, para 5 |
| 15 | 4:45–5:15 | CLI | A fresh clone: `git clone …`, `just quickstart` (cut the build), the printed URL and login | Run, cut, show the end | Part 4, para 1 |
| 16 | 5:15–5:35 | CLI | `just cli-build`, `culprit check` on the demo | Run | Part 4, para 2 |
| 17 | 5:35–6:00 | Title | The dashboard's investigation view at 1280 px, then the title card | Fade out | Part 5 |
