import logging
import os
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry.propagate import inject
from pydantic import BaseModel
from shared.faults import FaultState, build_fault_router
from shared.middleware import TelemetryFaultMiddleware
from shared.otel import configure_otel

SERVICE_NAME = "order-service"
configure_otel(SERVICE_NAME)
logger = logging.getLogger(SERVICE_NAME)

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
