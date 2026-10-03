"""验证家长邮箱列识别：构造含 N 列邮箱的 xlsx，确认解析正确。"""

from io import BytesIO

from openpyxl import Workbook

from app.excel_parser import parse_workbook


def build_xlsx(header_n):
    wb = Workbook()
    ws = wb.active
    headers = [
        "Student External Id", "Student Current Grade Level", "Student Official Class",
        "Advisor Last First", "School Short Code", "Section Course Name",
        "Section External Id", "Section Teacher Name", "Assessment Type Name",
        "Assessment Title", "Assessment Due Date", "Missing Work Code",
        "Missing Work Comment", header_n,
    ]
    ws.append(headers)
    ws.append(["24311", "08", "2031", None, "YK Pao", "8 MATH 数学", "8H", "Sue Li",
               "Formative", "1.1.1 HW", 46273, "M", None, "parent@example.com"])
    ws.append(["24311", "08", "2031", None, "YK Pao", "8 MATH 数学", "8H", "Sue Li",
               "Formative", "Quiz 2", 46268, "M", None, "parent@example.com"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# 场景 1：N 列表头为任意非关键词文本，应回退到第 14 列
r1 = parse_workbook(build_xlsx("家长邮箱"))
assert len(r1["students"]) == 1, r1
s = r1["students"][0]
assert s["parent_email"] == "parent@example.com", s
assert len(s["items"]) == 2, s
assert s["items"][0]["due_date"] == "2026-09-08"

# 场景 2：N 列表头含 "email" 关键词，应识别为邮箱列
r2 = parse_workbook(build_xlsx("Parent Email"))
assert r2["students"][0]["parent_email"] == "parent@example.com"

# 场景 3：N 列留空 → 标记缺邮箱
from openpyxl import Workbook as _WB
wb = _WB(); ws = wb.active
ws.append(["Student External Id", "Student Current Grade Level", "Student Official Class",
           "Advisor Last First", "School Short Code", "Section Course Name",
           "Section External Id", "Section Teacher Name", "Assessment Type Name",
           "Assessment Title", "Assessment Due Date", "Missing Work Code",
           "Missing Work Comment", "Parent Email"])
ws.append(["24311", "08", "2031", None, "YK Pao", "8 MATH 数学", "8H", "Sue Li",
           "Formative", "1.1.1 HW", 46273, "M", None, None])
buf = BytesIO(); wb.save(buf)
r3 = parse_workbook(buf.getvalue())
assert r3["students"][0]["parent_email"] == ""
assert any("缺少家长邮箱" in w for w in r3["warnings"])

print("OK: parent email column detection (N / header keyword / empty) all pass")


# 场景 4：学生姓名列（整名列 / First+Last 拼接 / 完全缺失）
BASE = ["Student External Id", "Student Current Grade Level", "Student Official Class",
        "Advisor Last First", "School Short Code", "Section Course Name",
        "Section External Id", "Section Teacher Name", "Assessment Type Name",
        "Assessment Title", "Assessment Due Date", "Missing Work Code",
        "Missing Work Comment", "Parent Email"]


def build_with(extra_headers, extra_values):
    wb = Workbook(); ws = wb.active
    ws.append(BASE + extra_headers)
    ws.append(["24311", "08", "2031", None, "YK Pao", "8 MATH 数学", "8H", "Sue Li",
               "Formative", "1.1.1 HW", 46273, "M", None, "parent@example.com"] + extra_values)
    buf = BytesIO(); wb.save(buf)
    return buf.getvalue()


# 4a：First + Last 分列 → 拼接
r4a = parse_workbook(build_with(["Student First Name", "Student Last Name"], ["San", "Zhang"]))
assert r4a["students"][0]["student_name"] == "San Zhang", r4a["students"][0]

# 4b：单一 Student Name 列
r4b = parse_workbook(build_with(["Student Name"], ["Zhang San"]))
assert r4b["students"][0]["student_name"] == "Zhang San", r4b["students"][0]

# 4c：完全没有姓名列 → 空字符串 + 警告
r4c = parse_workbook(build_with([], []))
assert r4c["students"][0]["student_name"] == ""
assert any("学生姓名" in w for w in r4c["warnings"]), r4c["warnings"]

print("OK: student name columns (full / first+last / missing) all pass")
