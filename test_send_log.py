"""验证发送日志（SQLite）：落库字段、读取与筛选、迁移幂等、失败降级、跨线程。

库文件一律指向临时目录——绝不能碰 data/mailer.db（那是真实运行数据）。
沿用仓库既有风格：纯脚本 + assert，跑通打印 OK。
"""

import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime

from app import config, db, send_job, send_log

TMP = tempfile.mkdtemp(prefix="send-log-test-")
config.DB_PATH = os.path.join(TMP, "unused.db")
config.SEND_DELAY_SECONDS = 0


def use_db(name: str) -> str:
    """换一个干净的库文件：db 模块按路径重新初始化（不缓存路径）。"""
    config.DB_PATH = os.path.join(TMP, name)
    return config.DB_PATH


def fetch(sql: str = "SELECT * FROM send_log ORDER BY id", params: tuple = ()) -> list[dict]:
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]


def seed_send(student_id: str, ok: bool, day: str | None = None, **extra) -> None:
    entry = {
        "event": "send",
        "job_id": "job-a",
        "mode": "live",
        "channel": "graph",
        "student_id": student_id,
        "student_name": f"学生{student_id}",
        "grade": "08",
        "class_name": "2031",
        "item_count": 2,
        "recipient": f"{student_id}@example.com",
        "subject": "主题",
        "ok": 1 if ok else 0,
        "error": None if ok else "模拟失败",
    }
    if day:
        entry["day"] = day
    entry.update(extra)
    send_log.record(entry)


# ---- 1. 写入后字段落库正确（含中文、布尔、分析维度快照）----
use_db("basic.db")
send_log.record(
    {
        "event": "send",
        "job_id": "job-1",
        "mode": "live",
        "channel": "graph",
        "student_id": "1001",
        "student_name": "张三",
        "grade": "08",
        "class_name": "2031",
        "item_count": 3,
        "recipient": "parent@example.com",
        "subject": "[缺交作业通知] Missing Assignments Notification",
        "ok": 1,
        "duration_ms": 42,
    }
)
today = datetime.now().strftime("%Y-%m-%d")
rows = fetch()
assert len(rows) == 1, rows
r = rows[0]
assert r["event"] == "send" and r["job_id"] == "job-1", r
assert r["day"] == today and r["ts"].startswith(today), r
assert r["student_name"] == "张三" and r["class_name"] == "2031", r
assert r["grade"] == "08" and r["item_count"] == 3, r
assert r["ok"] == 1 and r["recipient"] == "parent@example.com", r
assert r["attempt"] == 1, r
assert len(fetch("SELECT * FROM send_log WHERE retry_of IS NULL")) == 1, "retry_of 应留空（重试机制未实现）"

# ---- 2. read()：最新在前、limit 生效并置 truncated、counts 正确 ----
use_db("read.db")
send_log.record({"event": "job_start", "job_id": "job-b", "mode": "live", "channel": "graph", "total": 3})
seed_send("2001", True, job_id="job-b")
seed_send("2002", False, job_id="job-b")
seed_send("2003", True, job_id="job-b")
send_log.record({"event": "job_end", "job_id": "job-b", "mode": "live", "channel": "graph", "status": "done", "sent": 2, "failed": 1})

data = send_log.read()
assert data["date"] == today and data["truncated"] is False, data
assert [e["event"] for e in data["entries"]] == ["job_end", "send", "send", "send", "job_start"], data["entries"]
assert data["entries"][1]["student_id"] == "2003", "应按 id 倒序（最新在前）"
assert data["counts"] == {"send": 3, "ok": 2, "failed": 1, "jobs": 1}, data["counts"]

limited = send_log.read(limit=2)
assert len(limited["entries"]) == 2 and limited["truncated"] is True, limited
assert limited["counts"]["send"] == 3, "limit 只截断 entries，counts 仍是整天数字"

# ---- 3. ok 三种筛选语义（整批没发出去也算失败）----
use_db("filter.db")
seed_send("3001", True, job_id="job-c")
seed_send("3002", False, job_id="job-c")
send_log.record({"event": "job_end", "job_id": "job-c", "status": "done", "sent": 1, "failed": 1})
send_log.record({"event": "job_end", "job_id": "job-d", "status": "failed", "error": "连接 SMTP 服务器失败"})

assert len(send_log.read(ok="all")["entries"]) == 4, send_log.read(ok="all")
assert [e["student_id"] for e in send_log.read(ok="ok")["entries"]] == ["3001"]
failed = send_log.read(ok="fail")["entries"]
assert len(failed) == 2, failed
assert {e["job_id"] for e in failed} == {"job-c", "job-d"}, failed
assert send_log.read(ok="fail")["counts"]["failed"] == 2, send_log.read(ok="fail")["counts"]
assert send_log.read(ok="不认识的取值")["counts"]["send"] == 2, "未知筛选值按「全部」处理"

# ---- 4. dates：去重、新日期在前；不存在的日期返回空且不抛 ----
use_db("dates.db")
seed_send("4001", True, day="2026-01-02")
seed_send("4002", True, day="2026-01-03")
seed_send("4003", False, day="2026-01-03")

data = send_log.read()
assert data["dates"] == ["2026-01-03", "2026-01-02"], data["dates"]
assert data["date"] == "2026-01-03", "不指定日期时取最近有记录的一天，而不是今天"
assert len(data["entries"]) == 2, data["entries"]

empty = send_log.read(day="1999-12-31")
assert empty["date"] == "1999-12-31" and empty["entries"] == [], empty
assert empty["counts"] == {"send": 0, "ok": 0, "failed": 0, "jobs": 0}, empty
assert empty["dates"] == ["2026-01-03", "2026-01-02"], "看别的日期时下拉框仍要给出全部日期"
assert send_log.read(day="1999-12-31", ok="fail")["entries"] == [], "空日期叠加筛选也不能报错"

# ---- 5. init() 幂等：重复调用不重建表、不丢数据，user_version == 1 ----
before = fetch()
for _ in range(3):
    assert db.init() is True
assert fetch() == before, "重复 init 不能丢数据"
with sqlite3.connect(config.DB_PATH) as conn:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
assert version == db.SCHEMA_VERSION == 1, version
# 迁移用 user_version 而不是「建表语句里加列」：老库列已存在时 CREATE TABLE IF NOT EXISTS
# 什么也不做，改了建表语句对老库无效
assert {r["name"] for r in fetch("PRAGMA table_info(send_log)")} >= {"attempt", "retry_of", "class_name", "item_count"}

# ---- 6. 库不可写：record() 不抛、status() 报出错误、read() 优雅降级 ----
bad_path = os.path.join(TMP, "not-a-dir", "mailer.db")
with open(os.path.join(TMP, "not-a-dir"), "w"):
    pass  # 父路径是个普通文件 → 建库必然失败
config.DB_PATH = bad_path
send_log.record({"event": "send", "ok": 1})  # 关键：不能抛，绝不能连累发信
st = send_log.status()
assert st["ready"] is False and st["error"], st
assert st["path"] == bad_path, st
degraded = send_log.read()
assert degraded["entries"] == [] and degraded["db"]["ready"] is False, degraded
assert degraded["db"]["error"], "页面要靠它挂红色横幅，不能只是静默地空着"

# ---- 7. 集成：假 mailer 跑一次 send_job，三类 event 齐全 ----
use_db("job.db")
send_job._job = None


class FakeMailer:
    """最小 mailer：session() 返回自身，可注入「哪些收件人必失败」。"""

    def __init__(self, fail_for=(), fail_open=None):
        self.fail_for = set(fail_for)
        self.fail_open = fail_open

    def session(self):
        return self

    def __enter__(self):
        if self.fail_open is not None:
            raise self.fail_open
        return self

    def __exit__(self, *exc):
        return False

    def send(self, recipient, subject, html_body):
        if recipient in self.fail_for:
            raise RuntimeError(f"模拟失败：{recipient}")


def target(sid: str, to: str | None = None) -> dict:
    return {
        "student_id": sid,
        "name": f"学生{sid}",
        "to": to or f"{sid}@example.com",
        "subject": f"主题 {sid}",
        "html": f"<p>{sid}</p>",
        "grade": "08",
        "class": "2031",
        "item_count": 4,
    }


def wait_done(timeout=5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = send_job.snapshot()
        if job is not None and job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError(f"任务在 {timeout}s 内未结束：{send_job.snapshot()}")


job = send_job.start(
    [target("5001"), target("5002"), target("5003")],
    FakeMailer(fail_for={"5002@example.com"}),
    mode="live",
    channel="smtp",
    meta={"filename": "Missing_Work_Report.xlsx", "email_column": 13, "email_column_header": "Parent Email"},
)
# 写库发生在后台线程里，这里在主线程读——顺带就是跨线程用例（连接不跨线程共用）
final = wait_done()
assert final["status"] == "done", final

rows = fetch("SELECT * FROM send_log WHERE job_id = ? ORDER BY id", (job["id"],))
assert [r["event"] for r in rows] == ["job_start", "send", "send", "send", "job_end"], rows

start_row = rows[0]
assert start_row["total"] == 3, start_row
assert start_row["filename"] == "Missing_Work_Report.xlsx", start_row
assert start_row["email_column"] == 13 and start_row["email_column_header"] == "Parent Email", start_row
assert start_row["mode"] == "live" and start_row["channel"] == "smtp" and start_row["job_id"] == job["id"], start_row

sends = rows[1:4]
assert [s["student_id"] for s in sends] == ["5001", "5002", "5003"], sends
bad = sends[1]
assert bad["ok"] == 0 and "模拟失败" in bad["error"], bad
assert [s["ok"] for s in sends] == [1, 0, 1], sends
assert sends[0]["recipient"] == "5001@example.com" and sends[0]["subject"] == "主题 5001", sends[0]
assert all(s["grade"] == "08" and s["class_name"] == "2031" and s["item_count"] == 4 for s in sends), sends
assert all(isinstance(s["duration_ms"], int) for s in sends), "每封都要记耗时"

end_row = rows[4]
assert end_row["status"] == "done" and end_row["sent"] == 2 and end_row["failed"] == 1, end_row
assert isinstance(end_row["duration_ms"], int), end_row

# 连接阶段就失败：一封都没发，日志里靠 job_end(failed) 留下痕迹
send_job._job = None
job2 = send_job.start(
    [target("5101"), target("5102")],
    FakeMailer(fail_open=RuntimeError("连接 SMTP 服务器失败：模拟")),
    mode="live",
    channel="smtp",
)
assert wait_done()["status"] == "failed"
rows2 = fetch("SELECT * FROM send_log WHERE job_id = ? ORDER BY id", (job2["id"],))
assert [r["event"] for r in rows2] == ["job_start", "job_end"], rows2
assert rows2[1]["status"] == "failed" and "模拟" in rows2[1]["error"], rows2[1]
assert send_log.read(ok="fail")["counts"]["failed"] == 2, "失败封数 1 + 整批未发出 1"

# ---- 8. 跨线程：多个线程同时写（且同时首次初始化）、主线程读，不出现 SQLite 跨线程错误 ----
use_db("threads.db")  # 新库：4 个线程会同时第一次触发 init()，初始化必须单飞
errors = []


def writer(n: int) -> None:
    try:
        for i in range(25):
            seed_send(f"{n}{i:02d}", i % 2 == 0, job_id=f"job-{n}")
    except Exception as e:  # noqa: BLE001 — 记下来，别让线程里静默失败
        errors.append(e)


threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()

assert not errors, errors
assert send_log.status()["ready"] is True, send_log.status()
assert len(fetch()) == 100, len(fetch())
# 每个线程 25 封，i 为偶数成功（0…24 共 13 封），4 个线程合计 52 成功 / 48 失败
assert send_log.read(limit=1000)["counts"] == {"send": 100, "ok": 52, "failed": 48, "jobs": 0}, send_log.read(limit=1000)["counts"]

print("OK: 发送日志落库字段（中文/分析维度快照/attempt/retry_of 预留）正确")
print("OK: read() 倒序 / limit+truncated / counts / 三种筛选语义 / dates 与空日期降级")
print("OK: init() 幂等且 user_version=1；库不可写时 record 不抛、status 报错、read 优雅降级")
print("OK: send_job 集成（job_start/send/job_end 齐全，含整批失败）+ 跨线程读写")
