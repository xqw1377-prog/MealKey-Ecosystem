from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class StoreSettingsUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    city: Optional[str] = None
    area: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    cuisine_type: Optional[str] = None
    business_hours: Optional[str] = None
    audience: Optional[str] = None
    pain: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    delivery_radius_m: Optional[int] = Field(default=None, ge=500, le=10000)
    platform: Optional[str] = None
    platform_store_key: Optional[str] = None


class MenuItemSettingsInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None
    is_active: bool = True


class MenuSettingsUpdate(BaseModel):
    items: list[MenuItemSettingsInput] = Field(default_factory=list)


class SystemSettingPatch(BaseModel):
    key: str
    value: Optional[str] = None


class SystemSettingsUpdate(BaseModel):
    settings: list[SystemSettingPatch] = Field(default_factory=list)


class PlatformConnectRequest(BaseModel):
    platform: str = Field(min_length=2, max_length=64)
    mode: Literal["mock", "http", "mobile"] = "http"
    run_daily_job: bool = True


class AssistAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    store_id: Optional[str] = None


class OwnerProfileUpdate(BaseModel):
    """老板/操作者个人资料（头像入口可改）。"""

    display_name: str = Field(default="老板", min_length=1, max_length=40)
    phone: Optional[str] = Field(default=None, max_length=32)
    role: Optional[str] = Field(default="老板", max_length=40)
    avatar_data_url: Optional[str] = Field(default=None, max_length=240_000)


class EnterpriseSettingsUpdate(BaseModel):
    """企业主体资料；品牌字段会写到当前门店所属品牌。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    brand_name: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    cuisine_type: Optional[str] = Field(default=None, max_length=100)
    location: Optional[str] = Field(default=None, max_length=200)
    business_hours: Optional[str] = Field(default=None, max_length=200)


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    cuisine_type: Optional[str] = Field(default=None, max_length=100)
    business_hours: Optional[str] = Field(default=None, max_length=200)


class BrandSettingsUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    cuisine_type: Optional[str] = Field(default=None, max_length=100)
    business_hours: Optional[str] = Field(default=None, max_length=200)


class OrgStoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    city: Optional[str] = Field(default=None, max_length=120)
    area: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=300)


class StoreOpsRosterUpdate(BaseModel):
    manager_name: str = Field(default="", max_length=40)
    manager_phone: Optional[str] = Field(default=None, max_length=32)
    notify_channel: Optional[str] = Field(default="owner_relay", max_length=24)
    shift_note: Optional[str] = Field(default="", max_length=80)


class LoopEvidenceInput(BaseModel):
    kind: str = Field(default="note", max_length=24)
    note: str = Field(default="", max_length=400)
    data_url: Optional[str] = Field(default=None, max_length=240_000)
