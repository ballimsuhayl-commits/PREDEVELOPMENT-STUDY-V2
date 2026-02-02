from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class CheckLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    input_address: str
    normalized_address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    municipality: Optional[str] = None
    nsc_region: Optional[str] = None
    mpr_region: Optional[str] = None
    custom_region: Optional[str] = None

    ok: bool = False
    message: Optional[str] = None
