"""发送日志：往 SQLite 记「什么时候、给谁、成功还是失败」。

三类事件写同一张宽表（见 db._SCHEMA_V1）：
- `job_start` / `job_end`：一批的开始与结束。必须有——连接阶段就失败时一封都没发，
  只记 `send` 行的话日志里一片空白，看着像「什么都没发生」。
- `send`：每次实际投递一行（成功、失败各一行）。

**不存邮件正文**：正文长且高度重复。因此将来重试不能只靠日志重发，得重新上传同一份
Excel，用日志里的 `student_id` + `recipient` 把两者对上、筛出「上次失败的这些人」。

**写日志失败绝不能让发信失败**：record() 吞掉所有异常，只写 stderr 并记进 db 状态；
但也不静默——status() 会把错误交给页面显示。
"""

from __future__ import annotations

import sys
from contextlib import closing
from datetime import datetime

from . import db

# 表列固定顺序，写入时按它取值：缺的字段留 NULL，多给的不认。
_COLUMNS = (
    "ts",
    "day",
    "event",
    "job_id",
    "mode",
    "channel",
    "attempt",
    "retry_of",
    "student_id",
    "student_name",
    "grade",
    "class_name",
    "item_count",
    "recipient",
    "subject",
    "ok",
    "error",
    "duration_ms",
    "status",
    "total",
    "sent",
    "failed",
    "filename",
    "email_column",
    "email_column_header",
)


def _day_options(conn) -> list[str]:
    """供前端日期下拉：最近 90 天里有记录的日期。"""
    rows = conn.execute("SELECT DISTINCT day FROM send_log ORDER BY day DESC LIMIT 90")
    return [r[0] for r in rows if r[0]]


def _counts(conn, day: str) -> dict:
    """当日统计。只看当天、不受下方结果筛选影响，避免翻看筛选时数字跟着跳。

    `failed` 与筛选里的「仅失败」同一口径：投递失败的封数 + 整批没发出去的批次数。
    """
    row = conn.execute(
        "SELECT"
        " COALESCE(SUM(event='send'), 0) AS send,"
        " COALESCE(SUM(event='send' AND ok=1), 0) AS ok,"
        " COALESCE(SUM((event='send' AND ok=0) OR (event='job_end' AND status='failed')), 0) AS failed,"
        " COALESCE(SUM(event='job_end'), 0) AS jobs"
        " FROM send_log WHERE day = ?",
        (day,),
    ).fetchone()
    return {k: int(row[k] or 0) for k in ("send", "ok", "failed", "jobs")}


def _filter_clause(ok: str) -> str:
    """结果筛选：all / ok / fail。整批没发出去（job_end failed）也算失败。"""
    if ok == "ok":
        return " AND event='send' AND ok=1"
    if ok == "fail":
        return " AND ((event='send' AND ok=0) OR (event='job_end' AND status='failed'))"
    return ""


def record(entry: dict) -> None:
    """写一行日志。补全 ts/day/attempt/retry_of，异常降级为 stderr + db 状态，不抛。"""
    row = dict(entry)
    now = datetime.now()
    row.setdefault("ts", now.strftime("%Y-%m-%d %H:%M:%S"))
    row.setdefault("day", now.strftime("%Y-%m-%d"))
    row.setdefault("attempt", 1)
    row.setdefault("retry_of", None)
    try:
        # status() 内含 init()：一次调用就拿到「是否可用 + 失败原因」，
        # 不要在失败后再去问一次——那次重试可能成功，报出来的原因就成了空话
        info = db.status()
        if not info["ready"]:
            raise RuntimeError(info["error"] or "数据库不可用")
        with closing(db.connect()) as conn:
            conn.execute(
                f"INSERT INTO send_log ({', '.join(_COLUMNS)})"
                f" VALUES ({', '.join('?' * len(_COLUMNS))})",
                [row.get(c) for c in _COLUMNS],
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        db.mark_error(msg)
        # 不抛：日志写不进去不是发信失败的理由，但也不能悄悄吞掉
        print(f"[发送日志] 写入失败：{msg}", file=sys.stderr)


def status() -> dict:
    """{"path", "ready", "error"}：库不可用时页面挂红色横幅并给出真实路径。"""
    return db.status()


def read(day: str | None = None, ok: str = "all", limit: int = 200) -> dict:
    """读某一天的日志。

    day 为空时取最近有记录的一天（库里全是空的时候退化为今天），这样「上次发送在昨天」
    不会被默认成空列表。日期不存在不是错误，返回空列表即可。
    limit 只截断 entries，counts 仍是整天的数字。
    """
    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit = 200

    info = db.status()
    result = {
        "date": day or datetime.now().strftime("%Y-%m-%d"),
        "entries": [],
        "counts": {"send": 0, "ok": 0, "failed": 0, "jobs": 0},
        "truncated": False,
        "dates": [],
        "db": info,
    }
    if not info["ready"]:
        return result

    try:
        with closing(db.connect()) as conn:
            dates = _day_options(conn)
            target = day or (dates[0] if dates else datetime.now().strftime("%Y-%m-%d"))
            result["dates"] = dates
            result["date"] = target
            result["counts"] = _counts(conn, target)
            where = _filter_clause(ok)
            total = conn.execute(
                f"SELECT COUNT(*) FROM send_log WHERE day = ?{where}", (target,)
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM send_log WHERE day = ?{where} ORDER BY id DESC LIMIT ?",
                (target, limit),
            ).fetchall()
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        db.mark_error(msg)
        print(f"[发送日志] 读取失败：{msg}", file=sys.stderr)
        result["db"] = db.status()
        return result

    result["entries"] = [dict(r) for r in rows]
    result["truncated"] = total > len(rows)
    return result
