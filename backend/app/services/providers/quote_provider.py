from __future__ import annotations

import os
import threading
import time

import requests
from loguru import logger


QUOTE_TTL = 8
QUOTE_FAILURE_TTL = int(os.getenv("QUOTE_FAILURE_TTL", "30"))
QUOTE_TIMEOUT = float(os.getenv("QUOTE_TIMEOUT", "0.8"))
QUOTE_CIRCUIT_FAILURES = int(os.getenv("QUOTE_CIRCUIT_FAILURES", "3"))
QUOTE_CIRCUIT_SECONDS = int(os.getenv("QUOTE_CIRCUIT_SECONDS", "60"))
_quote_cache: dict[str, tuple[float, dict | None]] = {}
_quote_lock = threading.Lock()
_quote_circuit_disabled_until = 0.0
_quote_recent_failures: list[float] = []


def _to_tx_symbol(code: str) -> str | None:
    try:
        sym, mkt = code.split(".")
    except ValueError:
        return None
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(mkt.upper())
    if not prefix:
        return None
    return f"{prefix}{sym}"


def _from_tx_symbol(symbol: str) -> str | None:
    symbol = symbol.strip().lower()
    if len(symbol) < 8:
        return None
    prefix = symbol[:2]
    code = symbol[2:]
    suffix = {"sh": "SH", "sz": "SZ", "bj": "BJ"}.get(prefix)
    if not suffix or not code.isdigit():
        return None
    return f"{code}.{suffix}"


def _num(fields: list[str], idx: int, scale: float = 1.0) -> float | None:
    if idx >= len(fields):
        return None
    raw = str(fields[idx] or "").strip()
    if not raw or raw in {"-", "--"}:
        return None
    try:
        return float(raw.replace(",", "")) / scale
    except (TypeError, ValueError):
        return None


def _parse_tx_quote(text: str) -> dict | None:
    for line in text.splitlines():
        line = line.strip()
        if not line or "=\"" not in line:
            continue
        raw_symbol = line.split("=", 1)[0].replace("v_", "", 1)
        code = _from_tx_symbol(raw_symbol)
        payload = line.split("=\"", 1)[1].rstrip("\";")
        fields = payload.split("~")
        close = _num(fields, 3)
        if not code or close is None:
            continue
        prev_close = _num(fields, 4)
        change = _num(fields, 31)
        change_pct = _num(fields, 32)
        if change is None and prev_close and close is not None:
            change = close - prev_close
        if change_pct is None and prev_close and prev_close > 0:
            change_pct = (close - prev_close) / prev_close * 100
        return {
            "code": code,
            "name": fields[1] if len(fields) > 1 and fields[1] else None,
            "close": close,
            "prev_close": prev_close,
            "open": _num(fields, 5),
            "high": _num(fields, 33),
            "low": _num(fields, 34),
            "volume": _num(fields, 36, scale=0.01),
            "amount": _num(fields, 37, scale=0.0001),
            "turnover": _num(fields, 38),
            "pe": _num(fields, 39),
            "market_cap": _num(fields, 44),
            "pb": _num(fields, 46),
            "change": change,
            "change_pct": change_pct,
            "source": "tencent",
            "quote_time": fields[30] if len(fields) > 30 and fields[30] else None,
        }
    return None


def _cache_get(code: str) -> tuple[bool, dict | None]:
    with _quote_lock:
        cached = _quote_cache.get(code)
        if not cached:
            return False, None
        expires_at, payload = cached
        if time.monotonic() >= expires_at:
            _quote_cache.pop(code, None)
            return False, None
        return True, payload


def _cache_set(code: str, payload: dict | None, ttl: int | float):
    with _quote_lock:
        _quote_cache[code] = (time.monotonic() + ttl, payload)


def _circuit_open() -> bool:
    with _quote_lock:
        return time.monotonic() < _quote_circuit_disabled_until


def _record_quote_failure():
    global _quote_circuit_disabled_until
    now = time.monotonic()
    window_start = now - 60
    with _quote_lock:
        _quote_recent_failures[:] = [ts for ts in _quote_recent_failures if ts >= window_start]
        _quote_recent_failures.append(now)
        if len(_quote_recent_failures) >= QUOTE_CIRCUIT_FAILURES:
            _quote_circuit_disabled_until = now + QUOTE_CIRCUIT_SECONDS


def _record_quote_success():
    global _quote_circuit_disabled_until
    with _quote_lock:
        _quote_recent_failures.clear()
        _quote_circuit_disabled_until = 0.0


def fetch_realtime_quote(code: str, use_cache: bool = True) -> dict | None:
    if use_cache:
        cache_hit, cached = _cache_get(code)
        if cache_hit:
            return cached

    symbol = _to_tx_symbol(code)
    if not symbol:
        return None
    if _circuit_open():
        return None

    try:
        resp = requests.get(
            "https://qt.gtimg.cn/q=" + symbol,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.qq.com/"},
            timeout=QUOTE_TIMEOUT,
        )
        resp.raise_for_status()
        quote = _parse_tx_quote(resp.text)
    except Exception as exc:
        logger.warning("[QUOTE] {} 腾讯实时行情失败: {}", code, str(exc)[:120])
        _cache_set(code, None, QUOTE_FAILURE_TTL)
        _record_quote_failure()
        return None

    if quote:
        _cache_set(code, quote, QUOTE_TTL)
        _record_quote_success()
    else:
        _cache_set(code, None, QUOTE_FAILURE_TTL)
    return quote
