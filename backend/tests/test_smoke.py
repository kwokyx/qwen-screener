"""最简冒烟测试：保证后端能启起来、关键路由存在。
论文"测试"一章可以扩展这里。"""
import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app
from app import models  # noqa: F401  触发 ORM 注册
from tests.auth_helpers import login_form, register_json


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "app" in r.json()


def test_openapi_has_screener(client):
    r = client.get("/openapi.json")
    paths = r.json()["paths"]
    assert any("/screener" in p for p in paths)


def test_register_and_login(client):
    client.post("/api/v1/auth/register", json=register_json(client, "smoke_user", "abc12345"))
    r = client.post("/api/v1/auth/login", data=login_form(client, "smoke_user", "abc12345"))
    assert r.status_code == 200
    assert "access_token" in r.json()
