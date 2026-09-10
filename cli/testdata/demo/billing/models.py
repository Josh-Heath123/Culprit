"""The billing schema, as the code expects it."""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    reference = Column(String(64), nullable=False)
    #: Declared here and never migrated. See README.md.
    total_cents = Column(Integer, nullable=False)


metadata = Base.metadata
