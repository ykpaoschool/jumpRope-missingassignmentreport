"""用最小 SMTP 服务器验证 smtp_mailer 端到端发送。"""

import socket
import threading
from email import policy
from email.parser import BytesParser

from app import config, smtp_mailer

received = {"raw": b"", "mail_from": "", "rcpt_to": ""}


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
                received["rcpt_to"] = line.decode(errors="replace").strip()
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

srv, t = run_server(1025)

smtp_mailer.send_email("parent@example.com", "测试主题 Test Subject", "<html><body>你好 Hello</body></html>")
srv.close()

assert "parent@example.com" in received["rcpt_to"], received
assert "no-reply@school.edu" in received["mail_from"], received

msg = BytesParser(policy=policy.default).parsebytes(received["raw"])
subject = str(msg["Subject"])
body = msg.get_body(preferencelist=("html",)).get_content()
assert "Test Subject" in subject, subject
assert "你好 Hello" in body, body
assert str(msg["To"]) == "parent@example.com"

print("OK: smtp_mailer.send_email delivered message end-to-end (subject/body decoded)")
