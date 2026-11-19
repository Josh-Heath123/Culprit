# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

import logging
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from shared.faults import FaultState, build_fault_router
from shared.middleware import TelemetryFaultMiddleware
from shared.otel import configure_otel
from shared.startup import startup
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from inventory_service.db import engine
from shared import demo_auth

SERVICE_NAME = "inventory-service"
configure_otel(SERVICE_NAME)
logger = logging.getLogger(SERVICE_NAME)

fault_state = FaultState()
app = FastAPI(title=SERVICE_NAME, lifespan=startup(lambda: _warm()))
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


# The category the storefront shows when none is asked for. A request with
# no query is how probe.http.latency times a route — its budget is on the
# route, never on an input to it (docs/PROBES.md) — so GET /products must
# answer one, with the same statement a filtered request runs.
#
# It is a new category, launched on the storefront before it is stocked:
# 0002 seeds category-000 to category-199, never this one. That is the
# demo's database fault (Q35): without an index led by `category`, Postgres
# walks `ix_products_sku` for the order and filters row by row, which stops
# early for a seeded category (one every ~200 skus) and walks the whole
# index for a category with no products.
FEATURED_CATEGORY = "category-200"


@app.get("/products")
def list_products(category: str = FEATURED_CATEGORY, limit: int = 50) -> dict:
    """The catalogue for one category, from the service's own database
    (Phase 37 part 1, P8), in sku order. It filters on `category`, which
    0003 indexes as (category, sku): the fault library's database fault is
    that index missing, seen on a category with no products, such as the
    featured one. Not on the order path: POST /orders never reads it,
    so the library's order walks are unchanged.
    """
    database = engine()
    if database is None:
        raise HTTPException(status_code=503, detail="this inventory-service has no database")
    limit = max(1, min(limit, 200))
    with database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT sku, name, price_cents FROM products "
                "WHERE category = :category ORDER BY sku LIMIT :limit"
            ),
            {"category": category, "limit": limit},
        ).all()
    return {
        "category": category,
        "products": [
            {"sku": sku, "name": name, "price_cents": price_cents}
            for sku, name, price_cents in rows
        ],
    }


# Phase 39 part 2's fault library: the N+1 fault, off unless set, so the
# quickstart is unchanged. N_PLUS_ONE_FAULT=details-per-product makes GET
# /products/details load each product's details with a statement of its
# own, one per item; unset, one statement loads them all. A toggle, as
# CONTRACT_FAULT is, so the known fix is a configuration change a capture
# records (config:inventory-service/N_PLUS_ONE_FAULT).
DETAILS_PER_PRODUCT = os.environ.get("N_PLUS_ONE_FAULT") == "details-per-product"

# The page GET /products/details answers with no query: what a probe, which
# sends none, sees. Its size decides what loading each item's details
# separately costs, and so the route's latency budget in culprit.yaml,
# which is measured against this page (Q37). At most the route's declared
# list bound, response_items_max. 500 (Phase 40 part 1, C1): an N+1's cost
# is the runner's round trip, and at 200 the fault's sample 45 came within
# 2.6 ms of its budget on CI's fastest runner. The join's cost hardly moves
# with the page; the N+1's grows with it (measured at 200, 400 and 600:
# the join's slowest 5.9 to 9.0 ms throughout, the N+1's sample 45 from
# 35.8 to 128.7 ms). At 50 the N+1 measured 15.5 to 15.9 ms, too close to
# the join to tell apart.
DETAILS_PAGE = 500


@app.get("/products/details")
def list_product_details(limit: int = DETAILS_PAGE) -> dict:
    """The first products by id, each with its details from
    product_details (0004), one row per product. Not on the order path."""
    database = engine()
    if database is None:
        raise HTTPException(status_code=503, detail="this inventory-service has no database")
    limit = max(1, min(limit, DETAILS_PAGE))
    with database.connect() as connection:
        if DETAILS_PER_PRODUCT:
            products = connection.execute(
                text("SELECT id, sku, name FROM products ORDER BY id LIMIT :limit"),
                {"limit": limit},
            ).all()
            rows = []
            for product_id, sku, name in products:
                details = connection.execute(
                    text(
                        "SELECT description, weight_grams FROM product_details "
                        "WHERE product_id = :product_id"
                    ),
                    {"product_id": product_id},
                ).one()
                rows.append((sku, name, details[0], details[1]))
        else:
            rows = connection.execute(
                text(
                    "SELECT p.sku, p.name, d.description, d.weight_grams FROM products p "
                    "JOIN product_details d ON d.product_id = p.id ORDER BY p.id LIMIT :limit"
                ),
                {"limit": limit},
            ).all()
    return {
        "products": [
            {"sku": sku, "name": name, "description": description, "weight_grams": weight}
            for sku, name, description, weight in rows
        ],
    }


def _warm() -> None:
    """Startup's warm-up (Q39): each database read path once, before /ready
    answers, so no request a probe times is the process's first. A read
    that fails is skipped and logged: the database may be at a revision
    without product_details (the missing-index fault holds it at 0002), or
    not configured at all."""
    if engine() is None:
        return
    for read in (list_products, list_product_details):
        try:
            read()
        except SQLAlchemyError as error:
            logger.info("startup warm-up of %s skipped: %s", read.__name__, type(error).__name__)


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
