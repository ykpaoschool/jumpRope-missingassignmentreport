"""通过 Microsoft Graph（应用凭据 client secret）经共享邮箱发送邮件。"""

from __future__ import annotations

import threading
import time
from typing import Optional

import httpx
import msal

from . import config

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]

# 限流重试：Exchange Online 的 sendMail 约 30 封/分钟，超限返回 429
RETRY_STATUSES = (429, 503)
MAX_RETRIES = 2
DEFAULT_RETRY_AFTER = 5.0


class MailerError(Exception):
    pass


_app_lock = threading.Lock()
_app: Optional[msal.ConfidentialClientApplication] = None
_app_key: Optional[tuple] = None


def _get_app() -> msal.ConfidentialClientApplication:
    """懒加载单例：MSAL 的内存 token 缓存挂在应用实例上，每次新建等于每封邮件都去 AAD 换 token。"""
    global _app, _app_key
    if not config.is_configured():
        raise MailerError("未配置 Azure 凭据（请在 .env 中填写 TENANT_ID / CLIENT_ID / CLIENT_SECRET / SHARED_MAILBOX）")
    key = (config.TENANT_ID, config.CLIENT_ID, config.CLIENT_SECRET)
    with _app_lock:
        if _app is None or _app_key != key:
            authority = f"https://login.microsoftonline.com/{config.TENANT_ID}"
            _app = msal.ConfidentialClientApplication(
                config.CLIENT_ID,
                authority=authority,
                client_credential=config.CLIENT_SECRET,
            )
            _app_key = key
    return _app


def _get_token() -> str:
    result = _get_app().acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise MailerError(f"获取 token 失败：{result.get('error_description') or result}")
    return result["access_token"]


def _extract_error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return data.get("error", {}).get("message") or str(data)
    except Exception:  # noqa: BLE001
        return resp.text[:500]


def _retry_after(resp: httpx.Response) -> float:
    """读取 Retry-After 秒数，异常/缺失时用默认值，并封顶 60 秒。"""
    try:
        return max(0.0, min(60.0, float(resp.headers.get("Retry-After", ""))))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER


def test_connection() -> dict:
    """校验凭据与共享邮箱是否可用。"""
    token = _get_token()
    url = f"{GRAPH_BASE}/users/{config.SHARED_MAILBOX}"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code == 200:
        return {"ok": True, "mailbox": config.SHARED_MAILBOX}
    return {"ok": False, "status": resp.status_code, "error": _extract_error(resp)}


class _GraphSession:
    """复用一条 HTTP 连接与 token 缓存，发完整批。"""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=60)

    def __enter__(self) -> "_GraphSession":
        _get_app()  # 配置缺失时立刻失败，由调用方整批标记
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        self._client.close()

    def send(self, recipient: str, subject: str, html_body: str) -> None:
        """发送一封邮件；成功返回 None，失败抛 MailerError。"""
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "html", "content": html_body},
                "toRecipients": [{"emailAddress": {"address": recipient}}],
            },
            "saveToSentItems": True,
        }
        url = f"{GRAPH_BASE}/users/{config.SHARED_MAILBOX}/sendMail"
        for attempt in range(MAX_RETRIES + 1):
            headers = {"Authorization": f"Bearer {_get_token()}"}  # 走 MSAL 缓存，通常无需网络
            resp = self._client.post(url, headers=headers, json=payload)
            if resp.status_code == 202:
                return
            if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(_retry_after(resp))
                continue
            raise MailerError(f"发送失败 ({resp.status_code})：{_extract_error(resp)}")
        raise MailerError("发送失败：限流重试次数已用尽")  # 逻辑上不可达


def session() -> _GraphSession:
    """返回可复用的发送会话；进入 with 时才创建 HTTP client。"""
    return _GraphSession()


def send_email(recipient: str, subject: str, html_body: str) -> None:
    """发送一封邮件；成功返回 None，失败抛 MailerError。"""
    with session() as s:
        s.send(recipient, subject, html_body)
