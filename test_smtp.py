"""用最小 SMTP 服务器验证 smtp_mailer 端到端发送。"""

import smtplib
import socket
import threading
from email import policy
from email.parser import BytesParser

from app import config, smtp_mailer

received = {"raw": b"", "mail_from": "", "rcpt_to": []}


def run_server(port=1025):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)

    def handle(conn):
        f = conn.makefile("rwb", buffering=0)
        f.write(b"220 localhost ESMTP\r\n")
        in_data = False
        while True:
            line = f.readline()
            if not line:
                break
            if in_data:
                if line.rstrip(b"\r\n") == b".":
                    f.write(b"250 queued\r\n")
                    in_data = False
                else:
                    received["raw"] += line
                continue
            u = line.upper()
            if u.startswith(b"MAIL FROM"):
                received["mail_from"] = line.decode(errors="replace").strip()
                f.write(b"250 OK\r\n")
            elif u.startswith(b"RCPT TO"):
                received["rcpt_to"].append(line.decode(errors="replace").strip())
                f.write(b"250 OK\r\n")
            elif u.startswith(b"DATA"):
                f.write(b"354 go ahead\r\n")
                in_data = True
            elif u.startswith(b"QUIT"):
                f.write(b"221 bye\r\n")
                break
            elif u.startswith(b"EHLO") or u.startswith(b"HELO"):
                f.write(b"250 localhost\r\n")
            else:
                f.write(b"250 OK\r\n")
        conn.close()

    t = threading.Thread(target=lambda: handle(srv.accept()[0]), daemon=True)
    t.start()
    return srv, t


# 注入测试配置
config.SMTP_HOST = "127.0.0.1"
config.SMTP_PORT = 1025
config.SMTP_FROM = "no-reply@school.edu"
config.SMTP_USER = ""
config.SMTP_PASSWORD = ""
config.SMTP_STARTTLS = False
config.SENDER_DISPLAY_NAME = "教务部门 Academic Office"


def rcpt_addresses() -> list[str]:
    """服务端收到的收件地址（RCPT TO 行解析出来的裸地址）。"""
    return [r.split(":", 1)[1].strip().strip("<>") for r in received["rcpt_to"]]


srv, t = run_server(1025)

smtp_mailer.send_email("parent@example.com", "测试主题 Test Subject", "<html><body>你好 Hello</body></html>")
srv.close()

assert rcpt_addresses() == ["parent@example.com"], received
assert "no-reply@school.edu" in received["mail_from"], received

msg = BytesParser(policy=policy.default).parsebytes(received["raw"])
subject = str(msg["Subject"])
body = msg.get_body(preferencelist=("html",)).get_content()
assert "Test Subject" in subject, subject
assert "你好 Hello" in body, body
assert str(msg["To"]) == "parent@example.com"

print("OK: smtp_mailer.send_email delivered message end-to-end (subject/body decoded)")


# ---- 一格多个家长邮箱：一封邮件发给全部地址 ----
# 逗号与分号都要拆开：smtplib 不会自己拆，整串丢进 RCPT TO 会被服务器拒收（这正是改动前的行为）。
received["raw"] = b""
received["rcpt_to"].clear()
srv_multi, _ = run_server(1025)
smtp_mailer.send_email(
    "father@example.com; mother@example.com, FATHER@example.com", "多地址", "<p>hi</p>"
)
srv_multi.close()

assert rcpt_addresses() == ["father@example.com", "mother@example.com"], received["rcpt_to"]
msg = BytesParser(policy=policy.default).parsebytes(received["raw"])
assert str(msg["To"]) == "father@example.com, mother@example.com", msg["To"]
assert "多地址" in str(msg["Subject"]), msg["Subject"]

print("OK: 一格多个邮箱 → 一封邮件里全部作为收件人（去重 / To 头规范化）")


# ---- 建连失败的重试（见 smtp_mailer.CONNECT_RETRY_DELAYS）----
# 生产上真实发生过的形态：新建容器里第一次解析 SMTP 域名就 `Name or service not known`，
# 整批因此一封都没发出去，隔一分钟再点一次「发送」才成功。

_real_open = smtp_mailer._open
_real_delays = smtp_mailer.CONNECT_RETRY_DELAYS
_saved_smtp_user = config.SMTP_USER
_retry_error = "连接 SMTP 服务器失败：[Errno -2] Name or service not known"
smtp_mailer.CONNECT_RETRY_DELAYS = (0, 0)  # 测试里不真等


def _expect_mailer_error(action, why):
    try:
        action()
    except smtp_mailer.MailerError as e:
        return str(e)
    raise AssertionError(why)


# 1) 第一次解析失败、第二次成功：整批照常发出去（这正是要防的场景）
_flaky = {"opens": 0}
srv_retry, _ = run_server(1025)


def _flaky_open():
    _flaky["opens"] += 1
    if _flaky["opens"] == 1:
        raise smtp_mailer.MailerError(_retry_error)
    return _real_open()


smtp_mailer._open = _flaky_open
received["raw"] = b""
received["rcpt_to"].clear()
smtp_mailer.send_email("parent@example.com", "重试测试 Retry", "<p>hi</p>")
srv_retry.close()
smtp_mailer._open = _real_open

assert _flaky["opens"] == 2, _flaky
assert rcpt_addresses() == ["parent@example.com"], received
assert received["raw"], "重试之后应当真的投出去一封"

# 2) 一直连不上：只试 3 次（首次 + 2 次重试）就放弃，原始原因照原样抛出
_always = {"opens": 0}


def _always_fail():
    _always["opens"] += 1
    raise smtp_mailer.MailerError(_retry_error)


smtp_mailer._open = _always_fail
err = _expect_mailer_error(
    lambda: smtp_mailer.send_email("parent@example.com", "x", "<p>x</p>"),
    "建连始终失败时应当抛 MailerError",
)
assert _always["opens"] == len(_real_delays) + 1, _always
assert _retry_error in err, err


# 3) 登录失败不重试：凭据错是持续性的，重试只是让人多等 7 秒才看到原因
class _LoginFailServer:
    def __init__(self):
        self.logins = 0

    def login(self, user, password):
        self.logins += 1
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def quit(self):
        pass


_login_fail = _LoginFailServer()
smtp_mailer._open = lambda: _login_fail
config.SMTP_USER = "someone@school.edu"
err = _expect_mailer_error(
    lambda: smtp_mailer.send_email("parent@example.com", "x", "<p>x</p>"),
    "登录失败时应当抛 MailerError",
)
assert _login_fail.logins == 1, _login_fail
assert "SMTP 登录失败" in err, err

smtp_mailer._open = _real_open
smtp_mailer.CONNECT_RETRY_DELAYS = _real_delays
config.SMTP_USER = _saved_smtp_user

print("OK: SMTP 建连瞬时失败会退避重试；一直失败或登录失败则不重试")
