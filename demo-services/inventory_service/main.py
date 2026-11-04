import logging
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from shared.faults import FaultState, build_fault_router
from shared.middleware import TelemetryFaultMiddleware
from shared.otel import configure_otel

from shared import demo_auth

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

# Phase 32's fault library. Both are off unless set, so the quickstart is
# unchanged:
#  * EXPECTED_AUDIENCE + DEMO_TOKEN_SECRET: callers must present a bearer
#    token for this audience — the audience fault is a caller whose token
#    names another.
#  * CONTRACT_FAULT=stock-route-renamed: the stock route moves, so a caller
#    that declares GET /stock gets a 404 — the contract fault. The route
#    takes the sku as a query parameter, not a path parameter: a probe can
#    tell a missing route from a missing item only on a path with no
#    parameter in it (docs/LIMITS.md).
EXPECTED_AUDIENCE = os.environ.get("EXPECTED_AUDIENCE", "")
TOKEN_SECRET = os.environ.get("DEMO_TOKEN_SECRET", "")
STOCK_ROUTE = (
    "/stock-levels" if os.environ.get("CONTRACT_FAULT") == "stock-route-renamed" else "/stock"
)
_stock: dict[str, int] = {}


class ReserveRequest(BaseModel):
    order_id: str
    sku: str
    qty: int


def _require_token(authorization: str | None) -> None:
    if not (EXPECTED_AUDIENCE and TOKEN_SECRET):
        return
    problem = demo_auth.verify(authorization, TOKEN_SECRET, EXPECTED_AUDIENCE)
    if problem is not None:
        logger.warning("refused a caller's token: %s", problem)
        raise HTTPException(status_code=401, detail=f"token refused: {problem}")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    """Readiness through the fault middleware, unlike /health — what the
    isolation walk asks, because a check that injected faults skip cannot
    tell the walk a request here fails."""
    return {"status": "ready"}


def get_stock(sku: str = "", authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    return {"sku": sku, "available": _stock.get(sku, _DEFAULT_STOCK)}


app.add_api_route(STOCK_ROUTE, get_stock, methods=["GET"])


@app.post("/reserve", status_code=201)
def reserve(req: ReserveRequest, authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    available = _stock.setdefault(req.sku, _DEFAULT_STOCK)
    if available < req.qty:
        logger.warning(
            "insufficient stock for %s (requested %d, have %d)", req.sku, req.qty, available
        )
        raise HTTPException(status_code=409, detail="insufficient stock")
    _stock[req.sku] = available - req.qty
    logger.info("reserved %d of %s for order %s", req.qty, req.sku, req.order_id)
    return {"reserved": True, "sku": req.sku, "remaining": _stock[req.sku]}
