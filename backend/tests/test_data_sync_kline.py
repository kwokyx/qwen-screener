from app.models.stock import StockBasic
from app.services import data_sync


def test_bj_single_kline_backfill_uses_akshare_path(db, monkeypatch):
    calls = []

    def should_not_call(*_args, **_kwargs):
        raise AssertionError("BJ history must not be requested from baostock")

    def fake_akshare_backfill(session, code, days):
        calls.append((session, code, days))
        return 7

    monkeypatch.setattr(data_sync, "sync_kline_bs", should_not_call)
    monkeypatch.setattr(data_sync, "backfill_kline_single", fake_akshare_backfill)

    assert data_sync.backfill_kline_single_bs(db, "920175.BJ", 120) == 7
    assert calls == [(db, "920175.BJ", 120)]


def test_full_kline_backfill_splits_bj_from_baostock_batch(db, monkeypatch):
    db.add(StockBasic(code="600036.SH", name="招商银行", market="主板"))
    db.add(StockBasic(code="000001.SZ", name="平安银行", market="主板"))
    db.add(StockBasic(code="920175.BJ", name="东方碳素", market="北交所"))
    db.commit()

    bs_batches = []
    bj_calls = []

    def fake_sync_daily_bs(session, *, codes, start_date, end_date):
        bs_batches.append((session, list(codes), start_date, end_date))
        return 2

    def fake_akshare_backfill_all(session, *, days, workers, codes):
        bj_calls.append((session, days, workers, list(codes)))
        return 1

    monkeypatch.setattr(data_sync, "sync_daily_bs", fake_sync_daily_bs)
    monkeypatch.setattr(data_sync, "backfill_kline_all", fake_akshare_backfill_all)

    assert data_sync.backfill_kline_all_bs(db, days=60) == 3
    assert len(bs_batches) == 1
    assert set(bs_batches[0][1]) == {"600036.SH", "000001.SZ"}
    assert bj_calls == [(db, 60, 6, ["920175.BJ"])]
