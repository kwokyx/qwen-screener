"""规则评分引擎单元测试。"""
from app.services.score_engine import compute, template_reason


def test_compute_weighted_total_in_range():
    snap = {
        "code": "600519.SH",
        "pe": 28.0,
        "pb": 8.5,
        "roe": 32.0,
        "revenue_yoy": 12.0,
        "profit_yoy": 10.0,
        "gross_margin": 91.0,
        "debt_ratio": 22.0,
        "dividend_yield": 1.8,
    }
    r = compute(snap)
    assert 0 <= r["total"] <= 100
    assert r["verdict"] in ("强烈关注", "可关注", "中性", "谨慎")
    assert len(r["breakdown"]) >= 5
    assert r["method"] == "rule_weighted"


def test_low_pe_high_roe_scores_higher():
    good = compute({"code": "x", "pe": 8, "pb": 1.2, "roe": 22, "dividend_yield": 4.5})
    bad = compute({"code": "y", "pe": 55, "pb": 6, "roe": 3, "dividend_yield": 0})
    assert good["total"] > bad["total"]


def test_verdict_thresholds():
    assert compute({"code": "a", "pe": 6, "pb": 0.8, "roe": 25, "dividend_yield": 5})["total"] >= 60


def test_template_reason_length():
    r = compute({"code": "t", "pe": 15, "roe": 12})
    text = template_reason(r)
    assert len(text) <= 40
