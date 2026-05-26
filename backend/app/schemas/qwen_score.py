from typing import Literal

from pydantic import BaseModel, Field


class StockScoreResponse(BaseModel):
    code: str
    source: Literal["qwen", "formula"] = "formula"
    cached: bool = False
    total: int = Field(ge=0, le=100)
    valuation: int = Field(ge=0, le=100)
    profit: int = Field(ge=0, le=100)
    growth: int = Field(ge=0, le=100)
    dividend: int = Field(ge=0, le=100)
    verdict: str
    reason: str | None = None
