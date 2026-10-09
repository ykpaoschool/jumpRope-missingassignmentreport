"""验证 send_job 的任务状态机（用假 mailer，不碰真实网络）。"""

import threading
import time

from app import config, send_job

# 加速：任务之间不再 sleep
config.SEND_DELAY_SECONDS = 0


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

print("OK: send_job 状态机 / 单任务并发拒绝 / 单封失败隔离 / 连接失败整批标记")
