from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CompetitorMenuItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    price: Optional[float] = Field(default=None, ge=0)
    image_url: Optional[str] = Field(default=None, max_length=500)
    rating: Optional[float] = Field(default=None, ge=0, le=5)


class CompetitorSnapshotInput(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    external_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    area: Optional[str] = Field(default=None, max_length=120)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    review_count: Optional[int] = Field(default=None, ge=0)
    price_band_min: Optional[float] = Field(default=None, ge=0)
    price_band_max: Optional[float] = Field(default=None, ge=0)
    source_url: Optional[str] = Field(default=None, max_length=500)
    captured_at: Optional[datetime] = None
    menu_items: list[CompetitorMenuItemInput] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class CompetitionCollectionResult(BaseModel):
    run_id: str
    store_id: str
    provider: str
    status: str
    discovered_count: int
    snapshot_count: int
    skipped_count: int = 0
    error: Optional[str] = None


class CompetitionMapPoint(BaseModel):
    competitor_id: str
    name: str
    latitude: float
    longitude: float
    distance_m: Optional[int] = None
    score: Optional[int] = None
    category: Optional[str] = None
    rating: Optional[float] = None
    price_band: Optional[str] = None
    latest_change: Optional[str] = None


class CompetitionMapResponse(BaseModel):
    store_id: str
    store_name: str
    center_latitude: float
    center_longitude: float
    radius_m: int
    generated_at: datetime
    competitors: list[CompetitionMapPoint] = Field(default_factory=list)
