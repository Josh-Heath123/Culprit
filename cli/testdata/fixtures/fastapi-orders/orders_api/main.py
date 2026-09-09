"""The application object the extractor introspects."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Imported for its side effect of registering the mapped classes, which
# is how a real service reaches its models and is what makes SQLAlchemy
# metadata reachable to an extractor that imports this module. An app
# that never imports its models yields no schema facts, and the
# extractor says so rather than inventing any — see docs/LIMITS.md.
from orders_api import models  # noqa: F401

app = FastAPI(title="Orders API", version="0.2.0")


class OrderIn(BaseModel):
    customer_email: str
    total_cents: int


class OrderOut(BaseModel):
    id: int
    customer_email: str
    total_cents: int
    status: str


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/orders")
def list_orders() -> list[OrderOut]:
    return []


@app.post("/api/v1/orders", status_code=201)
def create_order(order: OrderIn) -> OrderOut:
    return OrderOut(id=1, customer_email=order.customer_email,
                    total_cents=order.total_cents, status="pending")


@app.get("/api/v1/orders/{order_id}")
def get_order(order_id: int) -> OrderOut:
    raise HTTPException(status_code=404, detail="not found")


@app.delete("/api/v1/orders/{order_id}", status_code=204)
def cancel_order(order_id: int) -> None:
    return None
