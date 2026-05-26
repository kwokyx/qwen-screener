from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionIn(BaseModel):
    """前端创建一条历史时上传的字段。query 必填，其余可空。"""
    query: str = Field(min_length=1, max_length=512)
    parsed_conditions: list | None = None
    items: list | None = None
    total: int | None = None
    screen_meta: dict | None = None


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    query: str
    parsed_conditions: list | None = None
    items: list | None = None
    total: int | None = None
    screen_meta: dict | None = None
    created_at: datetime
