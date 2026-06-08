from __future__ import annotations

from app.schemas.strategy import StrategyPickItem
from app.services.strategies.base import BaseStrategy, DailyPoint, base_item


class LimitUpShakeoutStrategy(BaseStrategy):
    id = "limit_up_shakeout"
    name = "涨停后承接"
    tag = "短线"
    description = "涨停次日承接策略：昨日接近涨停，今日放量收阴但低点不破昨日收盘。"
    rules = ["昨日收盘价较前日上涨至少 9.5%", "今日收阴线", "今日成交量大于昨日 2 倍", "今日最低价不低于昨日收盘价"]
    history_days = 3
    max_codes = None

    def run(self, histories: dict[str, list[DailyPoint]]) -> list[StrategyPickItem]:
        items: list[StrategyPickItem] = []
        for points in histories.values():
            if len(points) < 3:
                continue
            prev2, prev1, today = points[-3], points[-2], points[-1]
            required = (
                prev2.close, prev1.close, prev1.volume,
                today.open, today.low, today.close, today.volume,
            )
            if any(value is None for value in required):
                continue
            limit_up_yesterday = prev1.close >= prev2.close * 1.095
            bearish_today = today.close < today.open
            volume_surge = today.volume > prev1.volume * 2.0
            support_hold = today.low >= prev1.close
            if limit_up_yesterday and bearish_today and volume_surge and support_hold:
                limit_up_pct = (prev1.close / prev2.close - 1) * 100
                volume_ratio = today.volume / prev1.volume if prev1.volume else 0
                support_gap = (today.low / prev1.close - 1) * 100 if prev1.close else 0
                score = (
                    35
                    + min(25, max(0, limit_up_pct - 9.5) * 20)
                    + min(30, volume_ratio * 8)
                    + min(10, max(0, support_gap) * 10)
                )
                items.append(base_item(points, score, ["昨日强势涨停", "今日放量收阴", "支撑不破"], {
                    "昨日涨幅%": limit_up_pct,
                    "今日量比昨日": volume_ratio,
                    "支撑距离%": support_gap,
                }))
        return items
