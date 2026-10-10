"""通过 SMTP 发送邮件，便于快速测试（无需 Azure/Graph 配置）。"""

from __future__ import annotations

import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from . import config, recipients

# 建连失败后依次等待这些秒数再重试，长度即重试次数（先 2 秒、再 5 秒）。
# 为什么需要：容器刚创建时内置 DNS 可能是冷的，直接回 `[Errno -2] Name or service not known`，
# 而整批只在循环外开一次连接，一次瞬时解析失败就等于整批一封都不发 —— 那会逼用户手动再点一次
# 「发送」，正是这个项目一直在防的重复发信动作。
# 登录失败不重试：凭据错是持续性的，重试只是让人多等 7 秒才看到原因。
CONNECT_RETRY_DELAYS = (2.0, 5.0)


class MailerError(Exception):
    pass


def _check_config() -> None:
    if not config.is_smtp_configured():
        raise MailerError(
            "未配置 SMTP（请在 .env 中填写 SMTP_HOST / SMTP_FROM，可选 SMTP_USER / SMTP_PASSWORD）"
        )


def _build_message(addrs: list[str], subject: str, html_body: str) -> MIMEMultipart:
    """addrs 为已经拆好的收件地址列表：To 头用 ', ' 连接才是合法的地址列表写法。"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((config.SENDER_DISPLAY_NAME, config.SMTP_FROM))
    msg["To"] = ", ".join(addrs)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def _open() -> smtplib.SMTP:
    """建 TCP/TLS 连接（不含登录），失败抛 MailerError。"""
    try:
        if config.SMTP_PORT == 465:
            return smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
        if config.SMTP_STARTTLS:
            server.starttls()
        return server
    except Exception as e:  # noqa: BLE001
        raise MailerError(f"连接 SMTP 服务器失败：{e}")


def _open_with_retry() -> smtplib.SMTP:
    """建 TCP/TLS 连接，瞬时失败退避重试；最后一次失败照原样抛出。

    重试过程打到 stderr：日志里要看得见「刚才重试过」，不能是魔法（用 docker compose logs 查）。
    """
    delays = list(CONNECT_RETRY_DELAYS)  # 每次现读，测试改模块常量即可生效
    while True:
        try:
            return _open()
        except MailerError as e:
            if not delays:
                raise
            delay = delays.pop(0)
            print(f"[SMTP] 建连失败，{delay:.0f} 秒后重试：{e}", file=sys.stderr)
            time.sleep(delay)


def _connect() -> smtplib.SMTP:
    _check_config()
    server = _open_with_retry()
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
    with session() as s:
        s.send(recipient, subject, html_body)


class _SmtpSession:
    """一条连接的发送会话：整批复用同一次 TCP + TLS + 登录。"""

    def __init__(self) -> None:
        self._server: Optional[smtplib.SMTP] = None

    def __enter__(self) -> "_SmtpSession":
        self._server = _connect()  # 连接/登录失败直接抛出，由调用方整批标记失败
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._server is None:
            return
        try:
            self._server.quit()
        except Exception:  # noqa: BLE001
            pass  # 关闭阶段的异常不影响已发出的邮件
        self._server = None

    def send(self, recipient: str, subject: str, html_body: str) -> None:
        """发送一封邮件；成功返回 None，失败抛 MailerError。

        recipient 可以是逗号/分号分隔的多个地址（同一学生的多位家长）。smtplib 不会自己拆
        逗号，整串丢给 RCPT TO 会被服务器拒收，所以这里必须先拆成地址列表。
        """
        addrs = recipients.split(recipient)
        if not addrs:
            raise MailerError("收件人地址为空")
        msg = _build_message(addrs, subject, html_body)
        try:
            self._server.sendmail(config.SMTP_FROM, addrs, msg.as_string())
            return
        except (smtplib.SMTPServerDisconnected, OSError) as e:
            # 长连接可能被服务器掐断（空闲超时/连接数限制）：重连后重试本封一次
            self._reconnect(e)
        try:
            self._server.sendmail(config.SMTP_FROM, addrs, msg.as_string())
        except Exception as e:  # noqa: BLE001
            raise MailerError(f"SMTP 发送失败：{e}")

    def _reconnect(self, cause: Exception) -> None:
        self.close()
        try:
            self._server = _connect()
        except MailerError as e:
            raise MailerError(f"SMTP 连接中断且重连失败（{cause}）：{e}")


def session() -> _SmtpSession:
    """返回可复用的发送会话；进入 with 时才真正建连。"""
    return _SmtpSession()
