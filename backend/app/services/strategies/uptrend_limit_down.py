from __future__ import annotations

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import (
    LONG_STRATEGY_CANDIDATE_LIMIT,
    BaseStrategy,
    DailyPoint,
    avg,
    base_item,
)


class UptrendLimitDownStrategy(BaseStrategy):
    id = "uptrend_limit_down"
    name = "趋势急跌修复"
    tag = "反转"
    description = "趋势回撤策略：上升趋势中出现放量急跌，用于观察错杀修复机会。"
    rules = ["昨日 20 日均线高于 60 日均线", "今日收盘价较昨日下跌至少 9.5%", "今日成交量大于 20 日均量 2 倍"]
    history_days = 65
    max_codes = LONG_STRATEGY_CANDIDATE_LIMIT

    def run(self, histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
        items: list[StrategyPickItem] = []
        for points in histories.values():
            if len(points) < 61:
                continue
            closes = [p.close for p in points]
            volumes = [p.volume for p in points]
            prev, today = points[-2], points[-1]
            ma20_prev = avg(closes[-21:-1])
            ma60_prev = avg(closes[-61:-1])
            vol20_today = avg(volumes[-20:])
            if None in (prev.close, today.close, today.volume, ma20_prev, ma60_prev, vol20_today):
                continue
            uptrend = ma20_prev > ma60_prev
            limit_down = today.close <= prev.close * 0.905
            volume_ratio = today.volume / vol20_today if vol20_today else 0
            volume_surge = volume_ratio > 2.0
            if uptrend and limit_down and volume_surge:
                trend_gap = (ma20_prev / ma60_prev - 1) * 100 if ma60_prev else 0
                drop_pct = (today.close / prev.close - 1) * 100 if prev.close else 0
                score = 30 + min(30, max(0, trend_gap) * 8) + min(30, abs(drop_pct) * 2) + min(10, volume_ratio)
                items.append(base_item(points, score, ["上升趋势", "放量急跌", "修复观察"], {
                    "MA20": ma20_prev,
                    "MA60": ma60_prev,
                    "今日跌幅%": drop_pct,
                    "量比20日": volume_ratio,
                }))
        return items
