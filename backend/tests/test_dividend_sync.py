from datetime import date, timedelta

from app.models.stock import StockBasic, StockDaily, StockDividend
from app.services import data_sync
from app.services.providers import baostock_provider


def test_parse_dividend_row_uses_cash_per_share_column():
    row = [
        "sh.600519", "", "2025-05-20", "2025-04-03", "2025-06-20",
        "2025-06-25", "2025-06-26", "2025-06-26", "", "27.673",
        "24.9057或27.673", "0.000000", "10派276.73元", "",
    ]

    parsed = baostock_provider._parse_dividend_row(row)

    assert parsed == {
        "operate_date": date(2025, 6, 26),
        "cash_per_share": 27.673,
        "notice_date": date(2025, 4, 3),
        "pay_date": date(2025, 6, 26),
    }


def test_dividend_query_reconnects_once_when_login_expires(monkeypatch):
    attempts = []
    reconnects = []

    def fake_fetch(code, year):
        attempts.append((code, year))
        if len(attempts) == 1:
            raise RuntimeError("10001001 用户未登录")
        return [{"cash_per_share": 1}]

    monkeypatch.setattr(baostock_provider, "_fetch_dividend_unsafe", fake_fetch)
    monkeypatch.setattr(baostock_provider, "_force_relogin", lambda: reconnects.append(True))

    assert baostock_provider._fetch_dividend_with_retry_unsafe("600519.SH", "2026") == [{"cash_per_share": 1}]
    assert reconnects == [True]
    assert len(attempts) == 2


def test_refresh_dividend_yield_uses_trailing_365_days(db):
    as_of = date(2026, 5, 29)
    db.add(StockBasic(code="600519.SH", name="贵州茅台"))
    db.add(StockDaily(code="600519.SH", trade_date=as_of, close=100))
    db.add_all([
        StockDividend(code="600519.SH", operate_date=as_of - timedelta(days=20), cash_per_share=2),
        StockDividend(code="600519.SH", operate_date=as_of - timedelta(days=200), cash_per_share=3),
        StockDividend(code="600519.SH", operate_date=as_of - timedelta(days=400), cash_per_share=99),
        StockDividend(code="600519.SH", operate_date=as_of + timedelta(days=1), cash_per_share=99),
    ])
    db.commit()

    assert data_sync.refresh_dividend_yield_bs(db, as_of=as_of) == 1
    latest = db.query(StockDaily).one()
    assert latest.dividend_yield == 5.0


def test_sync_dividend_yield_bs_persists_records_and_refreshes_latest(db, monkeypatch):
    as_of = date(2026, 5, 29)
    db.add(StockBasic(code="601398.SH", name="工商银行"))
    db.add(StockBasic(code="600519.SH", name="贵州茅台"))
    db.add(StockDaily(code="601398.SH", trade_date=as_of, close=10))
    db.add(StockDaily(code="600519.SH", trade_date=as_of, close=1300))
    db.commit()

    monkeypatch.setattr(
        data_sync,
        "fetch_dividend_batch",
        lambda codes, years: {
            "601398.SH": [{
                "operate_date": date(2026, 5, 13),
                "cash_per_share": 0.1689,
                "notice_date": date(2026, 3, 28),
                "pay_date": date(2026, 5, 13),
            }],
        },
    )

    assert data_sync.sync_dividend_yield_bs(db, codes=["601398.SH", "600519.SH"], as_of=as_of) == 2
    assert db.query(StockDividend).count() == 1
    assert db.query(StockDaily).filter_by(code="601398.SH").one().dividend_yield == 1.689
    assert db.query(StockDaily).filter_by(code="600519.SH").one().dividend_yield is None
