"""验证管理员脚本 scripts/clear_send_log.py：三种删除范围、确认与 dry-run、路径守卫。

库文件一律指向临时目录——绝不能碰 data/mailer.db（那是真实运行数据）。
沿用仓库既有风格：纯脚本 + assert，跑通打印 OK。
"""

import builtins
import contextlib
import io
import os
import sqlite3
import tempfile

from app import config, db, send_log
from scripts import clear_send_log

TMP = tempfile.mkdtemp(prefix="clear-log-test-")


def use_db(name: str) -> str:
    """换一个干净的库文件：db 模块按路径重新初始化（不缓存路径）。"""
    config.DB_PATH = os.path.join(TMP, name)
    return config.DB_PATH


def seed(day: str, count: int, event: str = "send") -> None:
    for i in range(count):
        send_log.record(
            {
                "event": event,
                "day": day,
                "job_id": "job-x",
                "student_id": f"{day}-{i}",
                "class_name": "2031",
                "recipient": f"{day}-{i}@example.com",
                "ok": 1,
            }
        )


def count(path: str | None = None, day: str | None = None) -> int:
    with sqlite3.connect(path or config.DB_PATH) as conn:
        if day is None:
            return conn.execute("SELECT COUNT(*) FROM send_log").fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM send_log WHERE day = ?", (day,)).fetchone()[0]


def run(*argv: str) -> tuple[int, str]:
    """跑一次 CLI，连带把输出（含 argparse 的用法/报错）收走，测试输出只留 OK 行。"""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = clear_send_log.main(list(argv))
    except SystemExit as e:  # argparse 的参数错误走 SystemExit(2)
        code = e.code
    return code, buf.getvalue()


# ---- 1. --day 只删指定的一天，其余日期原样保留 ----
use_db("scope.db")
seed("2026-01-01", 3)
seed("2026-01-02", 2, event="job_end")
seed("2026-01-03", 4)
assert count() == 9, count()

code, out = run("--day", "2026-01-02", "--yes")
assert code == 0, out
assert count(day="2026-01-02") == 0 and count() == 7, "只该删掉 2026-01-02 那 2 条"
assert count(day="2026-01-01") == 3 and count(day="2026-01-03") == 4, "别的日期不能受影响"
assert "将删除 2 条记录（2026-01-02 ~ 2026-01-02）：job_end 2" in out, out
assert "已删除 2 条记录" in out, out

# ---- 2. --before 是「不含当天」，边界那天必须留着 ----
code, out = run("--before", "2026-01-03", "--yes")
assert code == 0, out
assert count() == 4 and count(day="2026-01-03") == 4, "2026-01-03 当天不能被删掉"

# ---- 3. --dry-run 只看不删；--all 清空 ----
code, out = run("--all", "--dry-run")
assert code == 0 and count() == 4, "dry-run 不能动数据"
assert "--dry-run：未做任何改动" in out and "将删除 4 条" in out, out

code, out = run("--all", "--yes")
assert code == 0 and count() == 0, out
assert "已删除 4 条记录" in out, out

code, out = run("--all", "--yes")
assert code == 0 and "没有命中任何记录" in out, out

# ---- 4. 确认：必须逐字 yes，非交互环境当取消而不是卡住 ----
original_input = builtins.input
builtins.input = lambda _prompt="": "YES"
assert clear_send_log._confirm("?") is True, "大小写与首尾空格应被容忍"
builtins.input = lambda _prompt="": "y"


def _eof(_prompt=""):
    raise EOFError


assert clear_send_log._confirm("?") is False, "y 不算确认，删的是审计记录，要求逐字 yes"
builtins.input = _eof
assert clear_send_log._confirm("?") is False, "管道/CI 里拿不到输入，按取消处理"
builtins.input = original_input

use_db("confirm.db")
seed("2026-01-04", 3)
original_confirm = clear_send_log._confirm
clear_send_log._confirm = lambda _prompt: False
code, out = run("--all")
clear_send_log._confirm = original_confirm
assert code == 0 and count() == 3, "拒绝确认后一条都不能删"
assert "已取消" in out, out

# ---- 5. 不带范围：只打印现状，一条都不删 ----
code, out = run()
assert code == 1 and count() == 3, "不给范围就什么都不删"
assert "未指定删除范围" in out and "现有 3 条记录" in out, out

# ---- 6. 参数校验 ----
code, out = run("--day", "2026/01/04", "--yes")
assert code == 1 and "日期格式不对" in out, out

code, out = run("--all", "--day", "2026-01-04")
assert code == 2 and count() == 3, "--all 与 --day 互斥，不能猜用户想删哪个"

missing = os.path.join(TMP, "no-such-dir", "mailer.db")
code, out = run("--all", "--yes", "--db", missing)
assert code == 1 and "库文件不存在" in out, out
assert not os.path.exists(missing), "路径写错时不能凭空建库，那会让人以为日志本来就是空的"

# ---- 7. --db 指向别的库：删的是它，不是 config.DB_PATH 那个 ----
main_db = use_db("main.db")
seed("2026-01-05", 2)
other_db = use_db("other.db")
seed("2026-01-06", 3)
code, out = run("--all", "--yes", "--db", other_db)
assert code == 0, out
assert count(path=other_db) == 0 and count(path=main_db) == 2, "--db 只影响指定的库文件"

# ---- 8. 删除后回收空间：DELETE 不还空间，VACUUM 才把库文件缩回去 ----
config.DB_PATH = main_db
db.init()
with sqlite3.connect(main_db) as conn:  # 批量插入，避免逐条 record() 的开销
    conn.executemany(
        "INSERT INTO send_log (ts, day, event, ok) VALUES (?, ?, 'send', 1)",
        [("2026-01-07 09:00:00", "2026-01-07")] * 500,
    )
before = os.path.getsize(main_db)

code, out = run("--all", "--yes", "--no-vacuum")
assert code == 0 and count(path=main_db) == 0, out
assert os.path.getsize(main_db) >= before, "--no-vacuum 不该动库文件"

with sqlite3.connect(main_db) as conn:
    conn.executemany(
        "INSERT INTO send_log (ts, day, event, ok) VALUES (?, ?, 'send', 1)",
        [("2026-01-07 09:00:00", "2026-01-07")] * 500,
    )
assert os.path.getsize(main_db) > 8192, "先确认这个库不止一页，否则「变小」没有意义"
before = os.path.getsize(main_db)

code, out = run("--all", "--yes")
assert code == 0 and count(path=main_db) == 0, out
assert os.path.getsize(main_db) < before, f"VACUUM 应回收空间：{before} → {os.path.getsize(main_db)}"
assert "已回收空间" in out, out

print("OK: --day / --before（不含当天）/ --all 三种范围各自只删该删的")
print("OK: dry-run 与拒绝确认都不动数据；必须逐字 yes，非交互环境按取消处理")
print("OK: 无范围 / 非法日期 / 互斥参数 / 库文件不存在 各自报错且不改数据")
print("OK: --db 只作用于指定库文件；VACUUM 回收空间，--no-vacuum 可关")
