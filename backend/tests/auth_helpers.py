from fastapi.testclient import TestClient

from app.services import captcha as captcha_service


def captcha_payload(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/captcha")
    assert response.status_code == 200
    body = response.json()
    assert body["image"].startswith("data:image/svg+xml;base64,")
    item = captcha_service._captcha_store.get(body["id"])
    assert item is not None
    return {"captcha_id": body["id"], "captcha_code": item[1]}


def register_json(client: TestClient, username: str, password: str, **extra) -> dict[str, str]:
    payload = {"username": username, "password": password, **extra}
    payload.update(captcha_payload(client))
    return payload


def login_form(client: TestClient, username: str, password: str) -> dict[str, str]:
    payload = {"username": username, "password": password}
    payload.update(captcha_payload(client))
    return payload
