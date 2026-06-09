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


def test_low_pe_filter_excludes_negative_pe_loss_makers(db, seed_stocks):
    """负 PE 表示亏损，不能被 PE<20 当作低估值股票命中。"""
    from datetime import date

    from app.models.stock import StockBasic, StockDaily

    db.add(StockBasic(code="999998.SH", name="亏损样本", industry="测试"))
    db.add(StockDaily(code="999998.SH", trade_date=date.today(), close=8, pe=-6.0, pb=1.1))
    db.commit()

    res = _screen(db, conditions=[FilterCondition(field="pe", op="lt", value=20)])
    codes = {it.code for it in res.items}

    assert "999998.SH" not in codes


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


def test_sort_pe_keeps_negative_values_after_positive_pe(db, seed_stocks):
    """按 PE 升序排序时，负 PE 亏损股排在有效正 PE 后面。"""
    from datetime import date

    from app.models.stock import StockBasic, StockDaily

    db.add(StockBasic(code="999998.SH", name="亏损样本", industry="测试"))
    db.add(StockDaily(code="999998.SH", trade_date=date.today(), close=8, pe=-6.0, pb=1.1))
    db.commit()

    result = _screen(db, conditions=[], sort_by="pe", sort_desc=False)
    codes = [item.code for item in result.items]

    assert codes.index("999998.SH") > codes.index("688981.SH")


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


def test_unknown_sort_field_raises(db, seed_stocks):
    """未知排序字段不能静默回退，避免模型参数错误被掩盖。"""
    import pytest
    with pytest.raises(ValueError, match="不支持的排序字段"):
        _screen(db, conditions=[], sort_by="not_exists")


def test_string_field_rejects_numeric_operator(db, seed_stocks):
    """行业字段仅允许字符串 eq/in。"""
    import pytest
    with pytest.raises(ValueError, match="industry 仅支持"):
        _screen(db, conditions=[FilterCondition(field="industry", op="gt", value=1)])


def test_numeric_field_rejects_string_threshold(db, seed_stocks):
    """数值字段不能接收字符串阈值。"""
    import pytest
    with pytest.raises(ValueError, match="pe 需要数字阈值"):
        _screen(db, conditions=[FilterCondition(field="pe", op="lt", value="15")])


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


def test_technical_breakout_and_volume_ratio_fields(db):
    """技术面字段基于已有日线派生：20日突破、放量倍数、均线状态、20日涨幅。"""
    from datetime import date, timedelta

    from app.models.stock import StockBasic, StockDaily

    start = date(2026, 1, 1)
    db.add(StockBasic(code="600001.SH", name="突破样本", industry="测试"))
    db.add(StockBasic(code="600002.SH", name="普通样本", industry="测试"))
    for i in range(22):
        trade_date = start + timedelta(days=i)
        db.add(StockDaily(
            code="600001.SH",
            trade_date=trade_date,
            close=25 if i == 21 else 10 + i * 0.2,
            high=25 if i == 21 else 18,
            volume=3000 if i == 21 else 1000,
        ))
        db.add(StockDaily(
            code="600002.SH",
            trade_date=trade_date,
            close=10,
            high=18,
            volume=1000,
        ))
    db.commit()

    breakout = _screen(db, conditions=[FilterCondition(field="breakout_20", op="eq", value=1)])
    volume = _screen(db, conditions=[FilterCondition(field="volume_ratio_20", op="gt", value=2)])
    trend = _screen(db, conditions=[FilterCondition(field="ma5_above_ma20", op="eq", value=1)])

    assert [item.code for item in breakout.items] == ["600001.SH"]
    assert [item.code for item in volume.items] == ["600001.SH"]
    assert [item.code for item in trend.items] == ["600001.SH"]
    assert breakout.items[0].breakout_20 == 1.0
    assert breakout.items[0].volume_ratio_20 == 3.0
    assert breakout.items[0].ma5 is not None
    assert breakout.items[0].ma20 is not None
    assert breakout.items[0].pct_change_20 is not None


def test_technical_fields_require_enough_history(db):
    """历史不足时技术字段为空，相关条件不会命中。"""
    from datetime import date, timedelta

    from app.models.stock import StockBasic, StockDaily

    start = date(2026, 1, 1)
    db.add(StockBasic(code="600003.SH", name="历史不足", industry="测试"))
    for i in range(5):
        db.add(StockDaily(
            code="600003.SH",
            trade_date=start + timedelta(days=i),
            close=20 + i,
            high=20 + i,
            volume=5000,
        ))
    db.commit()

    result = _screen(db, conditions=[FilterCondition(field="breakout_20", op="eq", value=1)])
    all_rows = _screen(db, conditions=[])

    assert result.items == []
    assert all_rows.items[0].breakout_20 is None
    assert all_rows.items[0].volume_ratio_20 is None
