from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import pandas as pd

from app.schemas.strategy import StrategyPickItem, StrategyTemplate


class BaseStrategy(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    tag: ClassVar[str]
    description: ClassVar[str]
    rules: ClassVar[list[str]]
    history_days: ClassVar[int]

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
    def run(self, df: pd.DataFrame) -> list[StrategyPickItem]:
        """Run strategy on full-market DataFrame.

        DataFrame columns:
            symbol, date, open, high, low, close, volume, amount,
            name, industry, market
        """
        ...


def _item(
    row: pd.Series,
    score: float,
    signals: list[str],
    metrics: dict,
    prev_close: float | None = None,
) -> StrategyPickItem:
    score = round(max(0, min(100, score)), 2)
    close = row["close"]
    change_pct = None
    if prev_close is not None and prev_close > 0:
        change_pct = (close / prev_close - 1) * 100
    return StrategyPickItem(
        code=row["symbol"],
        name=row.get("name") or None,
        industry=row.get("industry") or None,
        market=row.get("market") or None,
        trade_date=str(row["date"]) if pd.notna(row["date"]) else None,
        close=float(close) if pd.notna(close) else None,
        change_pct=round(change_pct, 2) if change_pct is not None else None,
        score=score,
        signals=signals,
        metrics={k: round(v, 2) if isinstance(v, float) else v for k, v in metrics.items()},
    )
