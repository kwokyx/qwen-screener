from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from statistics import mean
from typing import ClassVar

from app.schemas.strategy import StrategyPickItem, StrategyTemplate


STRATEGY_CANDIDATE_LIMIT = 500
LONG_STRATEGY_CANDIDATE_LIMIT = 300


@dataclass
class DailyPoint:
    code: str
    name: str | None
    industry: str | None
    market: str | None
    trade_date: object
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None


class BaseStrategy(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    tag: ClassVar[str]
    description: ClassVar[str]
    rules: ClassVar[list[str]]
    history_days: ClassVar[int]
    max_codes: ClassVar[int | None]

    @property
    def template(self) -> StrategyTemplate:
        return StrategyTemplate(
            id=self.id,
            name=self.name,
            tag=self.tag,
            description=self.description,
            rules=self.rules,
        )

    @abstractmethod
    def run(self, histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
        ...


def pct(last: DailyPoint, prev: DailyPoint | None) -> float | None:
    if not prev or not prev.close:
        return None
    return (last.close - prev.close) / prev.close * 100 if last.close is not None else None


def amount_yi(point: DailyPoint) -> float | None:
    # stock_daily.amount 统一按“元”存储，策略层转换为亿元。
    return point.amount / 1e8 if point.amount is not None else None


def avg(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return mean(nums) if nums and len(nums) == len(values) else None


def pct_rank(values: list[float], value: float) -> float:
    """Return pandas rank(pct=True) compatible average rank for one value."""
    if not values:
        return 0
    lower = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    if equal == 0:
        return 0
    average_rank = lower + (equal + 1) / 2
    return average_rank / len(values) * 100


def base_item(points: list[DailyPoint], score: float, signals: list[str], metrics: dict) -> StrategyPickItem:
    last = points[-1]
    prev = points[-2] if len(points) >= 2 else None
    return StrategyPickItem(
        code=last.code,
        name=last.name,
        industry=last.industry,
        market=last.market,
        trade_date=last.trade_date,
        close=last.close,
        change_pct=pct(last, prev),
        score=round(max(0, min(100, score)), 2),
        signals=signals,
        metrics={k: round(v, 2) if isinstance(v, float) else v for k, v in metrics.items()},
    )
