from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class CheckRequest(SQLModel):
    address: str
    country: Optional[str] = "South Africa"
    lat: Optional[float] = None
    lon: Optional[float] = None


class CheckResult(SQLModel):
    ok: bool
    input_address: str
    normalized_address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    municipality: Optional[str] = None
    province: Optional[str] = None
    nsc_region: Optional[str] = None
    mpr_region: Optional[str] = None
    custom_region: Optional[str] = None

    confidence: float = 0.0
    reason: Optional[str] = None


class CheckLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    address: str
    normalized_address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    municipality: Optional[str] = None
    province: Optional[str] = None
    nsc_region: Optional[str] = None
    mpr_region: Optional[str] = None
    custom_region: Optional[str] = None

    confidence: float = 0.0
    ok: bool = True
    reason: Optional[str] = None
