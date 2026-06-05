from __future__ import annotations

import base64
import html
import secrets
import string
import threading
import time


CAPTCHA_TTL_SECONDS = 300
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_captcha_lock = threading.Lock()
_captcha_store: dict[str, tuple[float, str]] = {}


def _cleanup(now: float) -> None:
    expired = [captcha_id for captcha_id, (expires_at, _) in _captcha_store.items() if expires_at <= now]
    for captcha_id in expired:
        _captcha_store.pop(captcha_id, None)


def _random_code(length: int = 4) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _noise_lines() -> str:
    lines = []
    for _ in range(4):
        x1 = secrets.randbelow(120)
        x2 = secrets.randbelow(120)
        y1 = secrets.randbelow(40)
        y2 = secrets.randbelow(40)
        opacity = 0.10 + secrets.randbelow(15) / 100
        lines.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="#111111" stroke-width="1" opacity="{opacity:.2f}" />'
        )
    return "".join(lines)


def _render_svg(code: str) -> str:
    letters = []
    for index, char in enumerate(code):
        x = 18 + index * 23 + secrets.randbelow(5)
        y = 27 + secrets.randbelow(8)
        rotate = secrets.choice([-8, -5, -3, 3, 5, 8])
        letters.append(
            f'<text x="{x}" y="{y}" transform="rotate({rotate} {x} {y})" '
            f'font-family="IBM Plex Mono, ui-monospace, Menlo, monospace" '
            f'font-size="22" font-weight="800" fill="#111111">{html.escape(char)}</text>'
        )
    dots = "".join(
        f'<circle cx="{secrets.randbelow(120)}" cy="{secrets.randbelow(40)}" r="1" fill="#71717A" opacity="0.35" />'
        for _ in range(18)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40" viewBox="0 0 120 40" role="img">'
        '<rect width="120" height="40" rx="8" fill="#F5F5F5" />'
        f'{_noise_lines()}{dots}{"".join(letters)}'
        '</svg>'
    )


def create_captcha() -> dict[str, str | int]:
    now = time.monotonic()
    code = _random_code()
    captcha_id = secrets.token_urlsafe(18)
    svg = _render_svg(code)
    image = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    with _captcha_lock:
        _cleanup(now)
        _captcha_store[captcha_id] = (now + CAPTCHA_TTL_SECONDS, code)
    return {
        "id": captcha_id,
        "image": image,
        "expires_in": CAPTCHA_TTL_SECONDS,
    }


def verify_captcha(captcha_id: str | None, captcha_code: str | None) -> bool:
    if not captcha_id or not captcha_code:
        return False
    now = time.monotonic()
    normalized = "".join(ch for ch in captcha_code.upper() if ch in string.ascii_uppercase + string.digits)
    with _captcha_lock:
        _cleanup(now)
        item = _captcha_store.pop(captcha_id, None)
    if not item:
        return False
    _, expected = item
    return secrets.compare_digest(normalized, expected)
