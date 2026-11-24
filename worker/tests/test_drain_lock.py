# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""F44-040 (Phase 44 batch 3): the drain lock, against a real Redis.

The lock that keeps two drains from writing one batch twice expired after
30 seconds whatever the drain was doing, and was released with an
unconditional DELETE: a drain slower than that lost its lock to the next
tick, and then deleted the next tick's lock when it finished, so a third
could start beside the second. Now it is released only by its holder
(compare-and-delete on a token) and renewed while held.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import redis.asyncio as redis
from app import consumer
from testcontainers.community.redis import RedisContainer

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def client(redis_url: str) -> AsyncIterator[redis.Redis]:
    connection = redis.from_url(redis_url, decode_responses=False)
    await connection.flushdb()
    yield connection
    await connection.aclose()


async def test_a_drain_never_releases_a_lock_it_no_longer_holds(
    client: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lost_the_lock(*args, **kwargs) -> consumer.DrainResult:
        # The lock expired mid-drain and the next tick took it.
        await client.set(consumer.LOCK_KEY, b"the-next-tick")
        return consumer.DrainResult(written=0, quarantined=0)

    monkeypatch.setattr(consumer, "_drain_batch", lost_the_lock)

    await consumer.drain_streams({"redis": client, "engine": None})

    assert await client.get(consumer.LOCK_KEY) == b"the-next-tick"


async def test_the_lock_is_renewed_while_a_drain_holds_it(
    client: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(consumer, "LOCK_TTL_S", 1)
    held: list[bool] = []

    async def slow(*args, **kwargs) -> consumer.DrainResult:
        await asyncio.sleep(2.5)  # past the lock's 1 s expiry
        held.append(await client.exists(consumer.EDGES_LOCK_KEY) == 1)
        return consumer.DrainResult(written=0, quarantined=0)

    monkeypatch.setattr(consumer, "_drain_batch", slow)

    await consumer.drain_edges({"redis": client, "engine": None})

    assert held == [True, True], "the lock expired while the drain still held it"
    assert await client.exists(consumer.EDGES_LOCK_KEY) == 0, "released when the drain ended"


async def test_a_second_drain_skips_while_the_first_holds_the_lock(
    client: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def first(*args, **kwargs) -> consumer.DrainResult:
        entered.set()
        await release.wait()
        return consumer.DrainResult(written=0, quarantined=0)

    monkeypatch.setattr(consumer, "_drain_batch", first)
    running = asyncio.create_task(consumer.drain_streams({"redis": client, "engine": None}))
    await entered.wait()
    assert await consumer.drain_streams({"redis": client, "engine": None}) == {}
    release.set()
    await running
