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


# 场景 5：多列邮箱 —— 候选列、默认选中、显式指定、非法下标

# A–M 列（不含邮箱列），邮箱列都放在后面，便于控制列下标
BASE_13 = ["Student External Id", "Student Current Grade Level", "Student Official Class",
           "Advisor Last First", "School Short Code", "Section Course Name",
           "Section External Id", "Section Teacher Name", "Assessment Type Name",
           "Assessment Title", "Assessment Due Date", "Missing Work Code",
           "Missing Work Comment"]

STUDENTS = 6


def build_multi(headers, extras):
    """extras[i] 为第 i 名学生的附加列取值；每名学生一行。"""
    wb = Workbook(); ws = wb.active
    ws.append(BASE_13 + headers)
    for i in range(STUDENTS):
        ws.append([f"1000{i}", "08", "2031", None, "YK Pao", "8 MATH 数学", "8H", "Sue Li",
                   "Formative", "1.1.1 HW", 46273, "M", None] + extras[i])
    buf = BytesIO(); wb.save(buf)
    return buf.getvalue()


# 5a：两列都像邮箱（N = Advisor Email 只有 1 条，O = Parent Email 有 6 条）
two_mail_cols = build_multi(
    ["Advisor Email", "Parent Email"],
    [["advisor@example.com" if i == 0 else None, f"parent{i}@example.com"] for i in range(STUDENTS)],
)
r5a = parse_workbook(two_mail_cols)
assert [(c["index"], c["letter"], c["header"], c["email_count"]) for c in r5a["email_columns"]] == [
    (13, "N", "Advisor Email", 1),
    (14, "O", "Parent Email", 6),
], r5a["email_columns"]
# 默认沿用既有规则：第一个表头命中关键词的列（即第一个候选列）
assert r5a["email_column"] == 13, r5a["email_column"]
assert r5a["email_column_info"]["header"] == "Advisor Email"
assert [s["parent_email"] for s in r5a["students"]] == ["advisor@example.com"] + [""] * (STUDENTS - 1)
# 选错列（1 条 vs 6 条）必须给出提醒
assert any("请确认收件列" in w for w in r5a["warnings"]), r5a["warnings"]

# 5b：显式指定到 Parent Email 列 → 全部学生都有邮箱，且不再提示选错
r5b = parse_workbook(two_mail_cols, email_column=14)
assert r5b["email_column"] == 14
assert all(s["parent_email"] == f"parent{i}@example.com" for i, s in enumerate(r5b["students"]))
assert not any("请确认收件列" in w for w in r5b["warnings"]), r5b["warnings"]

# 5c：表头不规范（不含关键词），但数据里是邮箱 → 仍应成为候选列
no_keyword = build_multi(
    ["备注", "联系人1"],
    [[None, f"parent{i}@example.com"] for i in range(STUDENTS)],
)
r5c = parse_workbook(no_keyword)
assert [(c["index"], c["by_header"], c["email_count"]) for c in r5c["email_columns"]] == [(14, False, 6)], r5c["email_columns"]
# 没有任何关键词时仍回退第 14 列（N），此时它并不在候选里，界面需要照样能显示/切回
assert r5c["email_column"] == 13
assert r5c["email_column_info"]["letter"] == "N" and r5c["email_column_info"]["email_count"] == 0
assert all(s["parent_email"] == "" for s in r5c["students"])
assert any("缺少家长邮箱" in w for w in r5c["warnings"])
assert any("请确认收件列" in w for w in r5c["warnings"]), r5c["warnings"]
r5d = parse_workbook(no_keyword, email_column=14)
assert all(s["parent_email"] == f"parent{i}@example.com" for i, s in enumerate(r5d["students"]))

# 5e：非法下标 → ValueError
for bad in (-1, 99):
    try:
        parse_workbook(two_mail_cols, email_column=bad)
        assert False, f"列下标 {bad} 应当抛 ValueError"
    except ValueError as e:
        assert "收件邮箱列" in str(e), e

# 5f：提前返回的路径也要带齐列信息，否则 main.py 的 _store.update() 会残留上一次的列
KEYS = {"students", "warnings", "email_columns", "email_column", "email_column_info"}

empty_wb = Workbook(); buf = BytesIO(); empty_wb.save(buf)
r_empty = parse_workbook(buf.getvalue())
assert set(r_empty) == KEYS and r_empty["warnings"] == ["文件为空，无数据"], r_empty

bad_wb = Workbook(); ws = bad_wb.active
ws.append(["Student External Id", "Parent Email"])
ws.append(["24311", "parent@example.com"])
buf = BytesIO(); bad_wb.save(buf)
r_bad = parse_workbook(buf.getvalue())
assert set(r_bad) == KEYS and r_bad["email_column"] is None, r_bad
assert any("缺少必需列" in w for w in r_bad["warnings"]), r_bad["warnings"]

# 5g：单列文件的既有行为不变，只是多出一份可展示的列信息
assert [(c["index"], c["header"]) for c in r1["email_columns"]] == [(13, "家长邮箱")], r1["email_columns"]
assert r1["email_column"] == 13 and r1["email_column_info"]["email_count"] == 2

# 5h：列数不足 14 且表头无关键词 —— 老规则会得出「没有邮箱列」，此时退到数据里真有邮箱的候选
short_wb = Workbook(); ws = short_wb.active
ws.append(["Student External Id", "Section Course Name", "Section Teacher Name",
           "Assessment Title", "Assessment Due Date", "Missing Work Code", "联系人"])
for i in range(3):
    ws.append([f"2000{i}", "8 MATH 数学", "Sue Li", "1.1.1 HW", 46273, "M", "parent@example.com"])
buf = BytesIO(); short_wb.save(buf)
r5h = parse_workbook(buf.getvalue())
assert [(c["index"], c["by_header"]) for c in r5h["email_columns"]] == [(6, False)], r5h["email_columns"]
assert r5h["email_column"] == 6 and r5h["email_column_info"]["letter"] == "G", r5h
assert all(s["parent_email"] == "parent@example.com" for s in r5h["students"])
assert not any("缺少家长邮箱" in w for w in r5h["warnings"]), r5h["warnings"]

print("OK: multiple email columns (candidates / default / override / invalid) all pass")


# 场景 6：一格多个邮箱 —— 逗号/分号、跨行并集、非法片段

# 6a：逗号与分号都要认；email_count 数行、address_count 数地址
multi_sep = build_multi(
    ["Parent Email"],
    [
        [f"father{i}@example.com; mother{i}@example.com" if i % 2 == 0
         else f"father{i}@example.com, mother{i}@example.com"]
        for i in range(STUDENTS)
    ],
)
r6a = parse_workbook(multi_sep)
assert r6a["students"][0]["parent_email"] == "father0@example.com, mother0@example.com", r6a["students"][0]
assert r6a["students"][1]["parent_email"] == "father1@example.com, mother1@example.com", r6a["students"][1]
assert all(s["invalid_addresses"] == [] for s in r6a["students"]), r6a["students"]
assert r6a["email_column_info"]["email_count"] == STUDENTS, r6a["email_column_info"]
assert r6a["email_column_info"]["address_count"] == STUDENTS * 2, r6a["email_column_info"]
assert r6a["email_column_info"]["sample"] == "father0@example.com", r6a["email_column_info"]
assert not any("发送会被暂停" in w for w in r6a["warnings"]), r6a["warnings"]

# 6b：一格多个地址的列，表头没有关键词也要成为候选列（整格匹配会漏掉这种列）
multi_no_kw = build_multi(
    ["联系人"], [[f"a{i}@example.com; b{i}@example.com"] for i in range(STUDENTS)]
)
r6b = parse_workbook(multi_no_kw)
assert [
    (c["index"], c["by_header"], c["email_count"], c["address_count"]) for c in r6b["email_columns"]
] == [(13, False, STUDENTS, STUDENTS * 2)], r6b["email_columns"]
assert r6b["email_column"] == 13  # 列数 14、表头无关键词 → 仍回退第 14 列，正好是这一列
assert r6b["students"][0]["parent_email"] == "a0@example.com, b0@example.com", r6b["students"][0]


def build_rows(email_rows):
    """同一个学生的多行（每行一条缺交记录），邮箱列的取值由调用方给。"""
    wb = Workbook(); ws = wb.active
    ws.append(BASE_13 + ["Parent Email"])
    for i, value in enumerate(email_rows):
        ws.append(["9001", "08", "2031", None, "YK Pao", "8 MATH 数学", "8H", "Sue Li",
                   "Formative", f"作业 {i}", 46273, "M", None, value])
    buf = BytesIO(); wb.save(buf)
    return buf.getvalue()


# 6c：同一学生的多行填了不同地址 → 合并发送（并说明数据本身有出入）
r6c = parse_workbook(build_rows(["father@example.com", "mother@example.com; father@example.com"]))
assert len(r6c["students"]) == 1 and len(r6c["students"][0]["items"]) == 2, r6c["students"]
assert r6c["students"][0]["parent_email"] == "father@example.com, mother@example.com", r6c["students"][0]
assert any("多行家长邮箱不一致" in w for w in r6c["warnings"]), r6c["warnings"]

# 6d：多行填的是同一组地址（只是顺序不同）→ 合并后只发一遍，也不该报「不一致」
r6d = parse_workbook(build_rows(["a@example.com; b@example.com", "B@example.com, a@example.com"]))
assert r6d["students"][0]["parent_email"] == "a@example.com, b@example.com", r6d["students"][0]
assert not any("不一致" in w for w in r6d["warnings"]), r6d["warnings"]

# 6e：含无法识别的片段 → 逐学生记下来 + 给一条「发送会被暂停」的提示（拦截在 main.send）
r6e = parse_workbook(
    build_multi(
        ["Parent Email"],
        [["father@example.com; 张先生"] if i == 0 else
         (["13800000000"] if i == 1 else [f"parent{i}@example.com"])
         for i in range(STUDENTS)],
    )
)
assert r6e["students"][0]["parent_email"] == "father@example.com, 张先生", r6e["students"][0]
assert r6e["students"][0]["invalid_addresses"] == ["张先生"], r6e["students"][0]
assert r6e["students"][1]["invalid_addresses"] == ["13800000000"], r6e["students"][1]
assert all(s["invalid_addresses"] == [] for s in r6e["students"][2:]), r6e["students"]
# 非法片段照样算「有邮箱」：它会被拦下，而不是被当成缺邮箱的学生悄悄跳过
assert not any("缺少家长邮箱" in w for w in r6e["warnings"]), r6e["warnings"]
assert any("发送会被暂停" in w and "10000（张先生）" in w for w in r6e["warnings"]), r6e["warnings"]

# 6f：邮箱列里放的是数字（openpyxl 读成 int）→ 当作非法片段，且解析不能炸
numeric = build_multi(
    ["Parent Email"],
    [[13800000000] if i == 0 else [f"parent{i}@example.com"] for i in range(STUDENTS)],
)
r6f = parse_workbook(numeric)
assert r6f["students"][0]["parent_email"] == "13800000000", r6f["students"][0]
assert r6f["students"][0]["invalid_addresses"] == ["13800000000"], r6f["students"][0]
assert not any("缺少家长邮箱" in w for w in r6f["warnings"]), r6f["warnings"]

print("OK: 一格多个邮箱（逗号/分号/跨行并集/非法片段）all pass")

