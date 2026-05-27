from typing import Any, Literal

from pydantic import BaseModel, Field


class ScoreBreakdownItem(BaseModel):
    metric: str
    label: str
    value: float | int | str
    dimension: Literal["valuation", "profit", "growth", "dividend"]
    score: int = Field(ge=0, le=100)


class StockScoreResponse(BaseModel):
    code: str
    source: Literal["algorithm"] = "algorithm"
    reason_source: Literal["qwen", "template", "none"] = "none"
    method: str = "rule_weighted"
    cached: bool = False
    total: int = Field(ge=0, le=100)
    valuation: int = Field(ge=0, le=100)
    profit: int = Field(ge=0, le=100)
    growth: int = Field(ge=0, le=100)
    dividend: int = Field(ge=0, le=100)
    verdict: str
    reason: str | None = None
    breakdown: list[ScoreBreakdownItem] = Field(default_factory=list)
