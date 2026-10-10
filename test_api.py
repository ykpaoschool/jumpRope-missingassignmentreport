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
