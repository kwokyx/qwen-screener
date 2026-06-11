from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationIn(BaseModel):
    kind: str = Field(default="alert", max_length=16)
    tone: str | None = Field(default=None, max_length=16)
    stock_code: str | None = Field(default=None, max_length=16)
    stock_name: str | None = Field(default=None, max_length=64)
    title: str = Field(max_length=128)
    desc: str | None = Field(default=None, max_length=512)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    tone: str | None = None
    stock_code: str | None = None
    stock_name: str | None = None
    title: str
    desc: str | None = None
    fired_at: datetime
    dismissed_at: datetime | None = None
