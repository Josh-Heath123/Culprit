import logging

from fastapi import FastAPI
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/charge", status_code=201)
def charge(req: ChargeRequest) -> dict:
    logger.info("charged %.2f for order %s", req.amount, req.order_id)
    return {"charged": True, "order_id": req.order_id, "amount": req.amount}
