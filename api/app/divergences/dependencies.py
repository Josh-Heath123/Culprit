"""The session for the divergence writer.

A separate session factory from `app/facts/`'s even though both run as
`fact-writer`: the two endpoints are independent uploads, and sharing a
factory would make a transaction in one visible to the other in ways
neither is written to expect. It is a handful of lines and removes a
class of bug entirely.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_divergence_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.divergence_session_factory
    )
    async with session_factory() as session:
        yield session
