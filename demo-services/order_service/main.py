import logging
import os
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanKind
from pydantic import BaseModel
from shared.faults import FaultState, build_fault_router
from shared.middleware import TelemetryFaultMiddleware
from shared.otel import configure_otel

SERVICE_NAME = "order-service"
configure_otel(SERVICE_NAME)
tracer = trace.get_tracer(SERVICE_NAME)
logger = logging.getLogger(SERVICE_NAME)

# Logical peer identities for the CLIENT spans below (Phase 19: topology
# inference reads these off `peer.service`) -- fixed, not derived from
# INVENTORY_URL/PAYMENTS_URL, because the URL is where a call goes today
# and the service identity is what a call is *to*; these three demo
# services are hardcoded everywhere else in this repo too (CLAUDE.md).
INVENTORY_SERVICE_NAME = "inventory-service"
PAYMENTS_SERVICE_NAME = "payments-service"

INVENTORY_URL = os.environ.get("INVENTORY_SERVICE_URL", "http://localhost:8002")
PAYMENTS_URL = os.environ.get("PAYMENTS_SERVICE_URL", "http://localhost:8003")
# Deliberately shorter than a plausible injected latency spike, so a slow
# downstream call becomes a timeout -> 502 here, not just added latency.
DOWNSTREAM_TIMEOUT_S = float(os.environ.get("DOWNSTREAM_TIMEOUT_S", "3"))

fault_state = FaultState()
app = FastAPI(title=SERVICE_NAME)
app.add_middleware(
    TelemetryFaultMiddleware,  # pyright: ignore[reportArgumentType]
    service_name=SERVICE_NAME,
    fault_state=fault_state,
)
app.include_router(build_fault_router(fault_state), prefix="/admin/fault")


class CreateOrderRequest(BaseModel):
    sku: str
    qty: int
    amount: float


def _propagated_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    inject(headers)
    return headers


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/orders", status_code=201)
async def create_order(req: CreateOrderRequest) -> dict:
    order_id = str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=DOWNSTREAM_TIMEOUT_S) as client:
        # CLIENT-kind span per downstream call, `peer.service` set to the
        # logical name being called (Phase 19: this is the signal
        # api/app/ingest_gateway/otlp_decode.py's decode_traces_request
        # reads to infer order-service -> inventory-service/payments-service
        # edges). `inject()` runs *inside* the span so the downstream
        # service's own span nests under this CLIENT span specifically,
        # not under whatever span was active before it.
        with tracer.start_as_current_span(
            "POST /reserve",
            kind=SpanKind.CLIENT,
            attributes={"peer.service": INVENTORY_SERVICE_NAME},
        ):
            try:
                reserve_resp = await client.post(
                    f"{INVENTORY_URL}/reserve",
                    json={"order_id": order_id, "sku": req.sku, "qty": req.qty},
                    headers=_propagated_headers(),
                )
                reserve_resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("order %s failed: inventory-service unavailable: %s", order_id, exc)
                raise HTTPException(
                    status_code=502, detail=f"inventory-service unavailable: {exc}"
                ) from exc

        with tracer.start_as_current_span(
            "POST /charge",
            kind=SpanKind.CLIENT,
            attributes={"peer.service": PAYMENTS_SERVICE_NAME},
        ):
            try:
                charge_resp = await client.post(
                    f"{PAYMENTS_URL}/charge",
                    json={"order_id": order_id, "amount": req.amount},
                    headers=_propagated_headers(),
                )
                charge_resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("order %s failed: payments-service unavailable: %s", order_id, exc)
                raise HTTPException(
                    status_code=502, detail=f"payments-service unavailable: {exc}"
                ) from exc

    logger.info("order %s fulfilled: %d x %s for %.2f", order_id, req.qty, req.sku, req.amount)
    return {
        "order_id": order_id,
        "sku": req.sku,
        "qty": req.qty,
        "amount": req.amount,
        "status": "fulfilled",
    }
