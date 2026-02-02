from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class CheckRequest(BaseModel):
    address: str = Field(..., min_length=1)
    country: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class LayerHit(BaseModel):
    layer: str
    match: Optional[str] = None
    reason: Optional[str] = None


class CheckResponse(BaseModel):
    ok: bool
    input_address: str
    normalized_address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    municipality: Optional[str] = None
    nsc_region: Optional[str] = None
    mpr_region: Optional[str] = None
    custom_region: Optional[str] = None

    hits: List[LayerHit] = []
    message: Optional[str] = None


class HistoryRow(BaseModel):
    id: int
    created_at: datetime
    input_address: str
    normalized_address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    municipality: Optional[str] = None
    nsc_region: Optional[str] = None
    mpr_region: Optional[str] = None
    custom_region: Optional[str] = None
    ok: bool
    message: Optional[str] = None
