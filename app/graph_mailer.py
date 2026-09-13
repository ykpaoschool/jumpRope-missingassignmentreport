"""通过 Microsoft Graph（应用凭据 client secret）经共享邮箱发送邮件。"""

from __future__ import annotations

import httpx
import msal

from . import config

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]


class MailerError(Exception):
    pass


def _get_app() -> msal.ConfidentialClientApplication:
    if not config.is_configured():
        raise MailerError("未配置 Azure 凭据（请在 .env 中填写 TENANT_ID / CLIENT_ID / CLIENT_SECRET / SHARED_MAILBOX）")
    authority = f"https://login.microsoftonline.com/{config.TENANT_ID}"
    return msal.ConfidentialClientApplication(
        config.CLIENT_ID,
        authority=authority,
        client_credential=config.CLIENT_SECRET,
    )


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


def test_connection() -> dict:
    """校验凭据与共享邮箱是否可用。"""
    token = _get_token()
    url = f"{GRAPH_BASE}/users/{config.SHARED_MAILBOX}"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code == 200:
        return {"ok": True, "mailbox": config.SHARED_MAILBOX}
    return {"ok": False, "status": resp.status_code, "error": _extract_error(resp)}


def send_email(recipient: str, subject: str, html_body: str) -> None:
    """发送一封邮件；成功返回 None，失败抛 MailerError。"""
    token = _get_token()
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "html", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        },
        "saveToSentItems": True,
    }
    url = f"{GRAPH_BASE}/users/{config.SHARED_MAILBOX}/sendMail"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=60,
    )
    if resp.status_code == 202:
        return
    raise MailerError(f"发送失败 ({resp.status_code})：{_extract_error(resp)}")
