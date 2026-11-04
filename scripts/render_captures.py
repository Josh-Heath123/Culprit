"""Regenerate the README's terminal captures from real runs.

Every image under docs/captures/ is the output of a command this script
actually runs — Phase 31.2's rule is that nothing in the README is drawn
by hand. Run it with `just readme-captures` (needs Go, uv and Node, the
same as `just cli-test`; and `npm ci` in extractors/node once).

Three captures:

  check.svg  `culprit check` on cli/testdata/demo, the repository in this
             tree with faults planted in it.
  diff.svg   `culprit env capture` twice and `culprit diff` of the two
             envelopes, on a small synthetic project written to a
             temporary directory: one environment is missing a key the
             code reads.
  probe.svg  `culprit probe` against a throwaway HTTP server this script
             starts on 127.0.0.1, which serves one of the two routes the
             synthetic project's openapi.json declares.

Every value in them is synthetic (DIAGNOSTIC_PLAN.md Phase 31.2 field 12):
no real hostname, token, key or DSN. Standard library only.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
# culprit_model's subject builder is standard library only, so it is
# imported from the source tree rather than making this script a project.
sys.path.insert(0, str(ROOT / "shared"))
from culprit_model import subjects  # noqa: E402

OUT = ROOT / "docs" / "captures"

#: Longest line drawn; anything longer ends in "…", as the CLI's own
#: value columns do. Keeps an extractor's long skip reason from making
#: the image a page wide.
MAX_LINE = 132

#: Lines kept from a "Not checked" section before eliding the rest — the
#: full list is in the command's own output; the image shows its shape.
NOT_CHECKED_SHOWN = 4

FONT_SIZE = 13
LINE_HEIGHT = 18
CHAR_WIDTH = 7.85  # ~0.6em, the advance width of common monospace faces
PAD = 16
BG = "#0d1117"
FG = "#c9d1d9"
DIM = "#8b949e"
PROMPT = "#58a6ff"
FAIL = "#f85149"
WARN = "#d29922"
PASS = "#3fb950"


def elide(lines: list[str], header_prefix: str, keep: int) -> list[str]:
    """Keep the first `keep` entries under the section whose header starts
    with `header_prefix`, and replace the rest with a single `…` line."""
    out: list[str] = []
    in_section = False
    kept = 0
    elided = False
    for line in lines:
        if line.startswith(header_prefix):
            in_section, kept, elided = True, 0, False
            out.append(line)
            continue
        if in_section and line.startswith("  "):
            if kept < keep:
                out.append(line)
                kept += 1
            elif not elided:
                out.append("  …")
                elided = True
            continue
        in_section = False
        out.append(line)
    return out


def colour_for(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("$ "):
        return PROMPT
    if "[breaks_request_path]" in line or stripped.startswith("FAILING"):
        return FAIL
    if "[degrades]" in line or stripped.startswith(("INCONCLUSIVE", "REFUSED")):
        return WARN
    if stripped.startswith("PASSING") or stripped.startswith("No divergences"):
        return PASS
    if stripped.startswith(("Not checked", "Refused")):
        return DIM
    return FG


def clip(line: str) -> str:
    # Never a command line: a clipped command would show a different one.
    if len(line) <= MAX_LINE or line.startswith("$ "):
        return line
    return line[: MAX_LINE - 1] + "…"


def render_svg(lines: list[str]) -> str:
    """A terminal-looking SVG: one <text> per line, whitespace preserved."""
    lines = [clip(line) for line in lines]
    width = int(PAD * 2 + CHAR_WIDTH * max((len(line) for line in lines), default=1))
    height = PAD * 2 + LINE_HEIGHT * len(lines)
    body = []
    for i, line in enumerate(lines):
        y = PAD + LINE_HEIGHT * (i + 1) - 5
        body.append(
            f'<text x="{PAD}" y="{y}" fill="{colour_for(line)}" xml:space="preserve">'
            f"{escape(line)}</text>"
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">\n'
        f'<rect width="100%" height="100%" rx="8" fill="{BG}"/>\n'
        f'<g font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" '
        f'font-size="{FONT_SIZE}">\n' + "\n".join(body) + "\n</g>\n</svg>\n"
    )


def run(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> list[str]:
    """Run a command and return its combined output as lines. A non-zero
    exit is expected — `check` and `diff` exit 1 on findings."""
    result = subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if result.returncode not in (0, 1):
        sys.exit(f"{' '.join(argv)} exited {result.returncode}:\n{result.stdout}{result.stderr}")
    lines = (result.stdout + result.stderr).rstrip("\n").splitlines()
    crashed = [line for line in lines if CRASHED_EXTRACTOR.search(line)]
    if crashed:
        # An extractor that crashed turns findings into "not checked" gaps,
        # and the run still exits 0 or 1 — so without this the README's
        # evidence would be overwritten by a degraded run, silently.
        sys.exit(
            "an extractor crashed, so this is not a capture to publish:\n" + "\n".join(crashed)
        )
    return lines


#: How `culprit` reports an extractor plugin that failed to run, as opposed
#: to one that ran and could not answer (which is an honest gap).
CRASHED_EXTRACTOR = re.compile(r'extractor "[^"]+" exited \d+')


def build_cli(into: Path) -> Path:
    binary = into / ("culprit.exe" if os.name == "nt" else "culprit")
    subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/culprit"],
        cwd=ROOT / "cli",
        env={**os.environ, "CGO_ENABLED": "0"},
        check=True,
    )
    return binary


def base_env() -> dict[str, str]:
    """Only what the tools need to start (uv's cache, Go's, the Windows
    basics). `env capture` with the `process` adapter reads the
    environment it runs in, so this is kept small and synthetic."""
    keep = ("PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP")
    return {k: os.environ[k] for k in keep if k in os.environ}


TOY_MANIFEST = """\
version: 1
components:
  - name: web
    kind: frontend
    connections:
      - to: api
        kind: http
        criticality: on_request_path
  - name: api
    kind: service

extract:
  extractors:
    - name: python
      command: ["uv", "run", "--project", "{extractor}", "culprit-extract-python"]
  components:
    api: {{ root: api, extractors: [python] }}

environments:
  staging:
    adapter: process
    components: {{ api: {{}} }}
    grants: {{ config.read.names: true }}
  production:
    adapter: process
    components: {{ api: {{}} }}
    grants: {{ config.read.names: true }}
  local:
    adapter: process
    components: {{ api: {{}} }}
    grants: {{ net.http.outbound: true, net.tcp.connect: true, net.dns.resolve: true }}
"""

TOY_CONFIG = """\
import os

DATABASE_URL = os.environ["DATABASE_URL"]
PAYMENTS_API_KEY = os.environ["PAYMENTS_API_KEY"]
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info")
"""

TOY_ENV_EXAMPLE = "DATABASE_URL=\nPAYMENTS_API_KEY=\nLOG_LEVEL=info\n"

TOY_OPENAPI = """\
{"openapi": "3.0.3", "info": {"title": "api", "version": "1"},
 "paths": {"/health": {"get": {"responses": {"200": {"description": "ok"}}}},
           "/orders": {"get": {"responses": {"200": {"description": "ok"}}}}}}
"""


def write_toy_project(at: Path) -> None:
    (at / "api").mkdir(parents=True)
    extractor = (ROOT / "extractors" / "python").as_posix()
    (at / "culprit.yaml").write_text(TOY_MANIFEST.format(extractor=extractor), encoding="utf-8")
    (at / "api" / "config.py").write_text(TOY_CONFIG, encoding="utf-8")
    (at / "api" / ".env.example").write_text(TOY_ENV_EXAMPLE, encoding="utf-8")
    (at / "api" / "openapi.json").write_text(TOY_OPENAPI, encoding="utf-8")


def capture_check(culprit: Path) -> list[str]:
    cmd = ["check", "-f", "testdata/demo/culprit.yaml"]
    out = run([str(culprit), *cmd], cwd=ROOT / "cli")
    return [f"$ culprit {' '.join(cmd)}", *elide(out, "Not checked", NOT_CHECKED_SHOWN)]


def capture_diff(culprit: Path, toy: Path) -> list[str]:
    # Synthetic values only; `env capture` records their shape, not them.
    shared = {"DATABASE_URL": "postgresql://app:example@db.example.internal:5432/app"}
    staging = {**base_env(), **shared, "PAYMENTS_API_KEY": "example-key", "LOG_LEVEL": "debug"}
    production = {**base_env(), **shared, "LOG_LEVEL": "info"}
    run([str(culprit), "env", "capture", "staging", "-o", "staging.capture"], toy, staging)
    run([str(culprit), "env", "capture", "production", "-o", "production.capture"], toy, production)
    out = run([str(culprit), "diff", "staging.capture", "production.capture"], toy, base_env())
    return [
        "$ culprit env capture staging -o staging.capture",
        "$ culprit env capture production -o production.capture",
        "$ culprit diff staging.capture production.capture",
        *elide(out, "Not checked", NOT_CHECKED_SHOWN),
    ]


def _first_reading(doc: object) -> dict:
    if isinstance(doc, dict) and "readings" in doc:
        doc = doc["readings"]
    if isinstance(doc, list) and doc and isinstance(doc[0], dict):
        return doc[0]
    if isinstance(doc, dict):
        return doc
    sys.exit(f"unexpected probe JSON shape: {type(doc).__name__}")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def capture_probe(culprit: Path, toy: Path) -> list[str]:
    www = toy / "www"
    www.mkdir()
    (www / "health").write_text("ok\n", encoding="utf-8")
    handler = functools.partial(_Quiet, directory=str(www))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        lines: list[str] = []
        # Targets built with the one sanctioned subject builder, never
        # formatted by hand (scripts/tests/test_subject_construction.py).
        health = subjects.build("http", component="api", method="GET", path="/health")
        orders = subjects.build("http", component="api", method="GET", path="/orders")
        flags = [
            "--env",
            "local",
            "-p",
            "probe.http.route_conformance",
            "--input",
            f"base_url={base}",
        ]
        for target in (health, orders):
            out = run([str(culprit), "probe", target, *flags], toy, base_env())
            lines += [
                f"$ culprit probe '{target}' {' '.join(flags)}",
                *[line for line in out if line.strip()],
                "",
            ]

        # The text format does not print where an expectation came from;
        # the JSON reading does. Shown as a labelled excerpt of that real
        # reading, not as output the command prints verbatim.
        flags += ["--format", "json"]
        raw = run([str(culprit), "probe", health, *flags], toy, base_env())
        reading = _first_reading(json.loads("\n".join(raw)))
        excerpt = {k: reading.get(k) for k in ("verdict", "expected", "expected_source")}
        lines += [
            f"$ culprit probe '{health}' {' '.join(flags)}   # excerpt of the reading",
            *json.dumps(excerpt, indent=2).splitlines(),
        ]
        return lines
    finally:
        server.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--print", action="store_true", help="print the captured text too")
    args = parser.parse_args()

    for tool in ("go", "uv", "node"):
        if shutil.which(tool) is None:
            sys.exit(f"{tool} is not on PATH; `just readme-captures` needs Go, uv and Node")

    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="culprit-captures-") as tmp:
        tmp_path = Path(tmp)
        culprit = build_cli(tmp_path)
        toy = tmp_path / "toy"
        write_toy_project(toy)
        captures = {
            "check": capture_check(culprit),
            "diff": capture_diff(culprit, toy),
            "probe": capture_probe(culprit, toy),
        }
    for name, lines in captures.items():
        (OUT / f"{name}.svg").write_text(render_svg(lines), encoding="utf-8", newline="\n")
        print(f"wrote docs/captures/{name}.svg ({len(lines)} lines)")
        if args.print:
            print("\n".join(lines), end="\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
