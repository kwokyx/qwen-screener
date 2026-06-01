"""筛选引擎核心用例：字段筛选、行业模糊匹配、AND/OR、limit、sort。"""
from app.schemas.screener import FilterCondition, ScreenRequest
from app.services import screener_engine


def _screen(db, **kwargs):
    return screener_engine.screen(db, ScreenRequest(**kwargs))


def test_pe_filter(db, seed_stocks):
    """PE < 20 应命中招商银行(6.5)、美的(13.5)、古井(18.5) 共 3 只。"""
    res = _screen(db, conditions=[FilterCondition(field="pe", op="lt", value=20)])
    codes = {it.code for it in res.items}
    assert codes == {"600036.SH", "000333.SZ", "000596.SZ"}


def test_roe_filter(db, seed_stocks):
    """ROE > 20% 应命中茅台(28)、美的(22)、古井(24) 共 3 只。"""
    res = _screen(db, conditions=[FilterCondition(field="roe", op="gt", value=20)])
    codes = {it.code for it in res.items}
    assert codes == {"600519.SH", "000333.SZ", "000596.SZ"}


def test_industry_eq_exact(db, seed_stocks):
    """industry='银行' 精确命中招商银行。"""
    res = _screen(db, conditions=[FilterCondition(field="industry", op="eq", value="银行")])
    assert {it.code for it in res.items} == {"600036.SH"}


def test_industry_fuzzy_food_drink(db, seed_stocks):
    """industry='食品饮料' 同义词扩展到 食品 / 饮料 → 命中 古井贡酒(饮料) + 茅台(白酒包含'白酒'非'饮料')。
    SYN 对'食品饮料' = ['食品','饮料']，所以白酒不命中（白酒的同义词在'消费'里）。
    """
    res = _screen(db, conditions=[FilterCondition(field="industry", op="eq", value="食品饮料")])
    codes = {it.code for it in res.items}
    assert "000596.SZ" in codes  # 饮料 LIKE %饮料% 命中


def test_industry_consumer_synonym(db, seed_stocks):
    """industry='消费' 同义词扩展到大消费板块 → 命中白酒+饮料+家电。"""
    res = _screen(db, conditions=[FilterCondition(field="industry", op="eq", value="消费")])
    codes = {it.code for it in res.items}
    # 白酒、饮料、白色家电 都应命中
    assert "600519.SH" in codes  # 白酒
    assert "000596.SZ" in codes  # 饮料
    assert "000333.SZ" in codes  # 家电


def test_and_logic_pe_and_roe(db, seed_stocks):
    """PE<20 AND ROE>20 → 美的(13.5/22)、古井(18.5/24) 命中；招商银行 ROE 16.5 < 20 不中。"""
    res = _screen(db, conditions=[
        FilterCondition(field="pe", op="lt", value=20),
        FilterCondition(field="roe", op="gt", value=20),
    ], logic="AND")
    codes = {it.code for it in res.items}
    assert codes == {"000333.SZ", "000596.SZ"}


def test_or_logic(db, seed_stocks):
    """PE<10 OR ROE>25 → 招商(PE 6.5)、茅台(ROE 28) 共 2 只。"""
    res = _screen(db, conditions=[
        FilterCondition(field="pe", op="lt", value=10),
        FilterCondition(field="roe", op="gt", value=25),
    ], logic="OR")
    codes = {it.code for it in res.items}
    assert codes == {"600036.SH", "600519.SH"}


def test_between_op(db, seed_stocks):
    """PE 介于 [15, 25] → 茅台(24)、古井(18.5)。"""
    res = _screen(db, conditions=[
        FilterCondition(field="pe", op="between", value=[15, 25]),
    ])
    codes = {it.code for it in res.items}
    assert codes == {"600519.SH", "000596.SZ"}


def test_limit(db, seed_stocks):
    """limit=2 截断 list；total 仍是真实命中数。"""
    res = _screen(db, conditions=[FilterCondition(field="pe", op="lt", value=100)], limit=2)
    assert len(res.items) == 2
    assert res.total == 5  # 全部 5 只都满足 pe<100


def test_offset_paginates_without_changing_total(db, seed_stocks):
    """offset 只切换当前页，total 始终是完整命中数。"""
    first = _screen(db, conditions=[], sort_by="pe", sort_desc=False, offset=0, limit=2)
    second = _screen(db, conditions=[], sort_by="pe", sort_desc=False, offset=2, limit=2)

    assert first.total == second.total == 5
    assert [item.code for item in first.items] == ["600036.SH", "000333.SZ"]
    assert [item.code for item in second.items] == ["000596.SZ", "600519.SH"]


def test_sort_desc(db, seed_stocks):
    """按 roe desc 排序：茅台(28) > 古井(24) > 美的(22) > 招商(16.5) > 中芯(8)。"""
    res = _screen(db, conditions=[FilterCondition(field="pe", op="lt", value=100)],
                  sort_by="roe", sort_desc=True, limit=3)
    codes = [it.code for it in res.items]
    assert codes == ["600519.SH", "000596.SZ", "000333.SZ"]


def test_sort_keeps_null_values_last(db, seed_stocks):
    """升序和降序都将空值放在最后，避免缺失数据占据列表前排。"""
    from datetime import date

    from app.models.stock import StockBasic, StockDaily

    db.add(StockBasic(code="999999.SH", name="缺失估值", industry="测试"))
    db.add(StockDaily(code="999999.SH", trade_date=date.today(), close=12, pe=None))
    db.commit()

    asc_result = _screen(db, conditions=[], sort_by="pe", sort_desc=False)
    desc_result = _screen(db, conditions=[], sort_by="pe", sort_desc=True)

    assert asc_result.items[-1].code == "999999.SH"
    assert desc_result.items[-1].code == "999999.SH"


def test_sort_change_pct_uses_server_expression(db, seed_stocks):
    """涨跌幅排序由后端根据最新价和前收计算，而不是只排序当前页。"""
    from app.models.stock import StockDaily

    latest = (
        db.query(StockDaily)
        .filter(StockDaily.code == "600036.SH")
        .order_by(StockDaily.trade_date.desc())
        .first()
    )
    latest.close = 12
    db.commit()

    result = _screen(db, conditions=[], sort_by="change_pct", sort_desc=True)

    assert result.items[0].code == "600036.SH"
    assert result.items[0].change_pct == 20.0


def test_sort_score_uses_server_expression(db, seed_stocks):
    """综合分由后端计算并支持全量排序，分页前就已经稳定排序。"""
    result = _screen(db, conditions=[], sort_by="score", sort_desc=True, limit=5)

    assert all(item.score is not None for item in result.items)
    assert result.items[0].code == "600036.SH"
    assert [item.score for item in result.items] == sorted(
        [item.score for item in result.items],
        reverse=True,
    )


def test_sort_uses_code_as_stable_tiebreaker(db, seed_stocks):
    """排序值相同时按代码升序兜底，保证翻页结果稳定。"""
    result = _screen(db, conditions=[], sort_by="close", sort_desc=True)

    assert [item.code for item in result.items] == sorted(item.code for item in result.items)


def test_unknown_field_raises(db, seed_stocks):
    """未知字段抛 ValueError，调用方转 HTTP 400。"""
    import pytest
    with pytest.raises(ValueError, match="不支持的筛选字段"):
        _screen(db, conditions=[FilterCondition(field="bogus", op="eq", value=1)])


def test_result_includes_latest_data_context(db, seed_stocks):
    """结果携带最新交易日、上一日收盘和可展示字段，前端不用再猜数据时间。"""
    res = _screen(db, conditions=[FilterCondition(field="industry", op="eq", value="银行")])
    item = res.items[0]
    assert item.code == "600036.SH"
    assert item.trade_date is not None
    assert item.close == 11.0
    assert item.prev_close == 10.0
    assert item.change_pct == 10.0
    assert item.pe == 6.5
    assert item.roe == 16.5
    assert res.trade_date == item.trade_date


def test_result_change_pct_is_none_without_previous_close(db):
    """只有一条日线时，涨跌幅保持为空，不补假数据。"""
    from datetime import date

    from app.models.stock import StockBasic, StockDaily

    db.add(StockBasic(code="999999.SH", name="新股", industry="测试"))
    db.add(StockDaily(code="999999.SH", trade_date=date.today(), close=50))
    db.commit()

    item = _screen(db, conditions=[FilterCondition(field="industry", op="eq", value="测试")]).items[0]

    assert item.prev_close is None
    assert item.change_pct is None
