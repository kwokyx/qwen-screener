from __future__ import annotations

from datetime import date as Date
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.screener import FilterCondition, ScreenResponse


class StrategyTemplate(BaseModel):
    id: str
    name: str
    tag: str
    description: str
    rules: list[str]
    source: str = "Sequoia-X 规则改写"


class StrategyToolField(BaseModel):
    key: str
    label: str
    data_type: str
    operators: list[str]
    description: str


class StrategyToolInfo(BaseModel):
    id: str
    label: str
    category: str
    description: str
    inputs: list[str]
    outputs: list[str]
    examples: list[str]
    fields: list[StrategyToolField] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)


class StrategySelectRequest(BaseModel):
    strategy_id: str = Field(default="turtle_breakout")
    limit: int = Field(default=50, ge=1, le=200)


class StrategyPickItem(BaseModel):
    code: str
    name: str | None = None
    industry: str | None = None
    market: str | None = None
    trade_date: Date | None = None
    close: float | None = None
    change_pct: float | None = None
    score: float
    signals: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class StrategySelectResponse(BaseModel):
    strategy: StrategyTemplate
    trade_date: Date | None = None
    total: int
    items: list[StrategyPickItem]
    notes: list[str] = Field(default_factory=list)


class StrategyAgentRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=50, ge=1, le=200)


class StrategyAgentPlan(BaseModel):
    tool: str
    tool_label: str
    reasoning: str
    strategy_id: str | None = None
    conditions: list[FilterCondition] = Field(default_factory=list)
    condition_labels: list[str] = Field(default_factory=list)
    logic: str = "AND"
    sort_by: str | None = None
    sort_desc: bool = True
    ai_configured: bool = False
    ai_used: bool = False


class StrategyAgentResponse(BaseModel):
    query: str
    plan: StrategyAgentPlan
    strategy_result: StrategySelectResponse | None = None
    screen_result: ScreenResponse | None = None
    answer: str
    warnings: list[str] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
