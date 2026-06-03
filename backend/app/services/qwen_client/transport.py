"""底层 I/O：OpenAI Responses / Chat Completions / 流式 / DashScope 兜底
+ 瞬时错误重试 + 错误消息产品化。

所有外部 HTTP / SDK 细节都在这里；上层只看到 _call / stream_call / probe_health。
"""
from __future__ import annotations

import json
import time
from threading import Lock
from typing import Any

from loguru import logger

from app.config import settings


# 上游中转网络偶发抖动（Connection reset / Timeout），自动重试可消除大部分用户感知
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.8  # 第 N 次失败后等 0.8、1.6、3.2 秒
_RESPONSES_TIMEOUT = 8.0
_RESPONSES_BREAKER_SECONDS = 300.0
_responses_unavailable_until = 0.0
_HEALTH_CACHE_SECONDS = 60.0
_HEALTH_FAILURE_CACHE_SECONDS = 5.0
_HEALTH_OK_GRACE_SECONDS = 300.0
_health_probe_lock = Lock()
_health_cache: tuple[float, dict] | None = None
_last_health_ok: tuple[float, dict] | None = None
_TRANSIENT_KEYWORDS = (
    "connection reset", "connection aborted", "remotedisconnect",
    "timeout", "timed out", "broken pipe", "errno 54", "errno 60",
    "max retries exceeded", "apiconnection",
)


def _responses_api_enabled() -> bool:
    return settings.openai_responses_enabled and time.monotonic() >= _responses_unavailable_until


def _mark_responses_api_unavailable() -> None:
    global _responses_unavailable_until
    _responses_unavailable_until = time.monotonic() + _RESPONSES_BREAKER_SECONDS


def _openai_base_url() -> str:
    base_url = (settings.openai_base_url or "https://api.openai.com").rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def _is_transient(exc: Exception) -> bool:
    s = str(exc).lower()
    name = exc.__class__.__name__.lower()
    return any(k in s for k in _TRANSIENT_KEYWORDS) or "connection" in name or "timeout" in name


def _user_friendly_error(exc: Exception) -> str:
    """把内部错误（errno、Connection reset 等）翻译成产品级提示。"""
    if _is_transient(exc):
        return "AI 服务暂时不可达，已自动重试若干次仍失败。请稍后再试。"
    s = str(exc)
    if "API_KEY" in s or "api_key" in s or "401" in s or "Unauthorized" in s:
        return "AI 服务凭证无效，请联系管理员检查配置"
    if "rate" in s.lower() and "limit" in s.lower():
        return "AI 服务请求过于频繁，请稍后再试"
    return "AI 服务调用失败，请稍后再试"


# ---------------------- Health probe ----------------------

def probe_health(timeout: float = 6.0) -> dict:
    """轻量探测当前配置的 AI 后端是否真的可用。"""
    global _health_cache, _last_health_ok
    with _health_probe_lock:
        now = time.monotonic()
        backend = (settings.ai_backend or "openai").lower()
        if _health_cache and now < _health_cache[0]:
            return _with_runtime_status(backend, _health_cache[1])

        status = _probe_backend_health(backend, timeout)

        if status.get("ok"):
            _last_health_ok = (now + _HEALTH_OK_GRACE_SECONDS, dict(status))
        elif _is_transient_health_status(status):
            if _last_health_ok and now < _last_health_ok[0]:
                status = dict(_last_health_ok[1])
                status["stale"] = True
            else:
                time.sleep(0.25)
                status = _probe_backend_health(backend, timeout)
                if status.get("ok"):
                    _last_health_ok = (now + _HEALTH_OK_GRACE_SECONDS, dict(status))

        status = _with_runtime_status(backend, status)
        cache_seconds = _HEALTH_FAILURE_CACHE_SECONDS if _is_transient_health_status(status) else _HEALTH_CACHE_SECONDS
        _health_cache = (now + cache_seconds, dict(status))
        return status


def _model_for_backend(backend: str) -> str:
    return settings.qwen_model if backend == "dashscope" else settings.openai_model


def _configured_for_backend(backend: str) -> bool:
    if backend == "dashscope":
        return bool(settings.dashscope_api_key)
    return bool(settings.openai_api_key)


def _with_runtime_status(backend: str, status: dict) -> dict:
    """Attach non-secret runtime metadata for UI and Agent fallback decisions."""
    result = dict(status)
    configured = _configured_for_backend(backend)
    ok = bool(result.get("ok"))
    result.setdefault("backend", backend)
    result.setdefault("model", _model_for_backend(backend))
    result["configured"] = configured
    result["fallback"] = not ok
    result["mode"] = "ai_agent" if ok else ("local_fallback" if configured else "local_rules")
    return result


def _probe_backend_health(backend: str, timeout: float) -> dict:
    if backend == "dashscope":
        return _probe_dashscope_health(timeout)
    return _probe_openai_health(timeout)


def _is_transient_health_status(status: dict) -> bool:
    return status.get("reason") in {
        "上游网络不可达",
        "服务暂时不可用",
        "千问服务网络不可达",
        "千问服务暂时不可用",
    }


def _probe_openai_health(timeout: float) -> dict:
    """按真实调用顺序探测 Responses API，再回退 Chat Completions。"""
    if not settings.openai_api_key:
        return {"ok": False, "latency_ms": None, "reason": "未配置 OPENAI_API_KEY"}
    import httpx
    base_url = _openai_base_url()
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    responses_payload = {
        "model": settings.openai_model,
        "input": "ping",
        "max_output_tokens": 1,
    }
    chat_payload = {
        "model": settings.openai_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    client_timeout = httpx.Timeout(timeout, connect=min(2.0, timeout))
    t0 = time.time()
    responses_result = None
    responses_error = None
    if _responses_api_enabled():
        try:
            with httpx.Client(timeout=client_timeout) as c:
                responses_result = c.post(f"{base_url}/responses", headers=headers, json=responses_payload)
        except Exception as exc:
            responses_error = exc
            _mark_responses_api_unavailable()

    latency_ms = int((time.time() - t0) * 1000)
    if responses_result is not None:
        if responses_result.status_code == 200:
            return {"ok": True, "latency_ms": latency_ms, "reason": None}
        if responses_result.status_code in (401, 403):
            return {"ok": False, "latency_ms": latency_ms, "reason": "鉴权失败"}
        _mark_responses_api_unavailable()

    try:
        with httpx.Client(timeout=client_timeout) as c:
            chat_result = c.post(f"{base_url}/chat/completions", headers=headers, json=chat_payload)
        latency_ms = int((time.time() - t0) * 1000)
        if chat_result.status_code == 200:
            return {"ok": True, "latency_ms": latency_ms, "reason": None}
        if chat_result.status_code in (401, 403):
            return {"ok": False, "latency_ms": latency_ms, "reason": "鉴权失败"}
        responses_text = responses_result.text[:220] if responses_result is not None else ""
        body = f"{responses_text} {chat_result.text[:220]}".lower()
        if "not supported" in body:
            return {"ok": False, "latency_ms": latency_ms, "reason": f"模型或网关不兼容: {settings.openai_model}"}
        response_status = responses_result.status_code if responses_result is not None else 0
        if max(response_status, chat_result.status_code) >= 500:
            diagnostics = _probe_openai_model_catalog(base_url, headers, client_timeout)
            reason = f"上游网关推理端不可用: HTTP {max(response_status, chat_result.status_code)}"
            if diagnostics.get("models_status") == 200:
                reason += "（模型列表正常）"
            return {
                "ok": False,
                "latency_ms": latency_ms,
                "reason": reason,
                "backend": "openai",
                "model": settings.openai_model,
                "stage": "inference",
                "responses_status": responses_result.status_code if responses_result is not None else None,
                "chat_status": chat_result.status_code,
                **diagnostics,
            }
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "reason": f"HTTP {chat_result.status_code}",
            "backend": "openai",
            "model": settings.openai_model,
            "stage": "chat",
            "responses_status": responses_result.status_code if responses_result is not None else None,
            "chat_status": chat_result.status_code,
        }
    except Exception as e:
        if _is_transient(e) or (responses_error is not None and _is_transient(responses_error)):
            return {"ok": False, "latency_ms": None, "reason": "上游网络不可达"}
        return {"ok": False, "latency_ms": None, "reason": "服务暂时不可用"}


def _probe_openai_model_catalog(base_url: str, headers: dict, timeout: httpx.Timeout) -> dict:
    """Check whether auth/base URL can reach the model catalog without exposing secrets."""
    import httpx

    try:
        with httpx.Client(timeout=timeout) as c:
            result = c.get(f"{base_url}/models", headers=headers)
        model_listed = None
        if result.status_code == 200:
            try:
                items = result.json().get("data", [])
                model_listed = any(item.get("id") == settings.openai_model for item in items if isinstance(item, dict))
            except Exception:
                model_listed = None
        return {
            "models_status": result.status_code,
            "model_listed": model_listed,
        }
    except Exception:
        return {
            "models_status": None,
            "model_listed": None,
        }


def _probe_dashscope_health(timeout: float) -> dict:
    """使用 DashScope OpenAI 兼容接口做最小探测，避免 SDK 调用长时间挂起。"""
    if not settings.dashscope_api_key:
        return {"ok": False, "latency_ms": None, "reason": "未配置 DASHSCOPE_API_KEY"}
    try:
        import httpx
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.dashscope_api_key}"}
        payload = {
            "model": settings.qwen_model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        t0 = time.time()
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(2.0, timeout))) as c:
            result = c.post(url, headers=headers, json=payload)
        latency_ms = int((time.time() - t0) * 1000)
        if result.status_code == 200:
            return {"ok": True, "latency_ms": latency_ms, "reason": None}
        if result.status_code in (401, 403):
            return {"ok": False, "latency_ms": latency_ms, "reason": "鉴权失败"}
        return {"ok": False, "latency_ms": latency_ms, "reason": f"千问服务不可用: HTTP {result.status_code}"}
    except Exception as e:
        msg = str(e).lower()
        if "reset" in msg or "refused" in msg or "timed out" in msg or "timeout" in msg:
            return {"ok": False, "latency_ms": None, "reason": "千问服务网络不可达"}
        return {"ok": False, "latency_ms": None, "reason": "千问服务暂时不可用"}


# ---------------------- OpenAI sync call ----------------------

def openai_client():
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，请在 backend/.env 中填入")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai 未安装，请 pip install -r requirements.txt") from e
    return OpenAI(api_key=settings.openai_api_key, base_url=_openai_base_url())


def _openai_call(prompt: str, *, json_mode: bool = False) -> str:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return _openai_call_once(prompt, json_mode=json_mode)
        except Exception as e:
            last_exc = e
            if not _is_transient(e) or attempt == _MAX_RETRIES - 1:
                break
            wait = _BACKOFF_BASE * (2 ** attempt)
            logger.warning("AI 调用失败 (#{}/{}, {} 秒后重试): {}", attempt + 1, _MAX_RETRIES, wait, e)
            time.sleep(wait)
    raise RuntimeError(_user_friendly_error(last_exc) if last_exc else "AI 服务调用失败")


def _openai_call_once(prompt: str, *, json_mode: bool = False) -> str:
    client = openai_client()
    model = settings.openai_model
    effort = settings.openai_reasoning or "high"

    # 1. 优先 Responses API；兼容网关不支持时短路一段时间，避免每次额外等待。
    if _responses_api_enabled():
        try:
            kwargs: dict[str, Any] = {"model": model, "input": prompt}
            if effort:
                kwargs["reasoning"] = {"effort": effort}
            if json_mode:
                kwargs["text"] = {"format": {"type": "json_object"}}
            resp = client.responses.create(**kwargs, timeout=_RESPONSES_TIMEOUT)
            text = getattr(resp, "output_text", None)
            if not text and getattr(resp, "output", None):
                chunks = []
                for item in resp.output:
                    for c in getattr(item, "content", []) or []:
                        t = getattr(c, "text", None)
                        if t:
                            chunks.append(t)
                text = "\n".join(chunks)
            if text:
                return text
            _mark_responses_api_unavailable()
            logger.warning("Responses API 返回空文本，回退 chat.completions")
        except Exception as e:
            if "401" in str(e) or "Unauthorized" in str(e):
                raise
            _mark_responses_api_unavailable()
            logger.warning("Responses API 失败，回退 chat.completions: {}", e)

    # 2. 回退 Chat Completions
    cc_kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": 60.0,
    }
    if json_mode:
        cc_kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**cc_kwargs)
    return resp.choices[0].message.content or ""


# ---------------------- DashScope 兜底 ----------------------

def _dashscope_call(prompt: str, *, json_mode: bool = False) -> str:
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY")
    try:
        import dashscope
    except ImportError as e:
        raise RuntimeError("dashscope 未安装") from e
    dashscope.api_key = settings.dashscope_api_key
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = dashscope.Generation.call(
        model=settings.qwen_model, prompt=prompt,
        result_format="message", **extra,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"千问调用失败: {resp.message}")
    return resp.output.choices[0].message.content


def call(prompt: str, *, json_mode: bool = False) -> str:
    """同步调用，按 settings.ai_backend 分发。"""
    backend = (settings.ai_backend or "openai").lower()
    if backend == "dashscope":
        return _dashscope_call(prompt, json_mode=json_mode)
    return _openai_call(prompt, json_mode=json_mode)


# ---------------------- 流式 ----------------------

def _openai_stream(prompt: str):
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY")
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        got_any = False
        try:
            for chunk in _openai_stream_once(prompt):
                got_any = True
                yield chunk
            return
        except Exception as e:
            last_exc = e
            if got_any:
                # 已经吐过 token 了，半途断开不重试（避免重复内容）
                break
            if not _is_transient(e) or attempt == _MAX_RETRIES - 1:
                break
            wait = _BACKOFF_BASE * (2 ** attempt)
            logger.warning("AI 流式调用失败 (#{}/{}, {} 秒后重试): {}", attempt + 1, _MAX_RETRIES, wait, e)
            time.sleep(wait)
    raise RuntimeError(_user_friendly_error(last_exc) if last_exc else "AI 服务调用失败")


def _openai_stream_once(prompt: str):
    import httpx
    url = f"{_openai_base_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": settings.openai_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    with httpx.stream("POST", url, headers=headers, json=payload,
                     timeout=httpx.Timeout(120.0, connect=10.0)) as r:
        if r.status_code != 200:
            body = r.read().decode("utf-8", errors="replace")[:300]
            if r.status_code in (401, 403):
                raise RuntimeError("AI 服务凭证无效，请联系管理员检查配置")
            if r.status_code == 429:
                raise RuntimeError("AI 服务请求过于频繁，请稍后再试")
            raise RuntimeError(f"上游 {r.status_code}")
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            try:
                delta = obj["choices"][0]["delta"]
                text = delta.get("content")
            except (KeyError, IndexError, TypeError):
                continue
            if text:
                yield text


def _dashscope_stream(prompt: str):
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY")
    import dashscope
    dashscope.api_key = settings.dashscope_api_key
    responses = dashscope.Generation.call(
        model=settings.qwen_model, prompt=prompt,
        result_format="message", stream=True, incremental_output=True,
    )
    for resp in responses:
        if resp.status_code != 200:
            raise RuntimeError(f"千问流式调用失败: {resp.message}")
        text = resp.output.choices[0].message.content
        if text:
            yield text


def stream_call(prompt: str):
    """返回 yields str 的迭代器；上层用 SSE 写出去即可。"""
    backend = (settings.ai_backend or "openai").lower()
    if backend == "dashscope":
        yield from _dashscope_stream(prompt)
    else:
        yield from _openai_stream(prompt)
