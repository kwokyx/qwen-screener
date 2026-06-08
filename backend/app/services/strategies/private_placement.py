"""定增公告监控策略：推送最近的定向增发公告。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import BaseStrategy, _item


class PrivatePlacementStrategy(BaseStrategy):
    id = "private_placement"
    name = "定增公告"
    tag = "事件"
    description = "监控最近 7 天内发布的定向增发公告，筛选定增事件驱动的股票。"
    rules = ["发行方式为定向增发", "发行日期在最近 7 天内", "按发行日期降序"]
    history_days = 1

    def run(self, df: pd.DataFrame) -> list[StrategyPickItem]:
        try:
            import akshare as ak
            raw = ak.stock_qbzf_em()
        except Exception:
            return []

        if raw is None or raw.empty:
            return []

        raw = raw[raw["发行方式"] == "定向增发"]
        if raw.empty:
            return []

        today = date.today()
        cutoff = today - timedelta(days=7)

        raw["发行日期"] = pd.to_datetime(raw["发行日期"], errors="coerce")
        raw = raw.dropna(subset=["发行日期"])
        raw = raw[raw["发行日期"].dt.date >= cutoff]
        if raw.empty:
            return []

        raw = raw.sort_values("发行日期", ascending=False)

        symbols = raw["股票代码"].astype(str).str.extract(r"(\d{6})")[0].dropna().tolist()
        seen = set()
        unique_symbols = []
        for s in symbols:
            if s not in seen:
                seen.add(s)
                unique_symbols.append(s)

        name_map = dict(zip(raw["股票代码"].astype(str).str.extract(r"(\d{6})")[0], raw["股票简称"]))

        items: list[StrategyPickItem] = []
        for symbol in unique_symbols:
            items.append(StrategyPickItem(
                code=symbol,
                name=name_map.get(symbol),
                industry=None,
                market=None,
                trade_date=today.strftime("%Y-%m-%d"),
                close=None,
                change_pct=None,
                score=80,
                signals=["定增公告"],
                metrics={},
            ))
        return items
