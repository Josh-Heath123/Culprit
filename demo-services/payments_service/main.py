import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from shared.faults import FaultState, build_fault_router
from shared.middleware import TelemetryFaultMiddleware
from shared.otel import configure_otel

SERVICE_NAME = "payments-service"
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


class ChargeRequest(BaseModel):
    order_id: str
    amount: float


# Required config — Phase 32's config fault is this key unset.
PROVIDER_KEY_VARIABLE = "PAYMENTS_PROVIDER_KEY"


def _provider_key_missing() -> bool:
    return not os.environ.get(PROVIDER_KEY_VARIABLE)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    """Readiness through the fault middleware, and honest about config: a
    payments service with no provider key cannot charge anyone."""
    if _provider_key_missing():
        raise HTTPException(status_code=503, detail=f"{PROVIDER_KEY_VARIABLE} is not set")
    return {"status": "ready"}


@app.post("/charge", status_code=201)
def charge(req: ChargeRequest) -> dict:
    if _provider_key_missing():
        raise HTTPException(status_code=500, detail="payments provider is not configured")
    logger.info("charged %.2f for order %s", req.amount, req.order_id)
    return {"charged": True, "order_id": req.order_id, "amount": req.amount}
