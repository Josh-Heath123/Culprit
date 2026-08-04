import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from shared.faults import FaultState, build_fault_router
from shared.middleware import TelemetryFaultMiddleware
from shared.otel import configure_otel

SERVICE_NAME = "inventory-service"
configure_otel(SERVICE_NAME)
logger = logging.getLogger(SERVICE_NAME)

fault_state = FaultState()
app = FastAPI(title=SERVICE_NAME)
app.add_middleware(
    TelemetryFaultMiddleware,  # pyright: ignore[reportArgumentType]
    service_name=SERVICE_NAME,
    fault_state=fault_state,
)
app.include_router(build_fault_router(fault_state), prefix="/admin/fault")

_DEFAULT_STOCK = 1_000
_stock: dict[str, int] = {}


class ReserveRequest(BaseModel):
    order_id: str
    sku: str
    qty: int


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/reserve", status_code=201)
def reserve(req: ReserveRequest) -> dict:
    available = _stock.setdefault(req.sku, _DEFAULT_STOCK)
    if available < req.qty:
        logger.warning(
            "insufficient stock for %s (requested %d, have %d)", req.sku, req.qty, available
        )
        raise HTTPException(status_code=409, detail="insufficient stock")
    _stock[req.sku] = available - req.qty
    logger.info("reserved %d of %s for order %s", req.qty, req.sku, req.order_id)
    return {"reserved": True, "sku": req.sku, "remaining": _stock[req.sku]}
