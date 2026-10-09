"""解析 JumpRope 导出的 Excel，按学生分组。"""

from __future__ import annotations

import datetime
import re
from io import BytesIO

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel

# 表头名 -> 内部字段名
COL_HEADERS = {
    "student_id": "Student External Id",
    "grade": "Student Current Grade Level",
    "class": "Student Official Class",
    "school": "School Short Code",
    "course": "Section Course Name",
    "teacher": "Section Teacher Name",
    "title": "Assessment Title",
    "due_date": "Assessment Due Date",
    "code": "Missing Work Code",
}

# 用于定位家长邮箱列的表头关键词
EMAIL_KEYWORDS = ("email", "mail", "邮箱", "家长")

# 判定单元格「像邮箱」的正则：仅用于探测候选列与提示选错列，不参与发送时的取值
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# 学生姓名列的表头候选（按优先级）；整名列缺失时回退到 First + Last 拼接
NAME_HEADERS = ("Student Name", "Student Full Name", "Student Last First", "Student Last Name First")
FIRST_NAME_HEADERS = ("Student First Name", "Student Firstname", "Student Preferred First Name")
LAST_NAME_HEADERS = ("Student Last Name", "Student Lastname", "Student Preferred Last Name")

# 必需列缺失时视为无法解析
REQUIRED_HEADERS = ("student_id", "course", "teacher", "title", "due_date", "code")


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_date_str(value) -> str:
    """把截止日期统一为 'YYYY-MM-DD' 字符串。"""
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        # Excel 日期序列号（如 46273 -> 2026-09-08）
        try:
            return from_excel(value).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return _clean(value)
    s = _clean(value)
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%Y.%m.%d"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def _looks_like_email(value) -> bool:
    return bool(EMAIL_RE.match(_clean(value)))


def _column_meta(index: int, header: list[str], data_rows: list) -> dict:
    """统计某一列的邮箱情况，供界面展示（列字母 / 表头 / 有效邮箱条数 / 样例）。"""
    count = 0
    sample = ""
    for row in data_rows:
        if index >= len(row):
            continue
        value = _clean(row[index])
        if _looks_like_email(value):
            count += 1
            if not sample:
                sample = value
    return {
        "index": index,
        "letter": get_column_letter(index + 1),
        "header": header[index],
        "email_count": count,
        "sample": sample,
    }


def _find_email_columns(header: list[str], data_rows: list) -> list[dict]:
    """候选收件列 = 表头含邮箱关键词的列 ∪ 数据里真的出现过邮箱的列。

    只看表头会漏掉表头不规范的文件（如列名就叫「N」），只看数据会把与发信无关的
    邮箱列（如 Advisor Email）也漏掉，所以取并集，由用户在界面上最终决定。
    """
    columns = []
    for i, name in enumerate(header):
        meta = _column_meta(i, header, data_rows)
        meta["by_header"] = any(k in name.lower() for k in EMAIL_KEYWORDS)
        if meta["by_header"] or meta["email_count"]:
            columns.append(meta)
    return columns


def _default_email_column(header: list[str], columns: list[dict]) -> int | None:
    """沿用既有规则：第一个表头命中关键词的列，否则回退到第 14 列（N）。

    再兜一层「数据里真的有邮箱」的候选列：列数不足 14 且表头没有关键词时，老规则会得出
    "没有邮箱列"，邮件一封也发不出去——这种文件正是本功能要救的，此时选中第一个候选列，
    总比什么都不选强。
    """
    for c in columns:
        if c["by_header"]:
            return c["index"]
    if len(header) >= 14:
        return 13
    return columns[0]["index"] if columns else None


def _empty(warning: str) -> dict:
    """任何提前返回都要带上完整字段，否则 main._store.update() 会留下上一次的列信息。"""
    return {
        "students": [],
        "warnings": [warning],
        "email_columns": [],
        "email_column": None,
        "email_column_info": None,
    }


def parse_workbook(data: bytes, filename: str = "", email_column: int | None = None) -> dict:
    """解析 Excel 字节，返回 {'students', 'warnings', 'email_columns', 'email_column', 'email_column_info'}。

    email_column 为显式指定的收件列下标（0 基），None 表示按默认规则自动选择。
    下标非法时抛 ValueError。
    """
    wb = load_workbook(BytesIO(data), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return _empty("文件为空，无数据")

    header = [_clean(h) for h in rows[0]]
    data_rows = rows[1:]

    idx: dict[str, int | None] = {}
    for key, name in COL_HEADERS.items():
        idx[key] = header.index(name) if name in header else None

    email_columns = _find_email_columns(header, data_rows)
    if email_column is None:
        email_column = _default_email_column(header, email_columns)
    elif not 0 <= email_column < len(header):
        raise ValueError(f"收件邮箱列无效：第 {email_column + 1} 列不存在（本表共 {len(header)} 列）")

    email_column_info = _column_meta(email_column, header, data_rows) if email_column is not None else None

    def find_col(candidates: tuple[str, ...]) -> int | None:
        for name in candidates:
            if name in header:
                return header.index(name)
        return None

    name_col = find_col(NAME_HEADERS)
    first_col = find_col(FIRST_NAME_HEADERS)
    last_col = find_col(LAST_NAME_HEADERS)

    def row_name(row) -> str:
        if name_col is not None:
            return _clean(row[name_col]) if name_col < len(row) else ""
        parts = [
            _clean(row[i]) if i < len(row) else ""
            for i in (first_col, last_col)
            if i is not None
        ]
        return " ".join(p for p in parts if p)

    missing = [name for key, name in COL_HEADERS.items() if idx[key] is None and key in REQUIRED_HEADERS]
    if missing:
        return _empty(f"缺少必需列：{'、'.join(missing)}")

    def get(row, key):
        i = idx.get(key)
        return row[i] if i is not None and i < len(row) else None

    grouped: dict[str, dict] = {}
    order: list[str] = []
    warnings: list[str] = []

    for row in data_rows:
        if row is None or all(v is None or _clean(v) == "" for v in row):
            continue
        sid = _clean(get(row, "student_id"))
        if not sid:
            continue
        email = _clean(row[email_column]) if email_column is not None and email_column < len(row) else ""

        if sid not in grouped:
            grouped[sid] = {
                "student_id": sid,
                "student_name": row_name(row),
                "grade": _clean(get(row, "grade")),
                "class": _clean(get(row, "class")),
                "school": _clean(get(row, "school")),
                "parent_email": email,
                "items": [],
            }
            order.append(sid)
        else:
            stu = grouped[sid]
            if email and stu["parent_email"] and email.lower() != stu["parent_email"].lower():
                warnings.append(f"学生 {sid} 出现多个不同家长邮箱：{stu['parent_email']} / {email}")
            if email and not stu["parent_email"]:
                stu["parent_email"] = email

        grouped[sid]["items"].append(
            {
                "course": _clean(get(row, "course")),
                "teacher": _clean(get(row, "teacher")),
                "title": _clean(get(row, "title")),
                "due_date": _to_date_str(get(row, "due_date")),
                "code": _clean(get(row, "code")),
            }
        )

    students = [grouped[sid] for sid in order]
    if students and name_col is None and first_col is None and last_col is None:
        warnings.append("未找到学生姓名列（Student Name 或 Student First/Last Name），邮件中不显示学生姓名")
    if email_column_info is not None:
        # 选错列最典型的后果是「整批只发出去几封」，这里给个不拦截的提醒
        better = max(
            (c for c in email_columns if c["index"] != email_column),
            key=lambda c: c["email_count"],
            default=None,
        )
        if better and better["email_count"] >= 5 and better["email_count"] > email_column_info["email_count"] * 2:
            warnings.append(
                f"当前收件列 {email_column_info['letter']} 列只有 {email_column_info['email_count']} 条邮箱，"
                f"而 {better['letter']} 列有 {better['email_count']} 条，请确认收件列是否选对"
            )
    no_email = [s["student_id"] for s in students if not s["parent_email"]]
    if no_email:
        warnings.append(f"以下 {len(no_email)} 名学生缺少家长邮箱，将不会被发送：{', '.join(no_email)}")

    return {
        "students": students,
        "warnings": warnings,
        "email_columns": email_columns,
        "email_column": email_column,
        "email_column_info": email_column_info,
    }
