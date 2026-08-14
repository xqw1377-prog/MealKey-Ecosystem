from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


class IntakeMenuItemInput(BaseModel):
    name: str
    category: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class IntakeDailyMetricInput(BaseModel):
    day: date
    impressions: Optional[int] = None
    visits: Optional[int] = None
    add_to_cart: Optional[int] = None
    payments: Optional[int] = None
    orders: Optional[int] = None
    gmv: Optional[float] = None
    aov: Optional[float] = None


class IntakeRawAssetInput(BaseModel):
    asset_type: Literal["store_link", "menu_note", "report_note", "screenshot_note", "review_note"]
    label: str
    source_url: Optional[HttpUrl] = None
    raw_text: Optional[str] = None


class IntakePreviewRequest(BaseModel):
    store_name: str
    merchant_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    category: Optional[str] = None
    cuisine_type: Optional[str] = None
    audience: Optional[str] = None
    pain: Optional[str] = None
    platform: Optional[str] = None
    platform_store_url: Optional[HttpUrl] = None
    menu_items: list[IntakeMenuItemInput] = Field(default_factory=list)
    daily_metrics: list[IntakeDailyMetricInput] = Field(default_factory=list)
    raw_assets: list[IntakeRawAssetInput] = Field(default_factory=list)


class IntakeSubmitRequest(IntakePreviewRequest):
    business_hours: Optional[str] = None
    referral_artifact_id: Optional[str] = Field(default=None, max_length=36)


class DocumentSyncRequest(BaseModel):
    assets: list[IntakeRawAssetInput] = Field(default_factory=list)
    note: Optional[str] = Field(default=None, max_length=500)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    days: int = Field(default=7, ge=1, le=30)
    work_thread_id: Optional[str] = Field(default=None, max_length=64)
