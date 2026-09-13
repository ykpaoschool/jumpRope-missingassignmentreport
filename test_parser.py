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
