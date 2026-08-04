"""Trigger fault injection against a demo service's admin endpoint.

    uv run python fault_cli.py latency inventory-service --delay-ms 800 --duration-s 30
    uv run python fault_cli.py errors payments-service --rate 0.5 --duration-s 30
    uv run python fault_cli.py status inventory-service
    uv run python fault_cli.py clear inventory-service
"""

import argparse
import sys

import httpx

SERVICE_URLS = {
    "order-service": "http://localhost:8001",
    "inventory-service": "http://localhost:8002",
    "payments-service": "http://localhost:8003",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    latency = sub.add_parser("latency", help="Inject a latency spike")
    latency.add_argument("service", choices=SERVICE_URLS)
    latency.add_argument("--delay-ms", type=float, default=1000)
    latency.add_argument("--duration-s", type=float, default=30)

    errors = sub.add_parser("errors", help="Inject an elevated error rate")
    errors.add_argument("service", choices=SERVICE_URLS)
    errors.add_argument("--rate", type=float, default=0.5)
    errors.add_argument("--duration-s", type=float, default=30)

    clear = sub.add_parser("clear", help="Clear active faults immediately")
    clear.add_argument("service", choices=SERVICE_URLS)

    status = sub.add_parser("status", help="Show currently active faults")
    status.add_argument("service", choices=SERVICE_URLS)

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    base_url = SERVICE_URLS[args.service]

    if args.command == "latency":
        resp = httpx.post(
            f"{base_url}/admin/fault/latency",
            json={"delay_ms": args.delay_ms, "duration_s": args.duration_s},
        )
    elif args.command == "errors":
        resp = httpx.post(
            f"{base_url}/admin/fault/error-rate",
            json={"rate": args.rate, "duration_s": args.duration_s},
        )
    elif args.command == "clear":
        resp = httpx.delete(f"{base_url}/admin/fault")
    else:
        resp = httpx.get(f"{base_url}/admin/fault")

    resp.raise_for_status()
    print(resp.json())


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
