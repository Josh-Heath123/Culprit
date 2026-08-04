"""Steady baseline traffic against order-service.

Without a baseline, "error rate" and "latency" are meaningless — Phase 4's
anomaly detection needs a normal signal to detect deviation from. Requests
are fired as background tasks rather than awaited in the loop, so an
injected latency fault slows individual requests without slowing the
generator's own send rate.
"""

import asyncio
import os
import random

import httpx

ORDER_SERVICE_URL = os.environ.get("ORDER_SERVICE_URL", "http://localhost:8001")
RATE_RPS = float(os.environ.get("LOAD_GEN_RATE_RPS", "2"))
REQUEST_TIMEOUT_S = float(os.environ.get("LOAD_GEN_TIMEOUT_S", "10"))
SKUS = ["widget-a", "widget-b", "widget-c"]


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


async def main() -> None:
    interval = 1.0 / RATE_RPS
    print(f"[load-gen] targeting {ORDER_SERVICE_URL} at {RATE_RPS} req/s")
    background_tasks: set[asyncio.Task] = set()
    async with httpx.AsyncClient() as client:
        while True:
            task = asyncio.create_task(place_order(client))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
