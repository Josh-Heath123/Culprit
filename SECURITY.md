# Security policy

## Reporting a vulnerability

**Report it privately,** through GitHub's private vulnerability reporting:
the repository's **Security** tab, then **Report a vulnerability**
(<https://github.com/Josh-Heath123/Culprit/security/advisories/new>). Please
do not open a public issue, pull request or discussion about it.

If that button is not there, private reporting has not been turned on yet:
open an issue that says only that you have something to report privately,
with no detail, and a private channel will be arranged.

Say what you found, how to reproduce it, which commit or release it is on,
and what you think it lets someone do.

## What is in scope

- **The `culprit` binary's read-only guarantees:** that no probe writes, that
  a database session cannot change data, that the check pipeline opens no
  connection, and that nothing in the binary listens
  ([`docs/PROBES.md`](docs/PROBES.md), [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md)).
- **The agent and its pairing with the control plane:** signed requests,
  grants, the audit log.
- **The control plane:** the API, its authentication and its database roles,
  the worker, and the dashboard.
- **The MCP server** (`mcp_server/`).
- **The extractors** (`extractors/python/`, `extractors/node/`), which run
  inside other people's projects.

[`docs/SECURITY.md`](docs/SECURITY.md) is the threat model: what a
compromised control plane, agent, pairing code, key or token cannot do, each
with the test that holds it. A way around any of those is in scope.

Out of scope: the demo services (`demo-services/`), which are deliberately
faulty test targets; denial of service by volume; and findings in a
dependency that Culprit does not reach (report those upstream).

## What is supported

Only `main` and the latest release. No release has been cut yet, so today
that is `main`. Fixes are not backported.

## What to expect

Culprit has one maintainer. You should hear back within **seven days**,
usually sooner. A fix and an advisory follow as soon as they are ready,
and the report is credited if you wish. There is no bug bounty.
