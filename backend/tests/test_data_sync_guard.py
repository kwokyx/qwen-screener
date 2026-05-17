"""sync_basic 防 wipe 测试。

上游 akshare.stock_info_a_code_name 偶尔会只返回部分快照（早盘前 / 接口抖动）。
如果直接覆盖 stock_basic，会把存量 5500 只缩成几百只，再叠加随后的 industry/financial
更新，残留数据就乱了。本测试模拟"DB 已有 5000 条 / 上游只返 100 条"的情况，
验证 sync_basic 拒绝写入。
"""
import pandas as pd
import pytest

from app.models.stock import StockBasic
from app.services import data_sync


def _make_df(n: int) -> pd.DataFrame:
    """伪造 akshare.stock_info_a_code_name 的返回结构。"""
    return pd.DataFrame({
        "code": [f"{600000 + i:06d}" for i in range(n)],
        "name": [f"测试股{i}" for i in range(n)],
    })


def _seed_db(db, n: int):
    for i in range(n):
        db.add(StockBasic(code=f"{100000 + i:06d}.SH", name=f"老股{i}"))
    db.commit()


def test_sync_basic_blocks_partial_snapshot(db, monkeypatch):
    """DB 5000 条，上游只返 100 条 → 应跳过更新，不清桌子。"""
    _seed_db(db, 5000)
    assert db.query(StockBasic).count() == 5000

    fake_ak = type("ak", (), {
        "stock_info_a_code_name": staticmethod(lambda: _make_df(100)),
    })
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)

    rv = data_sync.sync_basic(db)
    assert rv == 0
    # 关键：原有 5000 条没被动
    assert db.query(StockBasic).count() == 5000


def test_sync_basic_accepts_full_snapshot(db, monkeypatch):
    """DB 5000 条，上游返 5500 条 → 正常写入。"""
    _seed_db(db, 5000)

    fake_ak = type("ak", (), {
        "stock_info_a_code_name": staticmethod(lambda: _make_df(5500)),
    })
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)

    rv = data_sync.sync_basic(db)
    assert rv > 0
    # 新代码 (600000+) 写进去了
    assert db.query(StockBasic).filter(StockBasic.code.like("600%")).count() > 0


def test_sync_basic_handles_empty_upstream(db, monkeypatch):
    """上游返 None / 空 DataFrame → skip，原数据保留。"""
    _seed_db(db, 100)

    fake_ak = type("ak", (), {
        "stock_info_a_code_name": staticmethod(lambda: pd.DataFrame()),
    })
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)

    rv = data_sync.sync_basic(db)
    assert rv == 0
    assert db.query(StockBasic).count() == 100


def test_sync_basic_empty_db_accepts_anything(db, monkeypatch):
    """空 DB 启动场景：哪怕只返 100 条也应该写进去（没有可对比的基准）。"""
    assert db.query(StockBasic).count() == 0

    fake_ak = type("ak", (), {
        "stock_info_a_code_name": staticmethod(lambda: _make_df(100)),
    })
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)

    rv = data_sync.sync_basic(db)
    assert rv == 100
    assert db.query(StockBasic).count() == 100
