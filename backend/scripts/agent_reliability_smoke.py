"""Reliability smoke for the real Chat Agent SSE endpoint.

Run after Docker services are up:
    python scripts/agent_reliability_smoke.py

Optional:
    AGENT_RELIABILITY_BASE_URL=http://127.0.0.1:8080/api/v1 python scripts/agent_reliability_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


HOST_BASE_URL = "http://127.0.0.1:8080/api/v1"
CONTAINER_BASE_URL = "http://127.0.0.1:8000/api/v1"


class SmokeFailure(Exception):
    pass


def _default_base_url() -> str:
    path = Path(__file__).resolve()
    if str(path).startswith("/app/") or Path("/.dockerenv").exists():
        return CONTAINER_BASE_URL
    return HOST_BASE_URL


def _http_json(base_url: str, path: str, *, timeout: float = 12.0) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except TimeoutError as exc:
        raise SmokeFailure(f"GET {path} timed out after {timeout:g}s") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"GET {path} failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"GET {path} returned invalid JSON") from exc


def _post_sse(base_url: str, query: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    body = json.dumps({"query": query, "context": context}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/screener/nl/stream",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if line.startswith("data: "):
                    events.append(json.loads(line.removeprefix("data: ")))
    except TimeoutError as exc:
        raise SmokeFailure(f"SSE query timed out for {query!r}") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"SSE query failed for {query!r}: {exc}") from exc
    if not events:
        raise SmokeFailure(f"SSE query returned no events for {query!r}")
    return events


def _terminal(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("type") in {"result", "agent", "design", "error"}:
            return event
    raise SmokeFailure("SSE stream had no terminal result/agent/design/error event")


def _context_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _terminal(events)
    result = None
    if payload.get("type") == "result":
        result = {
            "total": payload.get("total", 0),
            "offset": payload.get("offset", 0),
            "limit": payload.get("limit", 50),
            "trade_date": payload.get("trade_date"),
            "items": payload.get("items", [])[:8],
            "parsed_conditions": payload.get("parsed_conditions", []),
        }
    return {
        "last_plan": payload.get("plan"),
        "last_answer": payload.get("answer", ""),
        "last_conditions": payload.get("conditions") or payload.get("parsed_conditions") or [],
        "last_result": result,
        "last_tool_calls": payload.get("tool_calls", []),
        "recent_turns": [],
    }


def _conditions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    plan = payload.get("plan") or {}
    conditions = payload.get("conditions") or payload.get("parsed_conditions") or plan.get("conditions") or []
    return [item for item in conditions if isinstance(item, dict)]


def _condition_matches(
    conditions: list[dict[str, Any]],
    field: str,
    ops: set[str],
    predicate,
) -> bool:
    for cond in conditions:
        if cond.get("field") != field or cond.get("op") not in ops:
            continue
        try:
            if predicate(float(cond.get("value"))):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _event_types(events: list[dict[str, Any]]) -> list[str | None]:
    return [event.get("type") for event in events]


def _summarize(query: str, events: list[dict[str, Any]], elapsed: float) -> dict[str, Any]:
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    conditions = _conditions(terminal)
    summary = {
        "query": query,
        "terminal": terminal.get("type"),
        "tool": plan.get("tool"),
        "conditions": conditions,
        "screened": "screening" in _event_types(events),
        "result": terminal.get("type") == "result",
        "total": terminal.get("total"),
        "model_ms": terminal.get("model_ms"),
        "tool_ms": terminal.get("tool_ms"),
        "fallback_reason": terminal.get("fallback_reason") or "-",
        "elapsed_s": round(elapsed, 1),
    }
    print(json.dumps(summary, ensure_ascii=False, default=str), flush=True)
    return summary


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _require_timing(summary: dict[str, Any], label: str) -> None:
    _require(isinstance(summary.get("model_ms"), int), f"{label} missing integer model_ms")
    _require(isinstance(summary.get("tool_ms"), int), f"{label} missing integer tool_ms")
    fallback_reason = summary.get("fallback_reason")
    if fallback_reason not in (None, "-"):
        _require(
            summary.get("model_ms", 0) > 0 or fallback_reason == "local_fast_path",
            f"{label} fallback_reason={fallback_reason!r} without model_ms/local fast-path evidence",
        )


def _run_query(base_url: str, query: str, context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.time()
    events = _post_sse(base_url, query, context)
    summary = _summarize(query, events, time.time() - started)
    terminal = _terminal(events)
    if terminal.get("type") == "error":
        raise SmokeFailure(f"{query!r} returned error: {terminal.get('message')}")
    return events, summary


def _is_safe_model_stop(summary: dict[str, Any]) -> bool:
    return (
        summary.get("terminal") == "agent"
        and summary.get("tool") == "ask_clarification"
        and not summary.get("screened")
        and not summary.get("result")
        and bool(summary.get("fallback_reason") not in (None, "-"))
    )


def main() -> int:
    base_url = os.environ.get("AGENT_RELIABILITY_BASE_URL", _default_base_url())
    print(f"Agent reliability smoke endpoint: {base_url}/screener/nl/stream", flush=True)

    health = _http_json(base_url, "/health/ai")
    if health.get("configured") is not True:
        print("[WARN] AI is not configured; skip real Qwen reliability smoke", flush=True)
        return 0
    if health.get("ok") is not True:
        print(
            "[WARN] AI is configured but not healthy; skip real Qwen reliability smoke "
            f"reason={health.get('reason') or 'unknown'}",
            flush=True,
        )
        return 0
    print(f"[PASS] AI healthy latency_ms={health.get('latency_ms')}", flush=True)

    try:
        events, summary = _run_query(base_url, "ROE 大于 15 且最新季度净利润同比正增长的成长股", {})
        if _is_safe_model_stop(summary):
            print(
                "[WARN] real Qwen did not produce a valid tool call; no local screen was executed "
                f"fallback_reason={summary['fallback_reason']}",
                flush=True,
            )
            return 0
        _require(summary["terminal"] == "result", "ROE/profit query did not return result")
        _require(summary["tool"] == "stock_screen", f"ROE/profit query routed to {summary['tool']}")
        _require_timing(summary, "ROE/profit query")
        conditions = _conditions(_terminal(events))
        _require(
            _condition_matches(conditions, "roe", {"gt", "gte"}, lambda value: value >= 15),
            "ROE/profit query missing roe >= 15 condition",
        )
        _require(
            _condition_matches(conditions, "profit_yoy", {"gt", "gte"}, lambda value: value >= 0),
            "ROE/profit query missing positive profit_yoy condition",
        )
        _require(
            not any(cond.get("field") == "revenue_yoy" for cond in conditions),
            "ROE/profit query incorrectly added growth fallback revenue_yoy condition",
        )
        _require(
            not _condition_matches(conditions, "profit_yoy", {"gt", "gte"}, lambda value: value >= 20),
            "ROE/profit query incorrectly used growth fallback profit_yoy >= 20",
        )

        events, summary = _run_query(base_url, "低估值高分红的银行股", {})
        if _is_safe_model_stop(summary):
            print(
                "[WARN] real Qwen did not produce a valid tool call for follow-up screen; "
                f"fallback_reason={summary['fallback_reason']}",
                flush=True,
            )
            return 0
        _require(summary["terminal"] == "result", "bank value/dividend query did not return result")
        _require(summary["tool"] == "stock_screen", f"bank value/dividend query routed to {summary['tool']}")
        _require_timing(summary, "bank value/dividend query")
        _require(int(summary["total"] or 0) > 0, "bank value/dividend query returned no results")
        context = _context_from_events(events)

        for query, expected_tool in (
            ("为什么这些股票排在前面", "explain_result"),
            ("按股息率排序", "sort_results"),
            ("换一批", "paginate_results"),
            ("查看第一只详情", "stock_detail"),
        ):
            events, summary = _run_query(base_url, query, context)
            _require(summary["tool"] == expected_tool, f"{query!r} routed to {summary['tool']}, expected {expected_tool}")
            if expected_tool in {"explain_result", "stock_detail"}:
                _require(not summary["screened"] and not summary["result"], f"{query!r} triggered a new screen")
            if expected_tool in {"sort_results", "paginate_results"}:
                _require(not summary["screened"] and summary["result"], f"{query!r} did not return a result operation")
            if summary["terminal"] == "result":
                context = _context_from_events(events)

        events, summary = _run_query(base_url, "PE 低于 15、ROE>15%、近三年净利润复合增速>20%的消费股", {})
        terminal = _terminal(events)
        text = json.dumps(terminal, ensure_ascii=False)
        _require(not summary["screened"] and not summary["result"], "unsupported CAGR query executed a partial screen")
        _require(summary["model_ms"] == 0, "unsupported CAGR query should be blocked before model planning")
        _require(summary["fallback_reason"] == "local_fast_path", "unsupported CAGR query should use local fast path")
        _require("不支持" in text and ("复合增速" in text or "CAGR" in text), "unsupported CAGR query did not explain unsupported metric")
    except SmokeFailure as exc:
        print(f"[FAIL] {exc}", flush=True)
        return 1

    print("[PASS] agent reliability smoke complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
