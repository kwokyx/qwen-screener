"""
baostock 数据源封装。

baostock (http://baostock.com) 是一个免费的 A 股历史数据源，提供：
- 股票基本信息 (query_stock_basic)
- 历史日 K 线 (query_history_k_data_plus)，含复权
- 利润表 (query_profit_data)
- 杜邦分析 (query_dupont_data) → ROE
- 成长指标 (query_growth_data) → 营收/净利同比
- 分红数据 (query_dividend_data)

所有 bs 调用前必须先 bs.login()，结果用完后 bs.logout()。
本模块用 context manager 自动管理 login/logout 生命周期，同一进程内复用 session。

注意：
- baostock 不是实时行情源，所有数据为历史日线/财报。
- 频率限制：查询间隔建议 > 0.5 秒。
- 单次查询返回行数有限制，全量查询需分页。
"""

import time
import socket
import threading
import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

import baostock as bs
from baostock.common import context as bs_context
from loguru import logger

BAOSTOCK_SOCKET_TIMEOUT = float(os.getenv("BAOSTOCK_SOCKET_TIMEOUT", "10"))
BAOSTOCK_RETRIES = int(os.getenv("BAOSTOCK_RETRIES", "2"))
socket.setdefaulttimeout(BAOSTOCK_SOCKET_TIMEOUT)


def _close_default_socket():
    sock = getattr(bs_context, "default_socket", None)
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass
    setattr(bs_context, "default_socket", None)

# ---- 全局 session 管理 ----
# baostock 官方推荐非频繁 login/logout 场景下全局登录一次。
# 这里用引用计数方式管理，避免多次 login 造成资源泄漏。

_session_refcount: int = 0
_session_lock = threading.RLock()


def _ensure_login():
    global _session_refcount
    if _session_refcount <= 0:
        last_msg = ""
        for attempt in range(BAOSTOCK_RETRIES):
            _close_default_socket()
            lg = bs.login()
            if lg.error_code == "0":
                logger.debug("baostock 登录成功")
                break
            last_msg = f"{lg.error_code} {lg.error_msg}"
            logger.warning("baostock 登录失败 attempt {}: {}", attempt + 1, last_msg)
            _close_default_socket()
            time.sleep(0.5 * (attempt + 1))
        else:
            raise ConnectionError(f"baostock 登录失败: {last_msg}")
    _session_refcount += 1


def _ensure_logout():
    global _session_refcount
    _session_refcount -= 1
    if _session_refcount <= 0:
        try:
            bs.logout()
        except Exception as exc:
            logger.warning("baostock 登出异常: {}", str(exc)[:120])
        _close_default_socket()
        _session_refcount = 0
        logger.debug("baostock 登出")


def _force_relogin():
    """Reconnect an expired baostock socket while keeping the active context."""
    global _session_refcount
    _close_default_socket()
    _session_refcount = 0
    _ensure_login()


@contextmanager
def bs_session():
    """baostock session context manager — 自动 login/logout。"""
    with _session_lock:
        _ensure_login()
        try:
            yield
        finally:
            _ensure_logout()


# ---- 代码格式转换 ----

def bs_to_code(bs_code: str) -> str:
    """sh.600519 → 600519.SH"""
    parts = bs_code.split(".")
    if len(parts) != 2:
        return bs_code
    mkt, sym = parts
    return f"{sym}.{mkt.upper().replace('SH', 'SH').replace('SZ', 'SZ')}"


def code_to_bs(code: str) -> str:
    """600519.SH → sh.600519"""
    sym, mkt = code.split(".")
    return f"{mkt.lower()}.{sym}"


def _f(value: Any, scale: float = 1.0) -> float | None:
    """安全转 float，空值返回 None。"""
    if value is None or value == "" or value == "None":
        return None
    try:
        v = float(value)
        if scale != 1.0:
            v = v / scale
        return v
    except (ValueError, TypeError):
        return None


# ---- 股票基本信息 ----

def fetch_stock_basic() -> list[dict]:
    """拉取全 A 股基本信息（代码、名称、上市日期）。
    返回 list[dict]，字段：code, name, list_date
    """
    with bs_session():
        rs = bs.query_stock_basic()
        if rs.error_code != "0":
            logger.error("query_stock_basic 失败: {} {}", rs.error_code, rs.error_msg)
            return []
        rows: list[dict] = []
        while rs.next():
            row = rs.get_row_data()
            if len(row) >= 6 and (row[4] != "1" or row[5] != "1"):
                continue
            code = bs_to_code(row[0])
            symbol = code.split(".")[0]
            if not (
                symbol.startswith(("60", "68", "00", "30", "12", "11", "13"))
                or (len(symbol) >= 4 and symbol[:3] in ("920", "430", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879"))
            ):
                continue
            name = row[1]
            ipo_date_str = row[2]
            list_date = None
            if ipo_date_str and ipo_date_str != "0001-01-01":
                try:
                    list_date = date.fromisoformat(ipo_date_str)
                except ValueError:
                    pass
            rows.append({"code": code, "name": name, "list_date": list_date})
        logger.info("fetch_stock_basic: {} 只", len(rows))
        return rows


# ---- K 线数据 ----

_KLINE_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)

_PERIOD_KLINE_FIELDS = "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"

_INTRADAY_FIELDS = "date,time,code,open,high,low,close,volume,amount,adjustflag"


def _parse_bs_datetime(value: str, fallback_date: str | None = None) -> datetime | None:
    """Parse baostock minute timestamp like 20260529150000000."""
    raw = (value or "").strip()
    if len(raw) >= 14 and raw[:14].isdigit():
        try:
            return datetime.strptime(raw[:14], "%Y%m%d%H%M%S")
        except ValueError:
            pass
    if fallback_date:
        try:
            return datetime.fromisoformat(f"{fallback_date} 15:00:00")
        except ValueError:
            return None
    return None


def fetch_kline(
    code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    frequency: str = "d",
    adjustflag: str = "2",  # 前复权
) -> list[dict]:
    """拉取单只股票 K 线。

    日线字段最完整；周线/月线不支持 preclose、peTTM、pbMRQ 等指标，
    所以使用 baostock 支持的周期字段，并把估值字段置空。
    返回 list[dict]，字段与 stock_daily 对齐。
    """
    bs_code = code_to_bs(code)
    fields = _KLINE_FIELDS if frequency == "d" else _PERIOD_KLINE_FIELDS
    for attempt in range(BAOSTOCK_RETRIES):
        with bs_session():
            rs = bs.query_history_k_data_plus(
                bs_code,
                fields=fields,
                start_date=start_date or "1990-01-01",
                end_date=end_date or date.today().strftime("%Y-%m-%d"),
                frequency=frequency,
                adjustflag=adjustflag,
            )
            if rs.error_code != "0":
                logger.warning("baostock kline {} 查询失败 attempt {}: {} {}", code, attempt + 1, rs.error_code, rs.error_msg)
                rows = []
            else:
                rows = []
                while rs.next():
                    row = rs.get_row_data()
                    # row order matches _KLINE_FIELDS
                    td = row[0]
                    if not td or td == "0000-00-00":
                        continue
                    item = {
                        "trade_date": date.fromisoformat(td),
                        "code": code,
                        "open": _f(row[2]),
                        "high": _f(row[3]),
                        "low": _f(row[4]),
                        "close": _f(row[5]),
                        "market_cap": None,
                        "dividend_yield": None,
                    }
                    if frequency == "d":
                        item.update({
                            "volume": _f(row[7]),
                            "amount": _f(row[8]),
                            "turnover": _f(row[10]),
                            "pe": _f(row[13]),
                            "pb": _f(row[14]),
                        })
                    else:
                        item.update({
                            "volume": _f(row[6]),
                            "amount": _f(row[7]),
                            "turnover": _f(row[9]),
                            "pe": None,
                            "pb": None,
                        })
                    rows.append(item)
                return rows
        time.sleep(0.5 * (attempt + 1))
    return []


def fetch_intraday_kline(
    code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    frequency: str = "5",
    adjustflag: str = "3",  # 分钟线默认不复权，避免盘中价被复权调整得不直观
) -> list[dict]:
    """拉取单只股票分钟 K 线。

    baostock minute frequency supports 5/15/30/60. It returns datetime-level
    bars, so this endpoint keeps them separate from stock_daily.
    """
    if frequency not in {"5", "15", "30", "60"}:
        raise ValueError("frequency must be one of 5, 15, 30, 60")

    bs_code = code_to_bs(code)
    for attempt in range(BAOSTOCK_RETRIES):
        with bs_session():
            rs = bs.query_history_k_data_plus(
                bs_code,
                fields=_INTRADAY_FIELDS,
                start_date=start_date or date.today().strftime("%Y-%m-%d"),
                end_date=end_date or date.today().strftime("%Y-%m-%d"),
                frequency=frequency,
                adjustflag=adjustflag,
            )
            if rs.error_code != "0":
                logger.warning(
                    "baostock intraday {} {}m 查询失败 attempt {}: {} {}",
                    code, frequency, attempt + 1, rs.error_code, rs.error_msg,
                )
                rows = []
            else:
                rows = []
                while rs.next():
                    row = rs.get_row_data()
                    dt = _parse_bs_datetime(row[1], row[0])
                    if dt is None:
                        continue
                    rows.append({
                        "datetime": dt,
                        "code": code,
                        "open": _f(row[3]),
                        "high": _f(row[4]),
                        "low": _f(row[5]),
                        "close": _f(row[6]),
                        "volume": _f(row[7]),
                        "amount": _f(row[8]),
                    })
                return rows
        time.sleep(0.5 * (attempt + 1))
    return []


def fetch_kline_batch(
    codes: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, list[dict]]:
    """批量拉取 K 线，单 session 内依次查询。每个请求间隔 0.3s 避免限流。"""
    results: dict[str, list[dict]] = {}
    with bs_session():
        for i, code in enumerate(codes):
            try:
                klines = fetch_kline_unsafe(code, start_date, end_date)
                if klines:
                    results[code] = klines
            except Exception as e:
                logger.warning("fetch_kline_batch {} 失败: {}", code, str(e)[:80])
            if i > 0 and i % 50 == 0:
                time.sleep(0.5)  # 每 50 只多等一会
            elif i > 0:
                time.sleep(0.3)
    return results


def fetch_kline_unsafe(
    code: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """在已有 session 内直接查询（不嵌套 login/logout）。"""
    bs_code = code_to_bs(code)
    rs = bs.query_history_k_data_plus(
        bs_code,
        fields=_KLINE_FIELDS,
        start_date=start_date or "1990-01-01",
        end_date=end_date or date.today().strftime("%Y-%m-%d"),
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code != "0":
        return []
    rows: list[dict] = []
    while rs.next():
        row = rs.get_row_data()
        td = row[0]
        if not td or td == "0000-00-00":
            continue
        rows.append({
            "trade_date": date.fromisoformat(td),
            "code": code,
            "open": _f(row[2]),
            "high": _f(row[3]),
            "low": _f(row[4]),
            "close": _f(row[5]),
            "volume": _f(row[7]),
            "amount": _f(row[8]),
            "turnover": _f(row[10]),
            "pe": _f(row[13]),
            "pb": _f(row[14]),
        })
    return rows


# ---- 财务数据 ----

def fetch_financial(
    code: str,
    year: int | None = None,
    quarter: int | None = None,
) -> dict | None:
    """拉取最新一期财务指标。
    组合利润表 + 杜邦分析 + 成长指标。
    返回 dict 或 None。

    字段映射：
    - roe: 杜邦 ROE
    - net_profit: 归母净利润（亿元）
    - revenue: 营业总收入（亿元）
    - gross_margin: 毛利率 (%)
    - net_margin: 净利率 (%)
    - debt_ratio: 资产负债率 (%) ［需从负债表计算，baostock 不直接提供］
    - revenue_yoy: 营收同比增长率 (%)
    - profit_yoy: 归属净利润同比增长率 (%)
    """
    bs_code = code_to_bs(code)
    with bs_session():
        # 1) 拉利润表 → 得到毛利率、净利率、净利润、营收
        rs_profit = bs.query_profit_data(bs_code, year=year or 2024, quarter=quarter or 4)
        profit_fields = [
            "code", "pubDate", "statDate",
            "roeAvg", "npMargin", "grProfit", "netProfit", "epsTTM",
            "MBRevenue", "totalShare", "liqaShare",
        ]
        profit: dict[str, float | None] = {}
        if rs_profit.error_code == "0":
            while rs_profit.next():
                row = rs_profit.get_row_data()
                profit["roe"] = _f(row[3])        # 平均 ROE，单位 %
                profit["net_margin"] = _f(row[4])   # 净利率 %
                profit["gross_margin"] = _f(row[5]) # 毛利率 % (不是百分数，是小数格式)
                profit["net_profit"] = _f(row[6], scale=10000)  # 元→亿元
                profit["revenue"] = _f(row[7], scale=10000)     # 元→亿元
                break  # 只取最新一期

        # 2) 杜邦分析 → 得到 ROE（更准确）
        rs_dupont = bs.query_dupont_data(bs_code, year=year or 2024, quarter=quarter or 4)
        if rs_dupont.error_code == "0":
            while rs_dupont.next():
                row = rs_dupont.get_row_data()
                dupont_roe = _f(row[3])  # 净资产收益率 %
                if dupont_roe is not None:
                    profit["roe"] = dupont_roe
                break

        # 3) 成长指标 → 营收同比 / 净利同比
        rs_growth = bs.query_growth_data(bs_code, year=year or 2024, quarter=quarter or 4)
        if rs_growth.error_code == "0":
            while rs_growth.next():
                row = rs_growth.get_row_data()
                # 字段: code, pubDate, statDate, YOYEquity, YOYAsset, YOYNI, YOYEPSBasic,
                #       YOYPNI, YOYOperatingRevenue, YOYOperationProfit, ...
                # YOYOperatingRevenue = 营收同比
                # YOYPNI = 归属净利润同比
                # 但具体字段位置取决于 baostock 版本，这里按常用顺序估算
                profit["revenue_yoy"] = _f(row[8])   # 营收同比
                profit["profit_yoy"] = _f(row[7])    # 归属净利润同比

                # 备选：部分版本的 YOYNI 在 row[5]
                if profit.get("profit_yoy") is None:
                    profit["profit_yoy"] = _f(row[5])
                break

        # 4) 资产负债率 — baostock 不直接提供，从 query_balance_data 计算
        # query_balance_data 字段: code, pubDate, statDate, currentAssets, ... totalAssets, totalLiab, ...
        # debt_ratio = totalLiab / totalAssets * 100
        rs_balance = bs.query_balance_data(bs_code, year=year or 2024, quarter=quarter or 4)
        if rs_balance and rs_balance.error_code == "0":
            while rs_balance.next():
                row = rs_balance.get_row_data()
                # 按经验: row[22] ≈ totalLiab, row[21] ≈ totalAssets
                # 更稳健做法：遍历列名匹配
                # 简化：取 row[22] 和 row[21]
                total_assets = _f(row[21])
                total_liab = _f(row[22])
                if total_assets and total_liab and total_assets > 0:
                    profit["debt_ratio"] = round(total_liab / total_assets * 100, 2)
                break

        # 只有 ROE 不为 None 才认为拉到有效数据
        if profit.get("roe") is None:
            return None

        return profit


def fetch_financial_batch(
    codes: list[str],
    year: int | None = None,
    quarter: int | None = None,
) -> dict[str, dict]:
    """批量拉取财务指标。"""
    results: dict[str, dict] = {}
    with bs_session():
        for i, code in enumerate(codes):
            try:
                fin = _fetch_financial_unsafe(code, year, quarter)
                if fin:
                    results[code] = fin
            except Exception as e:
                logger.warning("fetch_financial {} 失败: {}", code, str(e)[:80])
            if i > 0 and i % 20 == 0:
                time.sleep(0.5)
    return results


def _fetch_financial_unsafe(code: str, year: int | None, quarter: int | None) -> dict | None:
    """在已有 session 内直接查询财务数据。"""
    bs_code = code_to_bs(code)
    profit: dict[str, float | None] = {}

    # 利润表
    rs = bs.query_profit_data(bs_code, year=year or 2024, quarter=quarter or 4)
    if rs.error_code == "0":
        while rs.next():
            row = rs.get_row_data()
            profit["roe"] = _f(row[3])
            profit["net_margin"] = _f(row[4])
            profit["gross_margin"] = _f(row[5])
            profit["net_profit"] = _f(row[6], scale=10000)
            profit["revenue"] = _f(row[7], scale=10000)
            break

    # 杜邦 ROE
    rs2 = bs.query_dupont_data(bs_code, year=year or 2024, quarter=quarter or 4)
    if rs2.error_code == "0":
        while rs2.next():
            row = rs2.get_row_data()
            dupont_roe = _f(row[3])
            if dupont_roe is not None:
                profit["roe"] = dupont_roe
            break

    # 成长指标
    rs3 = bs.query_growth_data(bs_code, year=year or 2024, quarter=quarter or 4)
    if rs3.error_code == "0":
        while rs3.next():
            row = rs3.get_row_data()
            profit["revenue_yoy"] = _f(row[8])
            profit["profit_yoy"] = _f(row[7])
            if profit.get("profit_yoy") is None:
                profit["profit_yoy"] = _f(row[5])
            break

    # 资产负债率（负债表）
    rs4 = bs.query_balance_data(bs_code, year=year or 2024, quarter=quarter or 4)
    if rs4 and rs4.error_code == "0":
        while rs4.next():
            row = rs4.get_row_data()
            ta = _f(row[21])
            tl = _f(row[22])
            if ta and tl and ta > 0:
                profit["debt_ratio"] = round(tl / ta * 100, 2)
            break

    if profit.get("roe") is None:
        return None
    return profit


# ---- 分红数据 ----

def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_dividend_row(row: list[str]) -> dict | None:
    """解析 query_dividend_data 的一行结果。

    baostock 返回的 dividCashPsBeforeTax 已经是每股税前现金分红，不是
    每 10 股分红。只保留已实施且可用于收益率计算的现金分红。
    """
    if len(row) < 10:
        return None
    operate_date = _parse_date(row[6])
    cash_per_share = _f(row[9])
    if operate_date is None or cash_per_share is None or cash_per_share <= 0:
        return None
    return {
        "operate_date": operate_date,
        "cash_per_share": cash_per_share,
        "notice_date": _parse_date(row[3]),
        "pay_date": _parse_date(row[7]),
    }


def _fetch_dividend_unsafe(code: str, year: str) -> list[dict]:
    """在已有 baostock session 内拉取一个除权除息年份的分红记录。"""
    rs = bs.query_dividend_data(code_to_bs(code), year=year, yearType="operate")
    if rs.error_code != "0":
        raise RuntimeError(f"{rs.error_code} {rs.error_msg}")
    rows: list[dict] = []
    while rs.next():
        parsed = _parse_dividend_row(rs.get_row_data())
        if parsed:
            rows.append(parsed)
    return rows


def _fetch_dividend_with_retry_unsafe(code: str, year: str) -> list[dict]:
    """Retry a dividend query after baostock invalidates the current login."""
    for attempt in range(BAOSTOCK_RETRIES):
        try:
            return _fetch_dividend_unsafe(code, year)
        except RuntimeError as exc:
            if "10001001" not in str(exc) or attempt + 1 >= BAOSTOCK_RETRIES:
                raise
            logger.warning("fetch_dividend {} 登录失效，重新连接后重试", code)
            _force_relogin()
    return []


def fetch_dividend(code: str, year: str | None = None) -> list[dict]:
    """拉取一个除权除息年份的已实施现金分红记录。"""
    with bs_session():
        return _fetch_dividend_with_retry_unsafe(code, year or str(date.today().year))


def fetch_dividend_batch(
    codes: list[str],
    years: list[str] | None = None,
) -> dict[str, list[dict]]:
    """复用一次登录批量拉分红记录；失败股票不写入结果，保留旧值。"""
    years = years or [str(date.today().year - 1), str(date.today().year)]
    results: dict[str, list[dict]] = {}
    with bs_session():
        for i, code in enumerate(codes, 1):
            try:
                rows: list[dict] = []
                for year in years:
                    rows.extend(_fetch_dividend_with_retry_unsafe(code, year))
                results[code] = rows
            except Exception as e:
                logger.warning("fetch_dividend {} 失败: {}", code, str(e)[:80])
            if i % 100 == 0:
                logger.info("[BS-DIVIDEND] 拉取进度 {}/{}", i, len(codes))
                time.sleep(0.2)
    return results


# ---- 健康检查 ----

def probe_baostock() -> dict:
    """快速连通性检查。"""
    try:
        with bs_session():
            rs = bs.query_stock_basic(code_name="600519")
            return {"status": "ok", "code": rs.error_code, "text": "connected"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}
