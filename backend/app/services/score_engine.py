# -*- coding: utf-8 -*-
"""规则型基本面评分引擎（方案 B：数字分由此模块计算，千问仅解读）。

综合分 = 0.30×估值 + 0.30×盈利 + 0.25×成长 + 0.15×分红
各子维度由公开分档表映射到 0–100，详见 docs/SCORING_SCHEME_B.md
"""
from __future__ import annotations

from typing import Any

_VERDICTS = ("强烈关注", "可关注", "中性", "谨慎")

# (upper_bound_exclusive_or_none, score) — value <= bound 时取该档
_PE_TIERS = [(8, 95), (15, 80), (25, 60), (40, 40), (None, 20)]
_PB_TIERS = [(1.0, 95), (2, 75), (4, 55), (8, 35), (None, 20)]
_ROE_TIERS = [(5, 25), (10, 45), (15, 65), (20, 80), (None, 95)]
_GM_TIERS = [(20, 35), (30, 55), (40, 75), (None, 90)]
_DEBT_TIERS = [(40, 90), (60, 70), (75, 50), (None, 25)]
_YOY_TIERS = [(-10, 20), (0, 35), (10, 50), (20, 65), (30, 80), (None, 95)]
_DIV_TIERS = [(0.01, 35), (1, 50), (2, 65), (3, 80), (5, 95), (None, 25)]

_WEIGHTS = {
    "valuation": 0.30,
    "profit": 0.30,
    "growth": 0.25,
    "dividend": 0.15,
}


def _clamp(v: int) -> int:
    return max(0, min(100, int(v)))


def _tier(value: float | None, tiers: list[tuple[float | None, int]], *, missing: int = 60) -> int:
    if value is None:
        return missing
    try:
        x = float(value)
    except (TypeError, ValueError):
        return missing
    for bound, score in tiers:
        if bound is None or x <= bound:
            return score
    return missing


def _pe_score(pe: float | None) -> int:
    if pe is None:
        return 60
    try:
        x = float(pe)
    except (TypeError, ValueError):
        return 60
    if x <= 0:
        return 20
    return _tier(x, _PE_TIERS)


def _pb_score(pb: float | None) -> int:
    if pb is None:
        return 60
    try:
        x = float(pb)
    except (TypeError, ValueError):
        return 60
    if x <= 0:
        return 20
    return _tier(x, _PB_TIERS)


def _verdict_from_total(total: int) -> str:
    if total >= 80:
        return "强烈关注"
    if total >= 60:
        return "可关注"
    if total >= 40:
        return "中性"
    return "谨慎"


def _weighted_mean(pairs: list[tuple[int, float]]) -> int:
    """pairs: (score, weight)，缺项权重重分给其余项。"""
    valid = [(s, w) for s, w in pairs if w > 0]
    if not valid:
        return 60
    total_w = sum(w for _, w in valid)
    if total_w <= 0:
        return 60
    return _clamp(round(sum(s * w for s, w in valid) / total_w))


def compute(snapshot: dict) -> dict:
    """计算算法评分，返回含 breakdown 的完整结果（不含 reason）。"""
    pe = snapshot.get("pe")
    pb = snapshot.get("pb")
    roe = snapshot.get("roe")
    gm = snapshot.get("gross_margin")
    debt = snapshot.get("debt_ratio")
    rev_yoy = snapshot.get("revenue_yoy")
    prof_yoy = snapshot.get("profit_yoy")
    div = snapshot.get("dividend_yield")

    pe_s = _pe_score(pe)
    pb_s = _pb_score(pb)
    valuation = _weighted_mean([(pe_s, 0.4), (pb_s, 0.6)])

    roe_s = _tier(roe, _ROE_TIERS) if roe is not None else 60
    gm_s = _tier(gm, _GM_TIERS) if gm is not None else 60
    debt_s = _tier(debt, _DEBT_TIERS) if debt is not None else 60
    profit = _weighted_mean([(roe_s, 0.5), (gm_s, 0.3), (debt_s, 0.2)])

    rev_s = _tier(rev_yoy, _YOY_TIERS) if rev_yoy is not None else 60
    prof_s = _tier(prof_yoy, _YOY_TIERS) if prof_yoy is not None else 60
    growth = _weighted_mean([(rev_s, 0.5), (prof_s, 0.5)])

    if div is None:
        dividend = 25
    else:
        try:
            d = float(div)
            dividend = 25 if d <= 0 else _tier(d, _DIV_TIERS)
        except (TypeError, ValueError):
            dividend = 25

    total = _clamp(
        round(
            valuation * _WEIGHTS["valuation"]
            + profit * _WEIGHTS["profit"]
            + growth * _WEIGHTS["growth"]
            + dividend * _WEIGHTS["dividend"]
        )
    )

    breakdown: list[dict[str, Any]] = []
    if pe is not None:
        breakdown.append(
            {"metric": "pe", "label": "市盈率", "value": pe, "dimension": "valuation", "score": pe_s}
        )
    if pb is not None:
        breakdown.append(
            {"metric": "pb", "label": "市净率", "value": pb, "dimension": "valuation", "score": pb_s}
        )
    if roe is not None:
        breakdown.append(
            {"metric": "roe", "label": "ROE", "value": roe, "dimension": "profit", "score": roe_s}
        )
    if gm is not None:
        breakdown.append(
            {
                "metric": "gross_margin",
                "label": "毛利率",
                "value": gm,
                "dimension": "profit",
                "score": gm_s,
            }
        )
    if debt is not None:
        breakdown.append(
            {
                "metric": "debt_ratio",
                "label": "负债率",
                "value": debt,
                "dimension": "profit",
                "score": debt_s,
            }
        )
    if rev_yoy is not None:
        breakdown.append(
            {
                "metric": "revenue_yoy",
                "label": "营收同比",
                "value": rev_yoy,
                "dimension": "growth",
                "score": rev_s,
            }
        )
    if prof_yoy is not None:
        breakdown.append(
            {
                "metric": "profit_yoy",
                "label": "净利同比",
                "value": prof_yoy,
                "dimension": "growth",
                "score": prof_s,
            }
        )
    if div is not None:
        breakdown.append(
            {
                "metric": "dividend_yield",
                "label": "股息率",
                "value": div,
                "dimension": "dividend",
                "score": dividend,
            }
        )

    return {
        "code": snapshot.get("code", ""),
        "method": "rule_weighted",
        "total": total,
        "valuation": valuation,
        "profit": profit,
        "growth": growth,
        "dividend": dividend,
        "verdict": _verdict_from_total(total),
        "breakdown": breakdown,
    }


def template_reason(result: dict) -> str:
    """AI 不可用时的固定句式解读（≤40 字）。"""
    dims = [
        ("估值", result.get("valuation", 60)),
        ("盈利", result.get("profit", 60)),
        ("成长", result.get("growth", 60)),
        ("分红", result.get("dividend", 60)),
    ]
    dims.sort(key=lambda x: x[1], reverse=True)
    strong, weak = dims[0][0], dims[-1][0]
    total = result.get("total", 60)
    if total >= 80:
        tail = "综合偏强"
    elif total >= 60:
        tail = "整体尚可"
    elif total >= 40:
        tail = "中性观望"
    else:
        tail = "宜谨慎"
    text = f"{strong}较好、{weak}偏弱，{tail}。"
    return text[:40]
