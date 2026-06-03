"""P0 release smoke for the Qwen/OpenCode Go demo.

Run after Docker services are up:
    python3 backend/scripts/release_smoke.py

Optional:
    RELEASE_SMOKE_BASE_URL=http://127.0.0.1:8080/api/v1 python3 backend/scripts/release_smoke.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8080/api/v1"
SECRET_PATTERN = "|".join([
    "sk-" + "dm" + "ghh",
    "OPENAI_API_KEY=" + "sk-",
    "DASHSCOPE_API_KEY=" + "sk-",
    "OPENAI_API_KEY=.*" + "dm" + "ghh",
])
SECRET_SCAN_TARGETS = [
    "backend/app",
    "backend/tests",
    "backend/scripts",
    "frontend/src",
    "docker-compose.yml",
    "README.md",
    "docs",
    "backend/.env.example",
]


class SmokeFailure(Exception):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _http_json(base_url: str, path: str, *, timeout: float = 20.0) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except TimeoutError as exc:
        raise SmokeFailure(f"GET {path} timed out after {timeout:.0f}s") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"GET {path} failed: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"GET {path} returned non-JSON body: {body[:200]}") from exc


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


def _event_types(events: list[dict[str, Any]]) -> list[str | None]:
    return [event.get("type") for event in events]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _pass(name: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"[PASS] {name}{suffix}", flush=True)


def _warn(name: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"[WARN] {name}{suffix}", flush=True)


def _check_compose(cwd: Path) -> None:
    proc = _run(["docker", "compose", "ps"], cwd=cwd)
    if proc.returncode != 0:
        raise SmokeFailure(f"docker compose ps failed:\n{proc.stdout}")
    output = proc.stdout
    for service in ("qwen-backend", "qwen-frontend"):
        _require(service in output, f"{service} missing from docker compose ps output")
    _require("healthy" in output.lower(), "docker compose ps does not show healthy services")
    _pass("docker compose ps", "backend/frontend listed and healthy")


def _check_health(base_url: str) -> None:
    ai = _http_json(base_url, "/health/ai")
    _require(ai.get("configured") is True, "/health/ai reports AI is not configured")
    _require(ai.get("backend") == "openai", f"/health/ai backend is {ai.get('backend')!r}, expected openai")
    _require(ai.get("model") == "qwen3.6-plus", f"/health/ai model is {ai.get('model')!r}")
    if ai.get("ok") is True:
        _pass("health/ai", f"ok=true latency_ms={ai.get('latency_ms')}")
    else:
        _warn("health/ai", f"configured=true fallback=true reason={ai.get('reason') or 'unknown'}")

    data = _http_json(base_url, "/health/data")
    _require(data.get("fresh") is True, f"/health/data fresh=false: {data.get('freshness', {}).get('message')}")
    _require(data.get("expected_trade_date") == data.get("latest_trade_date"), "/health/data latest date is behind expected date")
    _pass(
        "health/data",
        f"fresh=true latest={data.get('latest_trade_date')} warnings={len(data.get('sync_warnings') or [])}",
    )


def _check_fast_path(base_url: str) -> None:
    events = _post_sse(base_url, "你好", {})
    types = _event_types(events)
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    _require(plan.get("tool") == "ask_clarification", f"你好 routed to {plan.get('tool')}")
    _require(terminal.get("model_ms") == 0, f"你好 model_ms={terminal.get('model_ms')}, expected 0")
    _require(terminal.get("fallback_reason") == "local_fast_path", f"你好 fallback_reason={terminal.get('fallback_reason')!r}")
    _require("screening" not in types and "result" not in types, "你好 triggered screening/result events")
    _require("done" in types, "你好 stream did not emit done")
    _pass("SSE fast-path", "你好 -> ask_clarification, model_ms=0")


def _check_detail(base_url: str) -> None:
    context = {
        "last_result": {
            "total": 1,
            "items": [{"code": "600036.SH", "name": "招商银行"}],
            "parsed_conditions": [{"field": "pe", "op": "lt", "value": 15}],
        }
    }
    events = _post_sse(base_url, "查看第一只详情", context)
    types = _event_types(events)
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    _require(plan.get("tool") == "stock_detail", f"detail routed to {plan.get('tool')}")
    _require("screening" not in types and "result" not in types, "stock_detail triggered screening/result events")
    calls = terminal.get("tool_calls") or []
    detail_call = next((call for call in calls if call.get("name") == "stock_detail"), None)
    _require(bool(detail_call), "stock_detail call missing")
    _require(detail_call.get("result", {}).get("url") == "/detail/600036.SH", "stock_detail url mismatch")
    _pass("SSE stock_detail", "查看第一只详情 -> /detail/600036.SH")


def _check_real_screen(base_url: str) -> dict[str, Any]:
    started = time.time()
    events = _post_sse(base_url, "低估值高分红的银行股", {})
    elapsed = time.time() - started
    types = _event_types(events)
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    _require(terminal.get("type") == "result", f"screen terminal type is {terminal.get('type')}")
    _require(plan.get("tool") == "stock_screen", f"screen routed to {plan.get('tool')}")
    _require("screening" in types and "result" in types and "done" in types, "screen stream missing screening/result/done")
    _require(int(terminal.get("total") or 0) > 0, "screen result total is 0")
    _require(isinstance(terminal.get("model_ms"), int), "screen result missing model_ms")
    _require(isinstance(terminal.get("tool_ms"), int), "screen result missing tool_ms")
    _pass(
        "SSE real screen",
        f"total={terminal.get('total')} model_ms={terminal.get('model_ms')} "
        f"tool_ms={terminal.get('tool_ms')} fallback_reason={terminal.get('fallback_reason') or '-'} "
        f"elapsed={elapsed:.1f}s",
    )
    return _context_from_events(events)


def _check_secret_scan(cwd: Path) -> None:
    proc = _run(["rg", "-n", SECRET_PATTERN, *SECRET_SCAN_TARGETS], cwd=cwd)
    if proc.returncode == 0:
        raise SmokeFailure(f"targeted secret scan found matches:\n{proc.stdout}")
    if proc.returncode not in (0, 1):
        raise SmokeFailure(f"targeted secret scan failed:\n{proc.stdout}")
    _pass("targeted secret scan", "no matches")


def main() -> int:
    cwd = _repo_root()
    base_url = os.environ.get("RELEASE_SMOKE_BASE_URL", DEFAULT_BASE_URL)
    print(f"Release smoke base URL: {base_url}", flush=True)
    checks = [
        lambda: _check_compose(cwd),
        lambda: _check_health(base_url),
        lambda: _check_fast_path(base_url),
        lambda: _check_detail(base_url),
        lambda: _check_real_screen(base_url),
        lambda: _check_secret_scan(cwd),
    ]
    for check in checks:
        try:
            check()
        except SmokeFailure as exc:
            print(f"[FAIL] {exc}", flush=True)
            return 1
    print("[PASS] release smoke complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
