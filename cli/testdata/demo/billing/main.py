"""A tiny billing API, enough to have a route table worth reading."""

from fastapi import FastAPI

from models import metadata  # noqa: F401  -- imported so the metadata is reachable

app = FastAPI(title="Billing")


@app.get("/api/v1/invoices/{invoice_id}")
async def get_invoice(invoice_id: int) -> dict:
    return {"id": invoice_id}


@app.post("/api/v1/invoices")
async def create_invoice() -> dict:
    return {"id": 1}
