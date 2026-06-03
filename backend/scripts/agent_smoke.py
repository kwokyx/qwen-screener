"""Manual smoke test for the real Chat Agent SSE endpoint.

Run after Docker is up:
    python3 backend/scripts/agent_smoke.py

Optional:
    AGENT_SMOKE_BASE_URL=http://127.0.0.1:8080/api/v1 python3 backend/scripts/agent_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:8080/api/v1"
QUERIES = [
    "低估值高分红的银行股",
    "为什么这些股票排在前面",
    "按股息率排序",
    "换一批",
    "查看第一只详情",
    "帮我设计一个稳健的选股策略，先别执行",
    "现在执行",
    "你好",
    "可以，做吧",
]


def _post_sse(base_url: str, query: str, context: dict) -> list[dict]:
    body = json.dumps({"query": query, "context": context}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/screener/nl/stream",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict] = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def _context_from_events(events: list[dict]) -> dict:
    payload = next(
        event for event in reversed(events)
        if event.get("type") in {"result", "agent", "design"}
    )
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


def _terminal(events: list[dict]) -> dict:
    return next(
        event for event in reversed(events)
        if event.get("type") in {"result", "agent", "design", "error"}
    )


def main() -> int:
    base_url = os.environ.get("AGENT_SMOKE_BASE_URL", DEFAULT_BASE_URL)
    context: dict = {}
    print(f"Agent smoke endpoint: {base_url}/screener/nl/stream", flush=True)
    for query in QUERIES:
        started = time.time()
        events = _post_sse(base_url, query, context)
        terminal = _terminal(events)
        if terminal.get("type") == "error":
            print(f"FAIL {query}: {terminal.get('message')}", flush=True)
            return 1
        plan = terminal.get("plan") or {}
        event_types = [event.get("type") for event in events]
        screened = "result" in event_types
        total = terminal.get("total")
        tool = plan.get("tool")
        ai_used = plan.get("ai_used")
        elapsed = time.time() - started
        print(
            f"{query} -> tool={tool} screened={screened} ai_used={ai_used} "
            f"total={total} elapsed={elapsed:.1f}s",
            flush=True,
        )
        context = _context_from_events(events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
