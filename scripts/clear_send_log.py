"""清空 / 裁剪发送日志（SQLite）。

服务器上（容器内执行，脚本随镜像发布）：

    docker compose exec mailer python3 scripts/clear_send_log.py --all --dry-run
    docker compose exec mailer python3 scripts/clear_send_log.py --all
    docker compose exec mailer python3 scripts/clear_send_log.py --before 2026-01-01
    docker compose exec mailer python3 scripts/clear_send_log.py --day 2026-10-01 --yes

本地开发（仓库根目录）：把 `docker compose exec mailer` 去掉即可。

**删除范围必须显式给出**（--all / --day / --before），不带范围时只打印现状与用法，一条都不删。
删掉的是「哪天给哪些家长发过信」的凭据，邮件正文本来就不存（见 app/send_log.py），
所以误删是真补不回来的，值得多敲一个参数。

库文件路径与表结构一律走 app.db / app.config（库文件位置的唯一出处），这里只负责「删」；
app 侧没有任何删除入口，因此这段 SQL 不会与别处重复。日志的**自动**清理与保留策略是
明确不做的功能（见 CLAUDE.md 的架构决策），要清就手动跑这个脚本。

发信进行中不要清理：正在写的那一批已经落库的行会被删掉（已发出去的邮件不受影响），
记录会缺一段；请在两次发送之间执行。
"""

from __future__ import annotations

import argparse
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

# 直接 `python3 scripts/clear_send_log.py` 运行时，sys.path[0] 是 scripts/，
# 仓库根目录不在其中，`import app` 会失败——补上，让直接执行与 `-m` 两种方式都能用
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402 —— 必须在上面那行之后才能 import

# 打印时的固定顺序，免得每次运行的事件排列都在变
_EVENTS = ("job_start", "send", "job_end")


def _resolve(args: argparse.Namespace) -> tuple[str, tuple, str]:
    """把范围参数翻成 (WHERE 片段, 参数, 给人看的描述)。

    三者从同一处出：打印出来的范围必须与实际删的范围是同一句话，否则这个提示本身就是隐患。
    `day` 是零填充的定长 YYYY-MM-DD，字典序即时间序，所以 `--before` 直接拿 `<` 比字符串，
    不用套 SQLite 的日期函数。
    """
    if args.all:
        return "", (), "全部"
    if args.day:
        return " WHERE day = ?", (args.day,), f"仅 {args.day} 当天"
    return " WHERE day < ?", (args.before,), f"{args.before} 之前（不含当天）"


def summarize(where: str, params: tuple) -> dict:
    """先看清楚要删什么：条数、日期跨度、各 event 的条数。"""
    with closing(db.connect()) as conn:
        total, first_day, last_day = conn.execute(
            f"SELECT COUNT(*), MIN(day), MAX(day) FROM send_log{where}", params
        ).fetchone()
        events = {
            row[0]: row[1]
            for row in conn.execute(
                f"SELECT event, COUNT(*) FROM send_log{where} GROUP BY event", params
            )
        }
    return {"total": total, "first_day": first_day, "last_day": last_day, "events": events}


def purge(where: str, params: tuple) -> int:
    """删除命中行并返回条数。

    单条 DELETE 本身就是原子的，不需要额外包一层事务；rowcount 即删除条数。
    """
    with closing(db.connect()) as conn:
        cur = conn.execute(f"DELETE FROM send_log{where}", params)
        conn.commit()
        return cur.rowcount


def reclaim_space() -> tuple[int, int]:
    """回收文件空间，返回 (前, 后) 字节数。

    DELETE 只是把页标成空闲，库文件不会自己变小；服务一直在跑，库只增不减也没人管。
    VACUUM 之后 checkpoint 一次，把 WAL 里的内容并回主文件、顺带截断 -wal。
    """
    path = db.path()
    before = Path(path).stat().st_size
    with closing(db.connect()) as conn:
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return before, Path(path).stat().st_size


def _size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _confirm(prompt: str) -> bool:
    """要求逐字输入 yes；y、回车都算取消——删的是审计记录，多敲三个字母不冤。

    非交互环境（管道、CI）里 input() 会抛 EOFError，一律当取消，此时该加 --yes。
    """
    try:
        return input(prompt).strip().lower() == "yes"
    except EOFError:
        return False


def _breakdown(events: dict) -> str:
    """`job_start 6 / send 116 / job_end 6`，末尾附上不认识的 event（表是别人也能写的宽表）。"""
    ordered = [e for e in _EVENTS if e in events]
    ordered += sorted(e for e in events if e not in _EVENTS)
    return " / ".join(f"{e} {events[e]}" for e in ordered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clear_send_log.py",
        description="清空 / 裁剪发送日志（SQLite）。删除范围必须显式指定。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例：\n"
            "  --all --dry-run              看看清空会删掉多少，不动数据\n"
            "  --before 2026-01-01          只删 2026-01-01 之前的\n"
            "  --day 2026-10-01 --yes       删某一天，跳过确认（脚本里用）\n"
            "\n"
            "发信进行中不要执行：这一批的记录会被删掉（邮件本身不受影响）。"
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="删除全部日志")
    group.add_argument("--day", metavar="YYYY-MM-DD", help="只删除这一天的日志")
    group.add_argument("--before", metavar="YYYY-MM-DD", help="删除这一天之前（不含当天）的日志")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过交互确认")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    parser.add_argument("--no-vacuum", action="store_true", help="删完不回收文件空间")
    parser.add_argument("--db", metavar="PATH", help="指定库文件（默认取 config.DB_PATH）")
    args = parser.parse_args(argv)

    if args.db:
        config.DB_PATH = args.db

    path = db.path()
    # 不自动建库：路径写错时凭空建出一个空库，会让人以为「日志本来就是空的」，
    # 而真正的日志其实在另一个文件里
    if not Path(path).exists():
        print(f"库文件不存在：{path}", file=sys.stderr)
        return 1

    info = db.status()
    if not info["ready"]:
        print(f"库不可用：{info['path']}\n{info['error']}", file=sys.stderr)
        return 1

    for value in (args.day, args.before):
        if value is None:
            continue
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            print(f"日期格式不对：{value}（应为 YYYY-MM-DD）", file=sys.stderr)
            return 1

    if not (args.all or args.day or args.before):
        total = summarize("", ())["total"]
        parser.print_help()
        print(f"\n库文件 {path} 现有 {total} 条记录。未指定删除范围，未做任何改动。")
        return 1

    where, params, described = _resolve(args)

    print(f"库文件：{path}")
    print(f"范围：{described}")
    stat = summarize(where, params)
    if stat["total"] == 0:
        print("没有命中任何记录，无需清理。")
        return 0
    print(f"将删除 {stat['total']} 条记录（{stat['first_day']} ~ {stat['last_day']}）：{_breakdown(stat['events'])}")

    if args.dry_run:
        print("--dry-run：未做任何改动。")
        return 0

    if not args.yes and not _confirm(f"确认删除以上 {stat['total']} 条记录？输入 yes 继续："):
        print("已取消，未做任何改动。")
        return 0

    deleted = purge(where, params)
    print(f"已删除 {deleted} 条记录。")

    if not args.no_vacuum:
        try:
            before, after = reclaim_space()
            print(f"库文件已回收空间：{_size(before)} → {_size(after)}")
        except Exception as e:  # noqa: BLE001 —— 空间没回收不影响删除结果，说清楚就行
            print(f"回收空间失败（记录已删除，不影响使用）：{type(e).__name__}: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
