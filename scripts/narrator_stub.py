"""A stub narration provider for tests and CI — Phase 35 part 2.

It speaks the one Ollama route the narrator uses (`POST /api/chat`), so CI
runs the real `ollama` provider code with no key and no model. It is not a
model: its replies are scripted, chosen by a marker in the evidence it is
sent (an investigation's symptom description):

- `narrator-stub:fail`      HTTP 500, with a secret-looking string and a
                            connection string in the body, which must leave
                            no trace in what Culprit stores, logs or shows;
- `narrator-stub:refuse`    prose naming a component the investigation does
                            not hold, and a markdown image with a URL —
                            stored as refused;
- `narrator-stub:markup`    markdown and HTML with no URL, which passes the
                            check and must be shown literally;
- anything else             a faithful narration that cites the evidence.

`GET /calls` answers how many calls it has had, in all and per marker, so
a test can count them: none with LLM_PROVIDER=none, and never a fourth for
an investigation that has had three. Standard library only.

    python scripts/narrator_stub.py [--port 11434]
"""

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MARKERS = ("narrator-stub:fail", "narrator-stub:refuse", "narrator-stub:markup")

#: Shaped like real credentials so the redaction choke point would catch
#: them if they ever reached it; not real.
FAKE_SECRETS = (
    "sk-ant-api03-" + "Q" * 40,
    "postgresql://narrator:hunter2-not-real@db.internal:5432/culprit",
)

_lock = threading.Lock()
_calls: dict[str, int] = {"total": 0}


def _count(marker: str) -> None:
    with _lock:
        _calls["total"] += 1
        _calls[marker] = _calls.get(marker, 0) + 1


def _faithful(evidence: str) -> str:
    numbers = re.findall(r"^\[(\d+)\]", evidence, flags=re.MULTILINE)
    cited = numbers[:3] or ["1"]
    return (
        "This investigation started from the reported symptom "
        + "".join(f"[{n}]" for n in cited[:1])
        + ". The walk's diagnosis and the change it recommends are in the evidence "
        + "".join(f"[{n}]" for n in cited[1:])
        + "."
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, body: object) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/calls":
            with _lock:
                self._send(200, dict(_calls))
            return
        if self.path in ("/", "/healthz"):
            self._send(200, {"ok": True})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("content-length") or 0)
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
            evidence = request["messages"][-1]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            self._send(400, {"error": "not a chat request"})
            return
        if request.get("tools"):
            # The narrator never offers tools; a request that does is wrong.
            self._send(400, {"error": "the narrator offers no tools"})
            return
        marker = next((m for m in MARKERS if m in evidence), "faithful")
        _count(marker)
        if marker == "narrator-stub:fail":
            self._send(500, {"error": "upstream exploded: " + " ".join(FAKE_SECRETS)})
            return
        if marker == "narrator-stub:refuse":
            # A component the investigation does not hold, beside a probe it
            # does, and a markdown image carrying a URL. (The subject rule is
            # held by shared/tests/narration_conformance.json and the API's
            # tests; a subject here would be a hand-formatted one.)
            content = (
                "The billing-service is the cause, as probe.http.reachable shows [1]. "
                "![x](https://evil.example/p.png)"
            )
        elif marker == "narrator-stub:markup":
            content = "**Root cause:** <b>see the diagnosis</b> <script>alert(1)</script> [2]."
        else:
            content = _faithful(evidence)
        self._send(
            200,
            {
                "model": request.get("model"),
                "message": {"role": "assistant", "content": content},
                "done": True,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=11434)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
