# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""The largest request bodies the api received, from its access log (F44-043).

Reads `docker compose logs api` (or any text holding the api's JSON access
lines) on stdin, and prints the largest bodies by method and route, ids
folded, with the largest of all. Every request's declared size is in its
`http_request` line as `request_bytes` (app/main.py). With `--cap BYTES`,
exits 1 unless the largest body, times four, is within the cap: the margin
the cap on /api/* was set with (docs/FIELD_READINESS_PLAN.md §6, batch 3).
"""

import argparse
import json
import re
import sys
from collections.abc import Iterable

#: An id in a path, folded so one route is one row.
_ID = re.compile(r"/(?:[0-9a-f]{8,}|[a-z]+-[0-9a-f]{6,}|[0-9]+)(?=/|$)")

MARGIN = 4


def sizes(lines: Iterable[str]) -> dict[str, int]:
    """The largest declared body per "METHOD /route", from access lines."""
    largest: dict[str, int] = {}
    for line in lines:
        start = line.find("{")
        if start < 0:
            continue
        try:
            entry = json.loads(line[start:])
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("event") != "http_request":
            continue
        size = entry.get("request_bytes")
        if not isinstance(size, int):
            continue
        route = f"{entry.get('method', '?')} {_ID.sub('/{id}', str(entry.get('path', '?')))}"
        largest[route] = max(largest.get(route, 0), size)
    return largest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap", type=int, help="fail unless the largest body x4 is within this")
    args = parser.parse_args(argv)
    largest = sizes(sys.stdin)
    if not largest:
        print("request_sizes: no access line with request_bytes was read", file=sys.stderr)
        return 1
    ranked = sorted(largest.items(), key=lambda item: (-item[1], item[0]))
    for route, size in ranked[:15]:
        print(f"{size:>10}  {route}")
    top_route, top = ranked[0]
    print(f"largest: {top} bytes ({top_route}); x{MARGIN} = {top * MARGIN}")
    if args.cap is not None and top * MARGIN > args.cap:
        print(
            f"request_sizes: {top} bytes x{MARGIN} is over the cap of {args.cap}: "
            "the cap no longer has its margin",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
