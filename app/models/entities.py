from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class Merchant(IdMixin, TimestampMixin, Base):
    __tablename__ = "merchant"

    name: Mapped[str] = mapped_column(String(200))
    brand_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cuisine_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    business_hours: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    brands: Mapped[list["Brand"]] = relationship(back_populates="merchant")
    stores: Mapped[list["Store"]] = relationship(back_populates="merchant")


class Brand(IdMixin, TimestampMixin, Base):
    """企业主体下的品牌。一个企业可有多个品牌，一个品牌可有多家门店。"""

    __tablename__ = "brand"

    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cuisine_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    business_hours: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")

    merchant: Mapped["Merchant"] = relationship(back_populates="brands")
    stores: Mapped[list["Store"]] = relationship(back_populates="brand")


class Store(IdMixin, TimestampMixin, Base):
    __tablename__ = "store"

    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"))
    brand_id: Mapped[Optional[str]] = mapped_column(ForeignKey("brand.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))

    address: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    area: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    delivery_radius_m: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")

    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    platform_store_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    primary_audience: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    primary_pain: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    merchant: Mapped["Merchant"] = relationship(back_populates="stores")
    brand: Mapped[Optional["Brand"]] = relationship(back_populates="stores")
    items: Mapped[list["MenuItem"]] = relationship(back_populates="store")


class Menu(IdMixin, TimestampMixin, Base):
    __tablename__ = "menu"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    name: Mapped[str] = mapped_column(String(200), default="默认菜单")
    type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="active")


class MenuItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "menu_item"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    menu_id: Mapped[Optional[str]] = mapped_column(ForeignKey("menu.id"), nullable=True)
    current_version_id: Mapped[Optional[str]] = mapped_column(ForeignKey("menu_item_version.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 成本缓存(从 CostRecord 最近一条同步,供 calculate_profit 快速读取)
    food_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    packaging_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cost_confidence: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    cost_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    store: Mapped["Store"] = relationship(back_populates="items")
    versions: Mapped[list["MenuItemVersion"]] = relationship(
        back_populates="item",
        foreign_keys="MenuItemVersion.item_id",
    )
    current_version: Mapped[Optional["MenuItemVersion"]] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class MenuItemVersion(IdMixin, Base):
    __tablename__ = "menu_item_version"

    item_id: Mapped[str] = mapped_column(ForeignKey("menu_item.id"))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    item: Mapped["MenuItem"] = relationship(
        back_populates="versions",
        foreign_keys=[item_id],
    )


class OrderFact(IdMixin, TimestampMixin, Base):
    __tablename__ = "order_fact"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    platform_order_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gmv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class OrderItemFact(IdMixin, TimestampMixin, Base):
    __tablename__ = "order_item_fact"

    order_id: Mapped[str] = mapped_column(ForeignKey("order_fact.id"))
    item_id: Mapped[Optional[str]] = mapped_column(ForeignKey("menu_item.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class ShopFunnelDaily(Base):
    __tablename__ = "shop_funnel_daily"
    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)

    impressions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    visits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    add_to_cart: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    repurchase: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gmv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    orders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aov: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Provenance — 每条数据有来源,区分真实导入 vs mock/合成
    data_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default="platform_export")
    ads_spend: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 当日推广费


class ItemFunnelDaily(Base):
    __tablename__ = "item_funnel_daily"
    item_id: Mapped[str] = mapped_column(ForeignKey("menu_item.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)

    impressions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    visits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    orders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gmv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ctr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cvr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # observed = 真实导入/平台；synthetic = 店级漏斗分摊，归因时降权
    data_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class ReviewFact(IdMixin, TimestampMixin, Base):
    __tablename__ = "review_fact"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    item_id: Mapped[Optional[str]] = mapped_column(ForeignKey("menu_item.id"), nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewNLP(Base):
    __tablename__ = "review_nlp"
    review_id: Mapped[str] = mapped_column(ForeignKey("review_fact.id"), primary_key=True)
    taste: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    portion: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    package: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class CompetitorStore(IdMixin, TimestampMixin, Base):
    __tablename__ = "competitor_store"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "platform_store_key",
            name="uq_competitor_store_platform_key",
        ),
    )

    area: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    platform_store_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class CompetitorSnapshot(IdMixin, Base):
    __tablename__ = "competitor_snapshot"

    c_store_id: Mapped[str] = mapped_column(ForeignKey("competitor_store.id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_band_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_band_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class CompetitorMenuItem(IdMixin, Base):
    __tablename__ = "competitor_menu_item"

    snapshot_id: Mapped[str] = mapped_column(ForeignKey("competitor_snapshot.id"))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class CompetitionCollectionRun(IdMixin, Base):
    __tablename__ = "competition_collection_run"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CompetitorRawPayload(IdMixin, Base):
    __tablename__ = "competitor_raw_payload"

    run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("competition_collection_run.id"),
        nullable=True,
    )
    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    payload_json: Mapped[str] = mapped_column(Text)
    checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class StoreCompetitorWatch(IdMixin, Base):
    __tablename__ = "store_competitor_watch"
    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "c_store_id",
            name="uq_store_competitor_watch",
        ),
    )

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    c_store_id: Mapped[str] = mapped_column(ForeignKey("competitor_store.id"))
    provider: Mapped[str] = mapped_column(String(32))
    distance_m: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
