"""多租户：Tenant 绑定门店，凭证换 JWT。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenant"

    name: Mapped[str] = mapped_column(String(200))
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_secret_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active")

    stores: Mapped[list["TenantStore"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
    )


class TenantStore(IdMixin, Base):
    __tablename__ = "tenant_store"
    __table_args__ = (UniqueConstraint("tenant_id", "store_id", name="uq_tenant_store"),)

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="operator")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="stores")
