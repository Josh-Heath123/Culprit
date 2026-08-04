# demo-services

Three tiny FastAPI services with a real call chain — `order-service` calls
`inventory-service` then `payments-service` to fulfill an order — plus a
load generator and a fault injector. This is a data source for
SignalStack, not a product: no persistence, no real business logic.

Exists to produce telemetry SignalStack can later ingest and correlate
(Phase 3+). Not wired to the Phase 0 Tempo instance — that's reserved for
SignalStack's own self-observability (Phase 10). By default these export
traces/metrics to the console; set `OTEL_EXPORTER_OTLP_ENDPOINT` to switch
to OTLP/HTTP once Phase 3's ingest-gateway exists to receive it.

## Ports

| Service            | Port |
|--------------------|------|
| order-service      | 8001 |
| inventory-service  | 8002 |
| payments-service   | 8003 |

## Run

```bash
just demo-inventory   # terminal 1
just demo-payments    # terminal 2
just demo-order       # terminal 3
just demo-load        # terminal 4 — steady baseline traffic
```

## Inject a fault

```bash
cd demo-services
uv run python fault_cli.py latency inventory-service --delay-ms 800 --duration-s 30
uv run python fault_cli.py errors payments-service --rate 0.5 --duration-s 30
uv run python fault_cli.py status inventory-service
uv run python fault_cli.py clear inventory-service
```
