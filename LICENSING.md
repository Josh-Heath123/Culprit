# Licensing

Copyright (c) 2026 Joshua Heath

Culprit is licensed under the **GNU Affero General Public License, version 3
only** (`AGPL-3.0-only`). The full text is in [`LICENSE`](LICENSE).

Three directories are licensed under the **Apache License, version 2.0**
(`Apache-2.0`) instead. Each one holds the full text in its own `LICENSE`.

| Path | Licence | SPDX | Full text |
|---|---|---|---|
| `extractors/python/` | Apache License 2.0 | `Apache-2.0` | [`extractors/python/LICENSE`](extractors/python/LICENSE) |
| `extractors/node/` | Apache License 2.0 | `Apache-2.0` | [`extractors/node/LICENSE`](extractors/node/LICENSE) |
| `shared/` | Apache License 2.0 | `Apache-2.0` | [`shared/LICENSE`](shared/LICENSE) |
| `cli/testdata/fixtures/third-party/*/` | Each project's own licence | — | The `LICENSE` file in each fixture directory |
| Everything else: `api/`, `worker/`, `mcp_server/`, `demo-services/`, `frontend/`, `cli/`, `infra/`, `scripts/`, `docs/`, `examples/`, `claude-setup/`, `.github/`, `.claude/` and the files at the root | GNU AGPL 3.0 only | `AGPL-3.0-only` | [`LICENSE`](LICENSE) |

## Why the split

The extractors run inside other people's projects, and `shared/` defines the
protocol they speak. The Python extractor depends on `culprit-shared`, so
`shared/` cannot be copyleft without making the extractor copyleft too.
Apache-2.0 lets you run them, embed them, or write your own against the same
contracts without taking on the AGPL.

The engine is AGPL-3.0. If you run a modified Culprit as a network service,
section 13 requires you to offer its users the source of your modified version.

The two third-party fixtures under `cli/testdata/fixtures/third-party/` are
unmodified copies of upstream example projects, used only as test input. They
keep their own licences (BSD-3-Clause and MIT); see
`cli/testdata/fixtures/README.md`.

## Earlier releases

Until this change, the whole repository was released under the MIT License.
Everything published before this commit, up to and including `58e7593` on
`main` (2026-11-10), was released under MIT and remains available under MIT.
The new licences apply only from this commit onward.
