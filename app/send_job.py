"""批量发送任务：状态机 + 后台线程。

发送从 HTTP 请求里挪出来，是为了绕开反向代理的读超时：POST /api/send 只做
「选人 + 渲染 + 抢任务锁」，立刻返回；真正的发信在 daemon 线程里跑，前端轮询
GET /api/send/status 拿进度。

内存态：只保留「当前/最近一次」任务，服务重启即失效（与 _store 解析结果一致）。
因此必须保持 uvicorn 单 worker，否则任务状态会分叉。
"""

from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Optional

from . import config


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


def start(targets: list[dict], mailer, mode: str, channel: str) -> dict:
    """抢占任务锁并启动后台发送线程，返回任务快照。

    targets 元素为 {"student_id", "name", "to", "subject", "html"}，由调用方在请求内
    预先渲染好：模板出问题要立刻反映在请求里，而不是等线程跑起来才炸。
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
        target=_run, args=(job, targets, mailer), name="send-job", daemon=True
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


def _run(job: dict, targets: list[dict], mailer) -> None:
    """线程主体：一次 session 发完整批；单封失败不中断整批。"""
    try:
        with mailer.session() as sender:
            for i, t in enumerate(targets):
                _update(job, current=f"{t['student_id']} {t.get('name', '')}".strip())
                try:
                    sender.send(t["to"], t["subject"], t["html"])
                    _record(job, {"student_id": t["student_id"], "to": t["to"], "ok": True})
                except Exception as e:  # noqa: BLE001
                    _record(
                        job,
                        {
                            "student_id": t["student_id"],
                            "to": t["to"],
                            "ok": False,
                            "error": str(e),
                        },
                    )
                if i < len(targets) - 1 and config.SEND_DELAY_SECONDS > 0:
                    time.sleep(config.SEND_DELAY_SECONDS)
    except Exception as e:  # noqa: BLE001
        # 连接/登录阶段就失败：整批转 failed 并给出原因，而不是变成 N 条收件人失败
        _update(job, current="", status="failed", error=str(e), finished_at=_now())
        return
    _update(job, current="", status="done", finished_at=_now())
