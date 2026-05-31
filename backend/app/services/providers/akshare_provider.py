"""AKShare provider helpers used as fallback/fast market data source."""

from datetime import datetime
import time
from typing import Any

from loguru import logger


def _f(value: Any, scale: float = 1.0) -> float | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
        return float(value) / scale
    except Exception:
        return None


def _symbol(code: str) -> str:
    return code.split(".")[0]


def _prefixed_symbol(code: str) -> str:
    sym, market = code.split(".")
    return f"{market.lower()}{sym}"


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def fetch_intraday_kline_em(
    code: str,
    start_datetime: str,
    end_datetime: str,
    frequency: str = "5",
    adjust: str = "",
) -> list[dict]:
    """Fetch A-share minute K-line from Eastmoney via AKShare.

    frequency supports 1/5/15/30/60 in AKShare. The UI currently exposes
    5/15/30/60.
    """
    if frequency not in {"1", "5", "15", "30", "60"}:
        raise ValueError("frequency must be one of 1, 5, 15, 30, 60")

    rows = _fetch_intraday_minute(code, start_datetime, end_datetime, frequency, adjust)
    if rows:
        return rows
    return _fetch_intraday_hist_min_em(code, start_datetime, end_datetime, frequency, adjust)


def _fetch_intraday_hist_min_em(
    code: str,
    start_datetime: str,
    end_datetime: str,
    frequency: str,
    adjust: str,
) -> list[dict]:
    import akshare as ak

    last_error: Exception | None = None
    df = None
    for attempt in range(2):
        try:
            df = ak.stock_zh_a_hist_min_em(
                symbol=_symbol(code),
                start_date=start_datetime,
                end_date=end_datetime,
                period=frequency,
                adjust=adjust,
            )
            break
        except Exception as exc:
            last_error = exc
            logger.warning("[AK-INTRADAY-EM] {} {}m attempt {} 失败: {}", code, frequency, attempt + 1, str(exc)[:120])
            time.sleep(0.4 * (attempt + 1))
    if df is None:
        if last_error is not None:
            logger.warning("[AK-INTRADAY-EM] {} {}m fallback required: {}", code, frequency, str(last_error)[:120])
        return []
    if df is None or df.empty:
        logger.warning("[AK-INTRADAY] {} {}m 返回 0 行", code, frequency)
        return []

    rows: list[dict] = []
    for _, r in df.iterrows():
        dt = _parse_dt(r.get("时间"))
        if dt is None:
            continue
        rows.append({
            "datetime": dt,
            "code": code,
            "open": _f(r.get("开盘")),
            "high": _f(r.get("最高")),
            "low": _f(r.get("最低")),
            "close": _f(r.get("收盘")),
            # Eastmoney minute volume is in hands; convert to shares.
            "volume": _f(r.get("成交量"), scale=0.01),
            "amount": _f(r.get("成交额"), scale=10000),
        })
    return rows


def _fetch_intraday_minute(
    code: str,
    start_datetime: str,
    end_datetime: str,
    frequency: str,
    adjust: str,
) -> list[dict]:
    import akshare as ak

    start = datetime.fromisoformat(start_datetime)
    end = datetime.fromisoformat(end_datetime)
    df = ak.stock_zh_a_minute(
        symbol=_prefixed_symbol(code),
        period=frequency,
        adjust=adjust,
    )
    if df is None or df.empty:
        logger.warning("[AK-INTRADAY-MINUTE] {} {}m 返回 0 行", code, frequency)
        return []

    rows: list[dict] = []
    for _, r in df.iterrows():
        dt = _parse_dt(r.get("day"))
        if dt is None or dt < start or dt > end:
            continue
        rows.append({
            "datetime": dt,
            "code": code,
            "open": _f(r.get("open")),
            "high": _f(r.get("high")),
            "low": _f(r.get("low")),
            "close": _f(r.get("close")),
            "volume": _f(r.get("volume")),
            "amount": _f(r.get("amount"), scale=10000),
        })
    return rows
