"""批量发送任务：状态机 + 后台线程。

发送从 HTTP 请求里挪出来，是为了绕开反向代理的读超时：POST /api/send 只做
「选人 + 渲染 + 抢任务锁」，立刻返回；真正的发信在 daemon 线程里跑，前端轮询
GET /api/send/status 拿进度。

内存态：只保留「当前/最近一次」任务，服务重启即失效（与 _store 解析结果一致）。
因此必须保持 uvicorn 单 worker，否则任务状态会分叉。
持久化只做一件事：每次实际投递与整批开始/结束都写一行到 SQLite（app.send_log），
供事后查「哪天给谁发过、谁失败了」——内存的任务状态本身仍然不落盘。
"""

from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Optional

from . import config, send_log


class JobBusyError(Exception):
    """已有发送任务正在进行中。"""


_lock = threading.Lock()
_job: Optional[dict] = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def snapshot() -> Optional[dict]:
    """返回最近一次任务的深拷贝（无任务时返回 None），供 HTTP 层直接序列化。"""
    with _lock:
        return deepcopy(_job)


def start(targets: list[dict], mailer, mode: str, channel: str, meta: dict | None = None) -> dict:
    """抢占任务锁并启动后台发送线程，返回任务快照。

    targets 元素为 {"student_id", "name", "to", "subject", "html", "grade", "class",
    "item_count"}，由调用方在请求内预先渲染好：模板出问题要立刻反映在请求里，而不是等
    线程跑起来才炸。grade/class/item_count 是写日志用的快照——它们只有这一刻可得。
    meta 为上传文件名与收件列（写 job_start 日志用），有默认值，缺字段也不影响发送。
    已有任务在跑时抛 JobBusyError——串行发送是杜绝重复发信的关键。
    """
    global _job
    with _lock:
        if _job is not None and _job["status"] == "running":
            raise JobBusyError("已有发送任务进行中，请等待完成")
        job = {
            "id": uuid.uuid4().hex[:12],
            "mode": mode,
            "channel": channel,
            "status": "running",
            "total": len(targets),
            "sent": 0,
            "failed": 0,
            "current": "",
            "results": [],
            "started_at": _now(),
            "finished_at": None,
            "error": None,
        }
        _job = job
        initial = deepcopy(job)  # 提交时的视图：线程可能瞬间就跑完，返回值不应随之漂移
    threading.Thread(
        target=_run, args=(job, targets, mailer, meta or {}), name="send-job", daemon=True
    ).start()
    return initial


def _update(job: dict, **fields) -> None:
    with _lock:
        job.update(fields)


def _record(job: dict, result: dict) -> None:
    """写入一条结果并同步计数。整批串行，这里的读写都在锁内保持一致。"""
    with _lock:
        job["results"].append(result)
        if result["ok"]:
            job["sent"] += 1
        else:
            job["failed"] += 1


def _log(event: str, job: dict, **fields) -> None:
    """写一行发送日志，公共字段（job_id / mode / channel）在这里补齐。

    send_log.record() 自己吞异常，所以调用点不需要 try/except。
    """
    send_log.record(
        {
            "event": event,
            "job_id": job["id"],
            "mode": job["mode"],
            "channel": job["channel"],
            **fields,
        }
    )


def _run(job: dict, targets: list[dict], mailer, meta: dict | None = None) -> None:
    """线程主体：一次 session 发完整批；单封失败不中断整批。

    日志写在任务状态翻到终态**之前**：反过来，测试和前端会在状态刚变 done 的瞬间
    读到还缺 job_end 的日志。
    """
    meta = meta or {}
    started = time.perf_counter()
    _log(
        "job_start",
        job,
        total=job["total"],
        filename=meta.get("filename", ""),
        email_column=meta.get("email_column"),
        email_column_header=meta.get("email_column_header", ""),
    )
    try:
        with mailer.session() as sender:
            for i, t in enumerate(targets):
                _update(job, current=f"{t['student_id']} {t.get('name', '')}".strip())
                t0 = time.perf_counter()
                try:
                    sender.send(t["to"], t["subject"], t["html"])
                    result = {"student_id": t["student_id"], "to": t["to"], "ok": True}
                except Exception as e:  # noqa: BLE001
                    result = {
                        "student_id": t["student_id"],
                        "to": t["to"],
                        "ok": False,
                        "error": str(e),
                    }
                _record(job, result)
                _log(
                    "send",
                    job,
                    student_id=t["student_id"],
                    student_name=t.get("name", ""),
                    grade=t.get("grade", ""),
                    class_name=t.get("class", ""),
                    item_count=t.get("item_count"),
                    recipient=t["to"],
                    subject=t["subject"],
                    ok=1 if result["ok"] else 0,
                    error=result.get("error"),
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                )
                if i < len(targets) - 1 and config.SEND_DELAY_SECONDS > 0:
                    time.sleep(config.SEND_DELAY_SECONDS)
    except Exception as e:  # noqa: BLE001
        # 连接/登录阶段就失败：整批转 failed 并给出原因，而不是变成 N 条收件人失败
        # 日志里也要留一行，否则「一封都没发」在日志中是一片空白
        _log(
            "job_end",
            job,
            status="failed",
            error=str(e),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        _update(job, current="", status="failed", error=str(e), finished_at=_now())
        return
    _log(
        "job_end",
        job,
        status="done",
        sent=job["sent"],
        failed=job["failed"],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    _update(job, current="", status="done", finished_at=_now())
