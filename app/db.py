"""SQLite 连接与表结构的唯一出处（将来的发送分析表也放这里）。

DB_PATH **惰性读取**（不缓存路径），测试改 config 常量即可生效，沿用 test_smtp.py /
test_send_job.py 直接改 config 常量的既有约定。

连接**不跨线程共用**：发信在后台线程、页面查询在 FastAPI 的线程池里，所以每次操作
现开现关（`with closing(db.connect())`）。写入量级是每秒一两行，这点开销可以忽略。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from . import config

# 表结构版本，写在 PRAGMA user_version 里
SCHEMA_VERSION = 1

# 模块级状态：路径 / 是否可用 / 最近的错误。页面靠它把「日志写不进去」报出来。
_state: dict = {"path": "", "ready": False, "error": None}

# 已完成初始化的路径。路径变了（测试改 config.DB_PATH）必须重新初始化。
_initialized_for: str | None = None

# init() 会被发信线程与请求线程同时调用，必须单飞：否则并发跑迁移/写入探测会互相踩
# （一个线程 DROP 掉另一个刚建的探测表），并且会把「已就绪」的状态改回不可用。
_init_lock = threading.Lock()


# 宽表：用 event 区分 job_start / send / job_end 三类行，dashboard 一条 SQL 就能聚合，
# 不用 join 两张表。分析维度（学生/年级/班级/缺交条数）必须在发送那一刻快照——
# Excel 发完就丢了，事后补不回来。
_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS send_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT NOT NULL,      -- 本地时间 YYYY-MM-DD HH:MM:SS
    day                 TEXT NOT NULL,      -- YYYY-MM-DD，按天查询/清理用
    event               TEXT NOT NULL,      -- job_start | send | job_end
    job_id              TEXT,
    mode                TEXT,               -- test | live
    channel             TEXT,               -- graph | smtp
    attempt             INTEGER NOT NULL DEFAULT 1,
    retry_of            TEXT,               -- 预留：重试时指向原 job_id
    student_id          TEXT,
    student_name        TEXT,
    grade               TEXT,
    class_name          TEXT,
    item_count          INTEGER,
    recipient           TEXT,
    subject             TEXT,
    ok                  INTEGER,            -- send 行：1 成功 / 0 失败
    error               TEXT,
    duration_ms         INTEGER,
    status              TEXT,               -- job_end 行：done | failed
    total               INTEGER,            -- job_start 行：本批封数
    sent                INTEGER,            -- job_end 行
    failed              INTEGER,            -- job_end 行
    filename            TEXT,               -- job_start 行：上传的文件名
    email_column        INTEGER,            -- job_start 行：收件列下标（0 基）
    email_column_header TEXT                -- job_start 行：收件列表头
);
CREATE INDEX IF NOT EXISTS idx_send_log_day_id ON send_log(day, id);
CREATE INDEX IF NOT EXISTS idx_send_log_job ON send_log(job_id);
"""


def path() -> str:
    """当前库文件路径（每次现读 config，不缓存）。"""
    return config.DB_PATH


def connect() -> sqlite3.Connection:
    """新建一个连接。调用方负责关闭——连接不可跨线程共用，不要缓存。"""
    conn = sqlite3.connect(path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """按 PRAGMA user_version 逐版本升级。

    加字段请**新增**一条 `if version < N` 分支，不要改旧分支：旧分支对已经升过级的库
    不会再执行，改了等于没改，老库会一直缺列。
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        conn.executescript(_SCHEMA_V1)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def init() -> bool:
    """幂等地建库/建表/迁移，返回当前是否可用。失败不抛异常，错误存进模块状态。

    record() / read() / status() 都会先调它，所以模块是自初始化的，不需要
    FastAPI 启动钩子（启动钩子在测试里也不会执行）。整体加锁：多线程同时首次调用时
    只有一个线程真正执行，其余线程等它做完后走上面的快路径。
    """
    global _initialized_for
    current = path()
    with _init_lock:
        if _initialized_for == current and _state["ready"]:
            return True
        _state.update(path=current, ready=False, error=None)
        try:
            Path(current).parent.mkdir(parents=True, exist_ok=True)
            with closing(connect()) as conn:
                # WAL：读查询与写入互不阻塞，避免「database is locked」
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                _migrate(conn)
                # 真实写入探测：库已存在且版本已是最新时，上面的建表语句什么也不会写，
                # 只有真写一次才能发现「目录/文件不可写」。
                conn.execute("CREATE TABLE IF NOT EXISTS _write_probe (x INTEGER)")
                conn.execute("DROP TABLE IF EXISTS _write_probe")
                conn.commit()
        except Exception as e:  # noqa: BLE001
            _state.update(ready=False, error=f"{type(e).__name__}: {e}")
            return False
        _initialized_for = current
        _state.update(ready=True, error=None)
        return True


def mark_error(error: str) -> None:
    """记下一次失败（如写入失败）：状态转为不可用，页面会显示出来。

    调用方自己吞掉异常，这里只负责让 status() 说得出发生了什么。
    """
    _state.update(ready=False, error=error)


def status() -> dict:
    """{"path", "ready", "error"}，供页面判断日志是否可用。"""
    init()
    return {
        "path": _state["path"] or path(),
        "ready": bool(_state["ready"]),
        "error": _state["error"],
    }
