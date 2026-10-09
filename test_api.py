"""验证收件邮箱列相关接口：上传 → 摘要 → 切换列 → 列表/预览同步刷新。

用 FastAPI 的 TestClient 直接打接口，不启动真实服务、不发信。
"""

from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import main

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

print("OK: email column API (upload / switch / restore / invalid) all pass")
