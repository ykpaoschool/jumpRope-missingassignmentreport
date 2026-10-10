"""验证收件邮箱列相关接口：上传 → 摘要 → 切换列 → 列表/预览同步刷新；以及发送日志接口。

用 FastAPI 的 TestClient 直接打接口，不启动真实服务、不发信。
"""

import os
import tempfile
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import config, main, send_log

# 发送日志接口会碰库：指向临时文件，避免创建/读取真实的 data/mailer.db
config.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="api-test-"), "mailer.db")

client = TestClient(main.app)

STUDENTS = 6
BASE_13 = ["Student External Id", "Student Current Grade Level", "Student Official Class",
           "Advisor Last First", "School Short Code", "Section Course Name",
           "Section External Id", "Section Teacher Name", "Assessment Type Name",
           "Assessment Title", "Assessment Due Date", "Missing Work Code",
           "Missing Work Comment"]


def build_xlsx() -> bytes:
    """N 列（下标 13）为 Advisor Email 只有 1 条，O 列（下标 14）为 Parent Email 有 6 条。"""
    wb = Workbook(); ws = wb.active
    ws.append(BASE_13 + ["Advisor Email", "Parent Email"])
    for i in range(STUDENTS):
        ws.append([f"1000{i}", "08", "2031", None, "YK Pao", "8 MATH 数学", "8H", "Sue Li",
                   "Formative", "1.1.1 HW", 46273, "M", None,
                   "advisor@example.com" if i == 0 else None, f"parent{i}@example.com"])
    buf = BytesIO(); wb.save(buf)
    return buf.getvalue()


# 1. 未上传时摘要为空，且不允许切换列
s = client.get("/api/summary").json()
assert s["uploaded"] is False and s["email_column"] is None, s
assert client.post("/api/email-column", json={"column": 14}).status_code == 400

# 2. 上传 → 默认选中第一个命中关键词的列（Advisor Email）
r = client.post("/api/upload", files={"file": ("test.xlsx", build_xlsx())})
assert r.status_code == 200, r.text
s = r.json()
assert s["uploaded"] is True and s["total_students"] == STUDENTS, s
assert s["email_column"] == 13 and s["email_column_info"]["header"] == "Advisor Email", s
assert [c["index"] for c in s["email_columns"]] == [13, 14], s["email_columns"]
assert s["with_email"] == 1, s

students = client.get("/api/students").json()
assert students[0]["parent_email"] == "advisor@example.com", students[0]
assert all(x["parent_email"] == "" for x in students[1:]), students

# 3. 切到 Parent Email 列 → 摘要、列表、预览一起刷新
r = client.post("/api/email-column", json={"column": 14})
assert r.status_code == 200, r.text
s = r.json()
assert s["email_column"] == 14 and s["with_email"] == STUDENTS and s["no_email"] == [], s

students = client.get("/api/students").json()
assert [x["parent_email"] for x in students] == [f"parent{i}@example.com" for i in range(STUDENTS)], students

pv = client.get("/api/preview/10003").json()
assert pv["parent_email"] == "parent3@example.com", pv

# 4. 页面重开时靠 /api/summary 恢复当前选择
s = client.get("/api/summary").json()
assert s["uploaded"] is True and s["email_column"] == 14 and s["with_email"] == STUDENTS, s

# 5. 非法列号 / 坏文件都要报 400
bad = client.post("/api/email-column", json={"column": 99})
assert bad.status_code == 400 and "收件邮箱列" in bad.json()["detail"], bad.text
assert client.post("/api/upload", files={"file": ("bad.xlsx", b"not an xlsx")}).status_code == 400

# 6. 切换列不改变发送队列的取值口径：/api/send 用的就是这份列表
assert all(x["parent_email"] for x in client.get("/api/students").json())

# 7. 发送日志接口：空库时结构齐全、不含记录
lg = client.get("/api/logs").json()
assert set(lg) == {"date", "entries", "counts", "truncated", "dates", "db"}, lg
assert lg["entries"] == [] and lg["dates"] == [] and lg["truncated"] is False, lg
assert lg["counts"] == {"send": 0, "ok": 0, "failed": 0, "jobs": 0}, lg
assert lg["db"]["ready"] is True and lg["db"]["path"].endswith("mailer.db"), lg["db"]

# 8. 有记录后：默认取最近一天，筛选与 limit 参数生效
send_log.record(
    {
        "event": "send",
        "job_id": "job-api",
        "mode": "live",
        "channel": "graph",
        "student_id": "10001",
        "student_name": "李四",
        "grade": "08",
        "class_name": "2031",
        "item_count": 1,
        "recipient": "parent0@example.com",
        "subject": "主题",
        "ok": 1,
    }
)
send_log.record(
    {
        "event": "send",
        "job_id": "job-api",
        "mode": "live",
        "channel": "graph",
        "student_id": "10002",
        "recipient": "parent1@example.com",
        "subject": "主题",
        "ok": 0,
        "error": "模拟失败",
    }
)
send_log.record({"event": "job_end", "job_id": "job-api", "status": "done", "sent": 1, "failed": 1})

lg = client.get("/api/logs").json()
assert len(lg["entries"]) == 3 and lg["counts"]["send"] == 2, lg
assert lg["entries"][0]["event"] == "job_end", "最新在前"
assert lg["entries"][1]["recipient"] == "parent1@example.com" and lg["entries"][1]["ok"] == 0, lg["entries"][1]
assert lg["entries"][2]["class_name"] == "2031" and lg["entries"][2]["item_count"] == 1, lg["entries"][2]

only_fail = client.get("/api/logs", params={"ok": "fail"}).json()
assert [e["student_id"] for e in only_fail["entries"]] == ["10002"], only_fail
assert client.get("/api/logs", params={"ok": "ok"}).json()["counts"]["send"] == 2, "counts 不受筛选影响"
assert client.get("/api/logs", params={"limit": 1}).json()["truncated"] is True
assert client.get("/api/logs", params={"date": "1999-12-31"}).json()["entries"] == []

print("OK: email column API (upload / switch / restore / invalid) all pass")
print("OK: send log API (empty / records / filter / limit / unknown date) all pass")


# 9. 一格多个家长邮箱：接口暴露的字段、汇总，以及「地址无法识别就暂停整批」
STUDENTS_MULTI = 6


def build_multi_xlsx() -> bytes:
    """N 列：两名学生一格两个地址（分号 / 逗号），一名学生混了无法识别的片段，其余各一个地址。"""
    wb = Workbook(); ws = wb.active
    ws.append(BASE_13 + ["Parent Email"])
    for i in range(STUDENTS_MULTI):
        email = [
            "father0@example.com; mother0@example.com",
            "father1@example.com, mother1@example.com",
            "father2@example.com; 张先生",
            "parent3@example.com",
            "parent4@example.com",
            "parent5@example.com",
        ][i]
        ws.append([f"3000{i}", "08", "2031", None, "YK Pao", "8 MATH 数学", "8H", "Sue Li",
                   "Formative", "1.1.1 HW", 46273, "M", None, email])
    buf = BytesIO(); wb.save(buf)
    return buf.getvalue()


r = client.post("/api/upload", files={"file": ("multi.xlsx", build_multi_xlsx())})
assert r.status_code == 200, r.text
s = r.json()
assert s["total_students"] == STUDENTS_MULTI and s["with_email"] == STUDENTS_MULTI, s
assert s["total_recipients"] == 9, s  # 一个学生多个地址时，地址数与学生数并不相等
assert s["email_column_info"]["email_count"] == STUDENTS_MULTI, s["email_column_info"]
assert s["email_column_info"]["address_count"] == 8, s["email_column_info"]  # 非法片段不计入
assert any("发送会被暂停" in w and "30002" in w for w in s["warnings"]), s["warnings"]

students = client.get("/api/students").json()
assert [x["recipient_count"] for x in students] == [2, 2, 2, 1, 1, 1], students
assert students[0]["parent_email"] == "father0@example.com, mother0@example.com", students[0]
assert students[2]["invalid_addresses"] == ["张先生"], students[2]
assert all(x["invalid_addresses"] == [] for x in students if x["student_id"] != "30002"), students

# 把任务启动换成记账本：本文件不发信，但要确认交给后台任务的是哪些收件地址
captured = {}
_real_start = main.send_job.start


def fake_start(targets, mailer, mode, channel, meta=None):
    captured["targets"] = targets
    return {"id": "job-api-test", "total": len(targets)}


main.send_job.start = fake_start

# 9a. 正式发送：含无法识别的地址 → 400，且任务根本没启动（不是发一半）
r = client.post("/api/send", json={"mode": "live", "channel": "smtp"})
assert r.status_code == 400, r.text
detail = r.json()["detail"]
assert "30002" in detail and "张先生" in detail and "已暂停" in detail, detail
assert captured == {}, "被拦下的批次不应启动任务"

# 9b. 取消勾选问题学生后照常发送；多个地址原样交给任务（拆分由 mailer 负责）
r = client.post(
    "/api/send",
    json={"mode": "live", "channel": "smtp", "student_ids": ["30000", "30001", "30003"]},
)
assert r.status_code == 202, r.text
assert r.json() == {"job_id": "job-api-test", "total": 3}, r.json()
assert [t["to"] for t in captured["targets"]] == [
    "father0@example.com, mother0@example.com",
    "father1@example.com, mother1@example.com",
    "parent3@example.com",
], captured["targets"]

# 9c. 测试邮箱同样要校验，一样是拦下而不是发出去
captured.clear()
bad = client.post("/api/send", json={"mode": "test", "channel": "smtp", "test_email": "not-an-email"})
assert bad.status_code == 400 and "测试邮箱地址无效" in bad.json()["detail"], bad.text
assert client.post(
    "/api/send", json={"mode": "test", "channel": "smtp", "test_email": "   "}
).status_code == 400
assert captured == {}

# 9d. 测试邮箱可以是多个地址（由 mailer 拆开）
r = client.post(
    "/api/send",
    json={"mode": "test", "channel": "smtp", "test_email": "me@example.com; me2@example.com",
          "student_ids": ["30000"]},
)
assert r.status_code == 202, r.text
assert captured["targets"][0]["to"] == "me@example.com; me2@example.com", captured["targets"]

main.send_job.start = _real_start

print("OK: 一格多个邮箱与非法地址（字段 / 汇总 / 暂停整批 / 取消勾选后可发）all pass")
