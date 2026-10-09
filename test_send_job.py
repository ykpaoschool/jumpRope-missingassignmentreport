"""验证 send_job 的任务状态机与两个 mailer 的连接复用。

状态机部分用假 mailer，不碰网络；连接复用部分在端口 1026 起一个最小 SMTP 服务器。
"""

import json
import os
import socket
import tempfile
import threading
import time
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import config, graph_mailer, send_job, smtp_mailer

# 加速：任务之间不再 sleep
config.SEND_DELAY_SECONDS = 0

# 发送日志会写库：指向临时文件，别把测试数据灌进真实的 data/mailer.db
config.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="send-job-test-"), "mailer.db")


class FakeMailer:
    """最小 mailer：session() 复用同一个 sender，可注入「哪些收件人必失败」。"""

    def __init__(self, fail_for=(), fail_open=None, block=None):
        self.fail_for = set(fail_for)
        self.fail_open = fail_open  # 进入 session 时抛出的异常
        self.block = block  # threading.Event，用于把任务卡在 running 状态
        self.sessions = 0
        self.sent = []

    def session(self):
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, mailer):
        self.mailer = mailer

    def __enter__(self):
        if self.mailer.fail_open is not None:
            raise self.mailer.fail_open
        self.mailer.sessions += 1
        return self

    def __exit__(self, *exc):
        return False

    def send(self, recipient, subject, html_body):
        if self.mailer.block is not None:
            assert self.mailer.block.wait(timeout=5), "block 事件未被释放"
        if recipient in self.mailer.fail_for:
            raise RuntimeError(f"模拟失败：{recipient}")
        self.mailer.sent.append((recipient, subject))


def targets(*ids, to=None):
    return [
        {
            "student_id": i,
            "name": f"学生{i}",
            "to": to or f"{i}@example.com",
            "subject": f"主题 {i}",
            "html": f"<p>{i}</p>",
        }
        for i in ids
    ]


def wait_done(timeout=5.0):
    """轮询等待任务离开 running 状态。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = send_job.snapshot()
        if job is not None and job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError(f"任务在 {timeout}s 内未结束：{send_job.snapshot()}")


def reset():
    """每个用例开始前清空上一次任务（模块级单任务状态）。"""
    send_job._job = None


# ---- 1. 正常整批：状态流转、计数、逐条结果 ----
reset()
mailer = FakeMailer()
job = send_job.start(targets("1001", "1002", "1003"), mailer, mode="test", channel="smtp")
assert job["status"] == "running", job
assert job["total"] == 3 and job["sent"] == 0 and job["results"] == [], job
assert job["id"] and job["started_at"] and job["finished_at"] is None, job

final = wait_done()
assert final["status"] == "done", final
assert final["sent"] == 3 and final["failed"] == 0, final
assert len(final["results"]) == 3 and all(r["ok"] for r in final["results"]), final
assert [r["student_id"] for r in final["results"]] == ["1001", "1002", "1003"], final
assert final["current"] == "" and final["error"] is None, final
assert final["finished_at"], final
assert mailer.sessions == 1, "整批应只建立一次 session"
assert [addr for addr, _ in mailer.sent] == ["1001@example.com", "1002@example.com", "1003@example.com"]

# 结束后 snapshot() 仍可用（页面重开要看最近一次结果），且是深拷贝
after = send_job.snapshot()
after["results"].append({"bogus": True})
assert len(send_job.snapshot()["results"]) == 3, "snapshot 必须返回深拷贝"

# ---- 2. 单封失败不影响后续，且逐条记录原因 ----
reset()
mailer = FakeMailer(fail_for=["1002@example.com"])
send_job.start(targets("1001", "1002", "1003"), mailer, mode="live", channel="graph")
final = wait_done()
assert final["status"] == "done", final
assert final["sent"] == 2 and final["failed"] == 1, final
assert [r["ok"] for r in final["results"]] == [True, False, True], final
bad = final["results"][1]
assert bad["student_id"] == "1002" and "模拟失败" in bad["error"], bad
assert len(mailer.sent) == 2, "失败的收件人不计入已发送"

# ---- 3. 任务进行中再次提交 → JobBusyError ----
reset()
block = threading.Event()
mailer = FakeMailer(block=block)
first = send_job.start(targets("2001", "2002"), mailer, mode="live", channel="smtp")
try:
    send_job.start(targets("9999"), FakeMailer(), mode="live", channel="smtp")
    raise AssertionError("并发提交未被拒绝")
except send_job.JobBusyError as e:
    assert "进行中" in str(e), e
# 被拒绝的请求不能改动当前任务
assert send_job.snapshot()["id"] == first["id"], send_job.snapshot()
block.set()
final = wait_done()
assert final["status"] == "done" and final["total"] == 2, final

# ---- 4. 任务完成后锁释放，可以再次提交 ----
reset()
send_job.start(targets("3001"), FakeMailer(), mode="test", channel="smtp")
assert wait_done()["status"] == "done"
second = send_job.start(targets("3002"), FakeMailer(), mode="test", channel="smtp")
assert second["id"] != "" and wait_done()["sent"] == 1

# ---- 5. 连接阶段就失败：整批 failed + 原因，而不是 N 条收件人失败 ----
reset()
mailer = FakeMailer(fail_open=RuntimeError("连接 SMTP 服务器失败：模拟"))
send_job.start(targets("4001", "4002"), mailer, mode="live", channel="smtp")
final = wait_done()
assert final["status"] == "failed", final
assert "模拟" in final["error"], final
assert final["results"] == [] and final["sent"] == 0 and final["failed"] == 0, final
assert final["total"] == 2 and final["finished_at"], final

# ---- 6. 无任务时 snapshot() 为 None ----
reset()
assert send_job.snapshot() is None


# ---- SMTP 渠道：一条连接发完整批 ----
class FakeSmtpServer:
    """最小 SMTP 服务器：接受多条连接，记录每封正文，可选把第一条连接在 N 封后掐断。"""

    def __init__(self, port, close_after=None):
        self.close_after = close_after
        self.connections = 0
        self.messages = []
        self._dropped = False
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", port))
        self._sock.listen(5)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return  # 套接字已关闭
            with self._lock:
                self.connections += 1
                index = self.connections
            threading.Thread(target=self._handle, args=(conn, index), daemon=True).start()

    def _handle(self, conn, index):
        f = conn.makefile("rwb", buffering=0)
        f.write(b"220 localhost ESMTP\r\n")
        raw = b""
        in_data = False
        sent_here = 0
        while True:
            line = f.readline()
            if not line:
                break
            if in_data:
                if line.rstrip(b"\r\n") == b".":
                    in_data = False
                    with self._lock:
                        self.messages.append(raw)
                    sent_here += 1
                    f.write(b"250 queued\r\n")
                    if self.close_after and index == 1 and sent_here >= self.close_after:
                        with self._lock:
                            if not self._dropped:
                                self._dropped = True
                                time.sleep(0.05)  # 让 250 先到达客户端，再模拟掐断长连接
                                break
                else:
                    raw += line
                continue
            u = line.upper()
            if u.startswith(b"MAIL FROM"):
                raw = b""
                f.write(b"250 OK\r\n")
            elif u.startswith(b"RCPT TO"):
                f.write(b"250 OK\r\n")
            elif u.startswith(b"DATA"):
                f.write(b"354 go ahead\r\n")
                in_data = True
            elif u.startswith(b"QUIT"):
                f.write(b"221 bye\r\n")
                break
            elif u.startswith((b"EHLO", b"HELO")):
                f.write(b"250 localhost\r\n")
            else:
                f.write(b"250 OK\r\n")
        conn.close()

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


# 注入测试配置
config.SMTP_HOST = "127.0.0.1"
config.SMTP_PORT = 1026
config.SMTP_FROM = "no-reply@school.edu"
config.SMTP_USER = ""
config.SMTP_PASSWORD = ""
config.SMTP_STARTTLS = False

# ---- 7. 一次 session 连发 3 封，服务端只应看到 1 条连接 ----
srv = FakeSmtpServer(1026)
with smtp_mailer.session() as s:
    for i in range(3):
        s.send(f"parent{i}@example.com", f"主题 {i}", f"<p>hi {i}</p>")

assert srv.connections == 1, f"整批应复用一条连接，实际建了 {srv.connections} 条"
assert len(srv.messages) == 3, len(srv.messages)
subjects = [str(BytesParser(policy=policy.default).parsebytes(m)["Subject"]) for m in srv.messages]
assert subjects == ["主题 0", "主题 1", "主题 2"], subjects

# send_email() 仍是同一套 session 的薄包装（既有接口不变）
smtp_mailer.send_email("single@example.com", "单封", "<p>one</p>")
assert len(srv.messages) == 4, len(srv.messages)
srv.close()

# ---- 8. 长连接被服务器掐断：自动重连并重试本封一次 ----
srv = FakeSmtpServer(1026, close_after=1)
with smtp_mailer.session() as s:
    for i in range(3):
        s.send(f"retry{i}@example.com", f"重试 {i}", "<p>x</p>")

assert srv.connections == 2, f"应在掐断后重连一次，实际建了 {srv.connections} 条连接"
assert len(srv.messages) == 3, f"重试不应丢信或重复投递，实际收到 {len(srv.messages)} 封"
srv.close()


# ---- Graph 渠道：429 限流退避重试 ----
graph_calls = []


class FakeGraphHandler(BaseHTTPRequestHandler):
    """按 statuses 顺序返回状态码（用完后一直返回最后一个），记录每次请求。"""

    statuses = [202]

    def do_POST(self):
        graph_calls.append(self.path)
        code = self.statuses[min(len(graph_calls) - 1, len(self.statuses) - 1)]
        body = json.dumps({"error": {"message": "Too many requests"}}).encode() if code != 202 else b""
        self.send_response(code)
        if code == 429:
            self.send_header("Retry-After", "0")  # 别让测试真的等
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


graph_srv = ThreadingHTTPServer(("127.0.0.1", 1027), FakeGraphHandler)
threading.Thread(target=graph_srv.serve_forever, daemon=True).start()

config.SHARED_MAILBOX = "shared@school.edu"
graph_mailer.GRAPH_BASE = "http://127.0.0.1:1027/v1.0"
# _get_app() 构造 MSAL 应用时会去 AAD 做 OIDC discovery，离线跑不了；
# 这里替换掉取凭据的两步，只验证 send() 的限流重试逻辑（token 缓存本身需连真实 AAD 才能验）
graph_mailer._get_app = lambda: object()
graph_mailer._get_token = lambda: "fake-token"

# 9. 先 429 后成功：重试一次即送达
FakeGraphHandler.statuses = [429, 202]
graph_mailer.send_email("parent@example.com", "主题", "<p>x</p>")
assert len(graph_calls) == 2, graph_calls
assert graph_calls[0].endswith("/users/shared@school.edu/sendMail"), graph_calls[0]

# 10. 持续 429：用尽重试次数后失败，且失败信息里带状态码
FakeGraphHandler.statuses = [429]
graph_calls.clear()
try:
    graph_mailer.send_email("parent@example.com", "主题", "<p>x</p>")
    raise AssertionError("持续限流应判为失败")
except graph_mailer.MailerError as e:
    assert "429" in str(e), e
assert len(graph_calls) == graph_mailer.MAX_RETRIES + 1, graph_calls

# 11. 非限流错误不重试，直接失败
FakeGraphHandler.statuses = [500]
graph_calls.clear()
try:
    graph_mailer.send_email("parent@example.com", "主题", "<p>x</p>")
    raise AssertionError("500 应判为失败")
except graph_mailer.MailerError as e:
    assert "500" in str(e), e
assert len(graph_calls) == 1, "非限流错误不应重试"
graph_srv.shutdown()

print("OK: send_job 状态机 / 单任务并发拒绝 / 单封失败隔离 / 连接失败整批标记")
print("OK: SMTP 一次 session 复用一条连接 / 断线自动重连重试")
print("OK: Graph 429 限流按 Retry-After 重试 / 用尽重试后失败 / 非限流错误不重试")
