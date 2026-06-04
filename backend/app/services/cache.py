"""Redis 缓存层 —— 千问 NL 解析、个股分析等可重复请求复用结果。

设计原则：
- 缓存不可用时，业务正常进行（go-around，不抛错）
- key 用 hashlib 摘要，避免出现非 ASCII 触发的连接器问题
- 默认 1 小时 TTL；调用方可覆盖
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from loguru import logger

from app.config import settings


_client = None
_init_attempted = False


def _get_client():
    """惰性初始化；上游不可达时返回 None，由调用方走原路径。"""
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True

    url = (settings.redis_url or "").strip()
    if not url:
        logger.info("[CACHE] 未配置 REDIS_URL，缓存禁用")
        return None
    try:
        import redis
        c = redis.from_url(url, socket_connect_timeout=1.0, socket_timeout=1.0, decode_responses=True)
        c.ping()
        _client = c
        logger.info("[CACHE] Redis 连接成功 ({})", url)
    except Exception as e:
        logger.warning("[CACHE] Redis 不可达，缓存禁用：{}", str(e)[:120])
        _client = None
    return _client


def make_key(namespace: str, payload: Any) -> str:
    """统一 hash key 生成：namespace:sha1(payload)"""
    if isinstance(payload, str):
        raw = payload
    else:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]
    return f"qwen:{namespace}:{h}"


def get_json(key: str) -> Any | None:
    c = _get_client()
    if c is None:
        return None
    try:
        s = c.get(key)
        if s is None:
            return None
        return json.loads(s)
    except Exception as e:
        logger.warning("[CACHE] get 失败：{}", str(e)[:80])
        return None


def set_json(key: str, value: Any, ttl: int = 3600) -> bool:
    c = _get_client()
    if c is None:
        return False
    try:
        c.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        return True
    except Exception as e:
        logger.warning("[CACHE] set 失败：{}", str(e)[:80])
        return False


def delete_prefix(prefix: str) -> int:
    """Best-effort delete for namespace-style cache keys."""
    c = _get_client()
    if c is None:
        return 0
    deleted = 0
    try:
        for key in c.scan_iter(match=f"{prefix}*", count=100):
            deleted += int(c.delete(key) or 0)
        return deleted
    except Exception as e:
        logger.warning("[CACHE] delete_prefix 失败：{}", str(e)[:80])
        return deleted


def get_text(key: str) -> str | None:
    c = _get_client()
    if c is None:
        return None
    try:
        return c.get(key)
    except Exception:
        return None


def set_text(key: str, value: str, ttl: int = 3600) -> bool:
    c = _get_client()
    if c is None:
        return False
    try:
        c.set(key, value, ex=ttl)
        return True
    except Exception:
        return False


def stats() -> dict:
    """返回简单统计；用于 /health 暴露。"""
    c = _get_client()
    if c is None:
        return {"enabled": False}
    try:
        info = c.info(section="stats")
        keyspace = c.info(section="keyspace")
        db0 = keyspace.get("db0", {}) if isinstance(keyspace, dict) else {}
        return {
            "enabled": True,
            "keys": db0.get("keys") if isinstance(db0, dict) else None,
            "hits": info.get("keyspace_hits"),
            "misses": info.get("keyspace_misses"),
        }
    except Exception:
        return {"enabled": True, "error": "info 调用失败"}
