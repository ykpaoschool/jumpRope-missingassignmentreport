"""通过 SMTP 发送邮件，便于快速测试（无需 Azure/Graph 配置）。"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from . import config


class MailerError(Exception):
    pass


def _check_config() -> None:
    if not config.is_smtp_configured():
        raise MailerError(
            "未配置 SMTP（请在 .env 中填写 SMTP_HOST / SMTP_FROM，可选 SMTP_USER / SMTP_PASSWORD）"
        )


def _build_message(recipient: str, subject: str, html_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((config.SENDER_DISPLAY_NAME, config.SMTP_FROM))
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def _connect() -> smtplib.SMTP:
    _check_config()
    try:
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
            if config.SMTP_STARTTLS:
                server.starttls()
    except Exception as e:  # noqa: BLE001
        raise MailerError(f"连接 SMTP 服务器失败：{e}")
    if config.SMTP_USER:
        try:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        except Exception as e:  # noqa: BLE001
            server.quit()
            raise MailerError(f"SMTP 登录失败：{e}")
    return server


def test_connection() -> dict:
    """校验 SMTP 配置是否可用。"""
    try:
        server = _connect()
        server.quit()
        return {"ok": True, "mailbox": f"{config.SMTP_FROM} (SMTP {config.SMTP_HOST}:{config.SMTP_PORT})"}
    except MailerError as e:
        return {"ok": False, "error": str(e)}


def send_email(recipient: str, subject: str, html_body: str) -> None:
    """发送一封邮件；成功返回 None，失败抛 MailerError。"""
    msg = _build_message(recipient, subject, html_body)
    server = _connect()
    try:
        server.sendmail(config.SMTP_FROM, [recipient], msg.as_string())
    except Exception as e:  # noqa: BLE001
        raise MailerError(f"SMTP 发送失败：{e}")
    finally:
        server.quit()
