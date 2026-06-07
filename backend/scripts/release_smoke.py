"""P0 release smoke for the Qwen/OpenCode Go demo.

Run after Docker services are up:
    python3 backend/scripts/release_smoke.py

Optional:
    RELEASE_SMOKE_BASE_URL=http://127.0.0.1:8080/api/v1 python3 backend/scripts/release_smoke.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
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


STATS = {"pass": 0, "warn": 0, "fail": 0}
WARNINGS: list[str] = []


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in (current.parent, *current.parents):
        if (parent / "docker-compose.yml").exists() and (parent / "backend").is_dir():
            return parent
    # Backend container images only contain /app/{app,scripts,tests}; there is
    # no compose file or frontend source inside that runtime.
    for parent in (current.parent, *current.parents):
        if (parent / "app").is_dir() and (parent / "scripts").is_dir():
            return parent
    return current.parents[2]


def _default_base_url(cwd: Path) -> str:
    if (cwd / "app").is_dir() and (cwd / "scripts").is_dir() and not (cwd / "backend").is_dir():
        return "http://127.0.0.1:8000/api/v1"
    return DEFAULT_BASE_URL


def _secret_scan_targets(cwd: Path) -> list[str]:
    if (cwd / "backend").is_dir():
        return SECRET_SCAN_TARGETS
    targets = ["app", "tests", "scripts"]
    if (cwd / "README.md").exists():
        targets.append("README.md")
    if (cwd / "docs").is_dir():
        targets.append("docs")
    return targets


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


def _post_json(base_url: str, path: str, payload: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            response_body = resp.read().decode("utf-8")
    except TimeoutError as exc:
        raise SmokeFailure(f"POST {path} timed out after {timeout:.0f}s") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"POST {path} failed: {exc}") from exc
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"POST {path} returned non-JSON body: {response_body[:200]}") from exc


def _expected_ai_backend() -> str | None:
    value = (
        os.environ.get("RELEASE_SMOKE_EXPECTED_AI_BACKEND")
        or os.environ.get("AI_BACKEND")
        or ""
    ).strip()
    return value or None


def _expected_ai_model(backend: str | None) -> str | None:
    explicit = os.environ.get("RELEASE_SMOKE_EXPECTED_AI_MODEL")
    if explicit:
        return explicit.strip() or None
    if backend == "openai":
        return (os.environ.get("OPENAI_MODEL") or "").strip() or None
    if backend == "dashscope":
        return (os.environ.get("QWEN_MODEL") or "").strip() or None
    return None


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
    STATS["pass"] += 1
    suffix = f" - {detail}" if detail else ""
    print(f"[PASS] {name}{suffix}", flush=True)


def _warn(name: str, detail: str = "") -> None:
    STATS["warn"] += 1
    suffix = f" - {detail}" if detail else ""
    WARNINGS.append(f"{name}{suffix}")
    print(f"[WARN] {name}{suffix}", flush=True)


def _fail(message: str) -> None:
    STATS["fail"] += 1
    print(f"[FAIL] {message}", flush=True)


def _print_summary() -> None:
    print(
        f"[SUMMARY] pass={STATS['pass']} warn={STATS['warn']} fail={STATS['fail']}",
        flush=True,
    )
    if WARNINGS:
        print("[NEXT] Review WARN lines above before demo; rerun this script after upstream/sync status changes.", flush=True)


def _check_compose(cwd: Path) -> None:
    if shutil.which("docker") is None:
        _warn(
            "docker compose ps",
            "docker CLI not available inside backend runtime; run outer `docker compose ps` separately and rely on HTTP checks here",
        )
        return
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
    backend = ai.get("backend")
    model = ai.get("model")
    expected_backend = _expected_ai_backend()
    if expected_backend:
        _require(backend == expected_backend, f"/health/ai backend is {backend!r}, expected {expected_backend!r}")
    else:
        _require(isinstance(backend, str) and bool(backend), "/health/ai backend is empty")
    expected_model = _expected_ai_model(backend if isinstance(backend, str) else None)
    if expected_model:
        _require(model == expected_model, f"/health/ai model is {model!r}, expected {expected_model!r}")
    else:
        _require(isinstance(model, str) and bool(model), "/health/ai model is empty")
    if ai.get("ok") is True:
        _pass("health/ai", f"ok=true backend={backend} model={model} latency_ms={ai.get('latency_ms')}")
    else:
        _warn(
            "health/ai",
            f"probe_ok=false backend={backend} model={model} reason={ai.get('reason') or 'unknown'}; "
            "next=continue reading SSE real screen result below; rerun later if both probe and real screen fail",
        )

    data = _http_json(base_url, "/health/data")
    _require(data.get("fresh") is True, f"/health/data fresh=false: {data.get('freshness', {}).get('message')}")
    _require(data.get("expected_trade_date") == data.get("latest_trade_date"), "/health/data latest date is behind expected date")
    sync_warnings = data.get("sync_warnings") or []
    _pass(
        "health/data",
        f"fresh=true latest={data.get('latest_trade_date')} warnings={len(sync_warnings)}",
    )
    if sync_warnings:
        labels = [
            f"{item.get('label') or item.get('job')}:{item.get('status') or 'unknown'}"
            for item in sync_warnings
            if isinstance(item, dict)
        ]
        _warn(
            "health/data sync_warnings",
            f"{', '.join(labels)}; next=retry failed sync jobs when no heavy sync is running",
        )
    active_jobs = (data.get("freshness") or {}).get("active_jobs") or []
    if active_jobs:
        _warn(
            "health/data active_jobs",
            f"{', '.join(active_jobs)} running; next=poll /health/data before starting heavy backfills",
        )


def _check_fast_path(base_url: str) -> None:
    events = _post_sse(base_url, "你好", {})
    types = _event_types(events)
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    _require(plan.get("tool") == "ask_clarification", f"你好 routed to {plan.get('tool')}")
    _require(plan.get("tool_label") == "普通回复", f"你好 label={plan.get('tool_label')}")
    _require("screening" not in types and "result" not in types, "你好 triggered screening/result events")
    _require("done" in types, "你好 stream did not emit done")
    _require(terminal.get("fallback_reason") != "local_fast_path", "你好 should not use local fast-path")
    if plan.get("ai_used") is True:
        _require(terminal.get("fallback_reason") is None, f"你好 fallback_reason={terminal.get('fallback_reason')!r}")
        _pass("SSE greeting model final", f"你好 -> 普通回复, model_ms={terminal.get('model_ms')}")
        return
    _require(terminal.get("fallback_reason"), "你好 safe-stop missing fallback_reason")
    _warn("SSE greeting safe-stop", f"你好 stopped without local fallback: {terminal.get('fallback_reason')}")


def _check_plain_chat(base_url: str) -> None:
    events = _post_sse(base_url, "这个 Agent 是什么", {})
    types = _event_types(events)
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    terminal_text = json.dumps(terminal, ensure_ascii=False)
    _require(plan.get("tool") == "ask_clarification", f"plain chat routed to {plan.get('tool')}")
    _require(plan.get("tool_label") == "普通回复", f"plain chat label={plan.get('tool_label')}")
    _require("screening" not in types and "result" not in types and "planned" not in types, "plain chat triggered tool events")
    _require(terminal.get("fallback_reason") != "local_fast_path", "plain chat should not use local fast-path")
    if plan.get("ai_used") is True:
        _require(terminal.get("fallback_reason") is None, f"plain chat fallback={terminal.get('fallback_reason')!r}")
        _require("有界选股 Agent" in terminal_text or "Agent" in terminal_text, "plain chat did not explain Agent boundary")
        _pass("SSE plain chat model final", f"这个 Agent 是什么 -> 普通回复, model_ms={terminal.get('model_ms')}")
        return
    _require(terminal.get("fallback_reason"), "plain chat safe-stop missing fallback_reason")
    _warn("SSE plain chat safe-stop", f"这个 Agent 是什么 stopped without local fallback: {terminal.get('fallback_reason')}")


def _check_strategy_agent_api(base_url: str) -> None:
    started = time.time()
    payload = _post_json(base_url, "/strategy/agent", {"query": "这个 Agent 是什么", "limit": 10})
    elapsed = time.time() - started
    plan = payload.get("plan") or {}
    payload_text = json.dumps(payload, ensure_ascii=False)
    _require(plan.get("tool") == "ask_clarification", f"/strategy/agent plain chat routed to {plan.get('tool')}")
    _require(plan.get("tool_label") == "普通回复", f"/strategy/agent plain chat label={plan.get('tool_label')}")
    _require(payload.get("screen_result") is None, "/strategy/agent plain chat returned screen_result")
    _require(payload.get("strategy_result") is None, "/strategy/agent plain chat returned strategy_result")
    _require("local_fast_path" not in payload_text, "/strategy/agent plain chat used local fast-path")
    if plan.get("ai_used") is True:
        _require("有界选股 Agent" in payload_text or "Agent" in payload_text, "/strategy/agent did not explain Agent boundary")
        _pass("Strategy Agent API model final", f"这个 Agent 是什么 -> 普通回复 elapsed={elapsed:.1f}s")
        return
    warnings = payload.get("warnings") or []
    _require(warnings, "/strategy/agent safe-stop missing warning")
    _warn("Strategy Agent API safe-stop", f"这个 Agent 是什么 stopped without local fallback: {warnings[0]}")


def _check_strategy_fast_path(base_url: str) -> None:
    events = _post_sse(base_url, "找最近强势突破的股票", {})
    types = _event_types(events)
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    embedded_result = terminal.get("result") if isinstance(terminal.get("result"), dict) else {}
    strategy = embedded_result.get("strategy") if isinstance(embedded_result.get("strategy"), dict) else {}
    if plan.get("tool") == "ask_clarification" and terminal.get("fallback_reason"):
        _require("screening" not in types and "result" not in types, "strategy safe-stop still triggered tool events")
        _warn("SSE strategy safe-stop", f"找最近强势突破的股票 stopped without local fallback: {terminal.get('fallback_reason')}")
        return
    expected_strategy_ids = {"turtle_breakout", "rps_breakout"}
    _require(plan.get("tool") == "strategy_select", f"strategy query routed to {plan.get('tool')}")
    _require(plan.get("strategy_id") in expected_strategy_ids, f"strategy_id={plan.get('strategy_id')}")
    _require(plan.get("ai_used") is True, "strategy query should use model judgment")
    _require(terminal.get("fallback_reason") is None, f"strategy fallback={terminal.get('fallback_reason')!r}")
    _require("planned" in types and "screening" in types and "agent" in types, "strategy fast-path missing strategy events")
    _require("result" not in types, "strategy_select should not emit stock_screen result event")
    _require(strategy.get("id") == plan.get("strategy_id"), "strategy result id mismatch")
    _pass(
        "SSE strategy model action",
        f"找最近强势突破的股票 -> {plan.get('strategy_id')} total={embedded_result.get('total')} model_ms={terminal.get('model_ms')}",
    )


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
    _require("screening" not in types and "result" not in types, "stock_detail triggered screening/result events")
    if plan.get("tool") == "ask_clarification" and terminal.get("fallback_reason"):
        _warn("SSE stock_detail safe-stop", f"查看第一只详情 stopped without local fallback: {terminal.get('fallback_reason')}")
        return
    _require(plan.get("tool") == "stock_detail", f"detail routed to {plan.get('tool')}")
    _require(plan.get("ai_used") is True, "stock_detail should use model judgment")
    calls = terminal.get("tool_calls") or []
    detail_call = next((call for call in calls if call.get("name") == "stock_detail"), None)
    _require(bool(detail_call), "stock_detail call missing")
    _require(detail_call.get("result", {}).get("url") == "/detail/600036.SH", "stock_detail url mismatch")
    _pass("SSE stock_detail", "查看第一只详情 -> /detail/600036.SH")


def _check_named_detail(base_url: str) -> None:
    events = _post_sse(base_url, "我想看一下招商银行的详情", {})
    types = _event_types(events)
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    _require("screening" not in types and "result" not in types, "named stock_detail triggered screening/result events")
    if plan.get("tool") == "ask_clarification" and terminal.get("fallback_reason"):
        _warn("SSE named stock_detail safe-stop", f"招商银行详情 stopped without local fallback: {terminal.get('fallback_reason')}")
        return
    _require(plan.get("tool") == "stock_detail", f"named detail routed to {plan.get('tool')}")
    _require(plan.get("ai_used") is True, "named stock_detail should use model judgment")
    calls = terminal.get("tool_calls") or []
    detail_call = next((call for call in calls if call.get("name") == "stock_detail"), None)
    _require(bool(detail_call), "named stock_detail call missing")
    _require(detail_call.get("result", {}).get("url") == "/detail/600036.SH", "named stock_detail url mismatch")
    _pass("SSE named stock_detail", "我想看一下招商银行的详情 -> /detail/600036.SH")


def _check_real_screen(base_url: str) -> dict[str, Any]:
    started = time.time()
    events = _post_sse(base_url, "低估值高分红的银行股", {})
    elapsed = time.time() - started
    types = _event_types(events)
    terminal = _terminal(events)
    plan = terminal.get("plan") or {}
    _require(isinstance(terminal.get("model_ms"), int), "screen result missing model_ms")
    _require(isinstance(terminal.get("tool_ms"), int), "screen result missing tool_ms")
    if terminal.get("type") == "result":
        _require(plan.get("tool") == "stock_screen", f"screen routed to {plan.get('tool')}")
        _require("screening" in types and "result" in types and "done" in types, "screen stream missing screening/result/done")
        _require(int(terminal.get("total") or 0) > 0, "screen result total is 0")
        _pass(
            "SSE real screen",
            f"total={terminal.get('total')} model_ms={terminal.get('model_ms')} "
            f"tool_ms={terminal.get('tool_ms')} fallback_reason={terminal.get('fallback_reason') or '-'} "
            f"completion_reason={terminal.get('completion_reason') or '-'} "
            f"elapsed={elapsed:.1f}s",
        )
        return _context_from_events(events)

    _require(terminal.get("type") == "agent", f"screen terminal type is {terminal.get('type')}")
    _require(plan.get("tool") == "ask_clarification", f"failed screen should stop as ask_clarification, got {plan.get('tool')}")
    _require("screening" not in types and "result" not in types, "failed screen still triggered screening/result events")
    _require(terminal.get("fallback_reason"), "failed screen did not expose fallback_reason")
    _pass(
        "SSE real screen safe-stop",
        f"model_ms={terminal.get('model_ms')} fallback_reason={terminal.get('fallback_reason')} "
        f"elapsed={elapsed:.1f}s",
    )
    return {}


def _check_secret_scan(cwd: Path) -> None:
    targets = _secret_scan_targets(cwd)
    if shutil.which("rg") is None:
        _check_secret_scan_python(cwd, targets)
        return
    proc = _run(["rg", "-n", SECRET_PATTERN, *targets], cwd=cwd)
    if proc.returncode == 0:
        raise SmokeFailure(f"targeted secret scan found matches:\n{proc.stdout}")
    if proc.returncode not in (0, 1):
        raise SmokeFailure(f"targeted secret scan failed:\n{proc.stdout}")
    _pass("targeted secret scan", "no matches")


def _check_secret_scan_python(cwd: Path, targets: list[str]) -> None:
    pattern = re.compile(SECRET_PATTERN)
    skip_suffixes = {".db", ".sqlite", ".pyc", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    matches: list[str] = []
    scanned = 0
    for target in targets:
        root = cwd / target
        if not root.exists():
            continue
        paths = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in paths:
            if path.suffix.lower() in skip_suffixes or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            scanned += 1
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{path.relative_to(cwd)}:{lineno}:{line[:160]}")
    if matches:
        raise SmokeFailure("targeted secret scan found matches:\n" + "\n".join(matches[:20]))
    if scanned == 0:
        _warn("targeted secret scan", "no readable targets in this runtime")
        return
    _pass("targeted secret scan", f"no matches via python fallback ({scanned} files)")


def main() -> int:
    cwd = _repo_root()
    base_url = os.environ.get("RELEASE_SMOKE_BASE_URL", _default_base_url(cwd))
    print(f"Release smoke base URL: {base_url}", flush=True)
    checks = [
        lambda: _check_compose(cwd),
        lambda: _check_health(base_url),
        lambda: _check_fast_path(base_url),
        lambda: _check_plain_chat(base_url),
        lambda: _check_strategy_agent_api(base_url),
        lambda: _check_strategy_fast_path(base_url),
        lambda: _check_detail(base_url),
        lambda: _check_named_detail(base_url),
        lambda: _check_real_screen(base_url),
        lambda: _check_secret_scan(cwd),
    ]
    for check in checks:
        try:
            check()
        except SmokeFailure as exc:
            _fail(str(exc))
            _print_summary()
            return 1
    _pass("release smoke complete")
    _print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
