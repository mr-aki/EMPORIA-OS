from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VentureCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)


class VentureUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    status: Literal["planning", "active", "paused", "archived"] | None = None


class VentureRead(BaseModel):
    id: str
    name: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditRead(BaseModel):
    id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    detail: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
