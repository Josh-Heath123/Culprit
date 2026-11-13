"""Steady baseline traffic against the demo services.

Without a baseline, "error rate" and "latency" are meaningless — Phase 4's
anomaly detection needs a normal signal to detect deviation from. Requests
are fired as background tasks rather than awaited in the loop, so an
injected latency fault slows individual requests without slowing the
generator's own send rate.

Two kinds of traffic, each at its own rate (0 turns it off):

* POST /orders on order-service (LOAD_GEN_RATE_RPS);
* GET /products?category=… on inventory-service, across the seeded
  categories (LOAD_GEN_PRODUCTS_RPS). Phase 37 part 3: Culprit's statement
  window measures the system's own traffic and sends none of its own, so
  this is what makes the list route's statement visible to it. The fault
  library runs this kind alone.
"""

import asyncio
import os
import random

import httpx

ORDER_SERVICE_URL = os.environ.get("ORDER_SERVICE_URL", "http://localhost:8001")
INVENTORY_SERVICE_URL = os.environ.get("INVENTORY_SERVICE_URL", "http://localhost:8002")
RATE_RPS = float(os.environ.get("LOAD_GEN_RATE_RPS", "2"))
PRODUCTS_RPS = float(os.environ.get("LOAD_GEN_PRODUCTS_RPS", "1"))
REQUEST_TIMEOUT_S = float(os.environ.get("LOAD_GEN_TIMEOUT_S", "10"))
SKUS = ["widget-a", "widget-b", "widget-c"]
# The 200 categories inventory-service's 0002 migration seeds.
CATEGORIES = [f"category-{n:03d}" for n in range(200)]


async def place_order(client: httpx.AsyncClient) -> None:
    body = {
        "sku": random.choice(SKUS),
        "qty": random.randint(1, 3),
        "amount": round(random.uniform(10, 200), 2),
    }
    url = f"{ORDER_SERVICE_URL}/orders"
    try:
        resp = await client.post(url, json=body, timeout=REQUEST_TIMEOUT_S)
        print(f"[load-gen] POST /orders {body['sku']} -> {resp.status_code}")
    except httpx.HTTPError as exc:
        print(f"[load-gen] POST /orders {body['sku']} -> error: {exc}")


async def list_products(client: httpx.AsyncClient) -> None:
    category = random.choice(CATEGORIES)
    url = f"{INVENTORY_SERVICE_URL}/products"
    try:
        resp = await client.get(url, params={"category": category}, timeout=REQUEST_TIMEOUT_S)
        print(f"[load-gen] GET /products {category} -> {resp.status_code}")
    except httpx.HTTPError as exc:
        print(f"[load-gen] GET /products {category} -> error: {exc}")


async def steady(rate: float, send, client: httpx.AsyncClient) -> None:
    """Sends at `rate` requests a second, without waiting for answers."""
    interval = 1.0 / rate
    background_tasks: set[asyncio.Task] = set()
    while True:
        task = asyncio.create_task(send(client))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        await asyncio.sleep(interval)


async def main() -> None:
    print(
        f"[load-gen] POST {ORDER_SERVICE_URL}/orders at {RATE_RPS} req/s, "
        f"GET {INVENTORY_SERVICE_URL}/products at {PRODUCTS_RPS} req/s"
    )
    async with httpx.AsyncClient() as client:
        senders = [
            steady(rate, send, client)
            for rate, send in ((RATE_RPS, place_order), (PRODUCTS_RPS, list_products))
            if rate > 0
        ]
        await asyncio.gather(*senders)


if __name__ == "__main__":
    asyncio.run(main())
