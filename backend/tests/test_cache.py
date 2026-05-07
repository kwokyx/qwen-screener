"""cache 模块：key 生成 + redis 不可达时的优雅降级。"""
import pytest

from app.services import cache


@pytest.fixture
def cache_disabled(monkeypatch):
    """强制禁用 Redis，模拟 REDIS_URL 未配置的情况。"""
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "_init_attempted", True)  # 跳过初始化
    yield


def test_make_key_string():
    k = cache.make_key("nl", "低估值的银行股")
    assert k.startswith("qwen:nl:")
    assert len(k) == len("qwen:nl:") + 24  # sha1 取前 24


def test_make_key_dict_stable():
    """dict 顺序不同也产生相同 key（sort_keys=True 保证）。"""
    a = cache.make_key("analyze", {"a": 1, "b": 2})
    b = cache.make_key("analyze", {"b": 2, "a": 1})
    assert a == b


def test_make_key_namespace_isolated():
    """不同 namespace 即使 payload 相同，key 不冲突。"""
    a = cache.make_key("nl", "x")
    b = cache.make_key("analyze", "x")
    assert a != b


def test_get_set_when_redis_disabled(cache_disabled):
    """Redis 不可达 → 应静默返回 None / False，不抛错。"""
    assert cache.get_json("qwen:test:nokey") is None
    assert cache.set_json("qwen:test:nokey", {"foo": 1}) is False
    assert cache.get_text("qwen:test:nokey") is None
    assert cache.set_text("qwen:test:nokey", "hello") is False


def test_stats_when_disabled(cache_disabled):
    s = cache.stats()
    assert s == {"enabled": False}
