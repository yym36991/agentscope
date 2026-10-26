# -*- coding: utf-8 -*-
"""Price baseline model (§7.1 dual track).

Core numbers (rates, factors, productivity baselines) live in this
structured table so the budget agent queries them exactly through the
price-baseline tool — never "retrieved and guessed" from a vector
store. Explanatory documents still go through KB RAG like everything
else.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PriceItem(Base):
    __tablename__ = "price_items"
    __table_args__ = (
        # One row per (region, type, name, year): re-importing the
        # same year replaces the old set for that key first.
        UniqueConstraint(
            "region",
            "item_type",
            "name",
            "effective_year",
            name="uq_price_items_key",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    # e.g. "全国" / "北京" — human-matching happens in the query tool.
    region: Mapped[str] = mapped_column(String(64), index=True)
    # e.g. "人月费率" / "调整因子" / "生产率基准"
    item_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    value: Mapped[float] = mapped_column(Float, nullable=False)
    # e.g. "元/人月" / "倍" — the unit the agent must cite alongside.
    unit: Mapped[str] = mapped_column(String(64))
    effective_year: Mapped[int] = mapped_column(Integer, nullable=False)
    # Where the number came from (audit trail, bank requirement).
    source: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    imported_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
