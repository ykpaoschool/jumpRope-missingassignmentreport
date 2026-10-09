"""FastAPI 入口：上传解析、预览、发送。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    config,
    email_template,
    excel_parser,
    graph_mailer,
    send_job,
    send_log,
    smtp_mailer,
)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Missing Work Mailer")


@app.middleware("http")
async def no_cache_assets(request, call_next):
    """首页与静态资源每次都回源校验，避免部署新版本后浏览器继续跑旧版 app.js。

    前后端版本错配是静默故障：旧 JS 配新接口会报出与真实原因无关的
    TypeError（"Cannot read properties of undefined"），而邮件其实已经发出去了。
    no-cache 只要求回源校验，未变更时仍是 304，单机内网工具无性能顾虑。
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 内存缓存：仅适合单机单人内部工具。
# raw/filename 是给「切换收件邮箱列」用的：切换时不重新上传文件（页面刷新后前端已无
# File 对象），而是用这份原始字节按新列号重跑解析。
_store: dict = {
    "students": [],
    "warnings": [],
    "email_columns": [],
    "email_column": None,
    "email_column_info": None,
    "raw": None,
    "filename": "",
}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


def _mailer(channel: str):
    """根据渠道返回对应的邮件发送模块。"""
    if channel == "smtp":
        return smtp_mailer
    return graph_mailer


def _render(s: dict) -> tuple[str, str]:
    """按 config 中的落款与跳转链接渲染邮件。"""
    return email_template.render_email(
        s,
        sender_display_name=config.SENDER_DISPLAY_NAME,
        sender_contact_email=config.SENDER_CONTACT_EMAIL,
        procedure_url=config.PROCEDURE_URL,
    )


@app.get("/api/status")
def status():
    return {
        "configured": config.is_configured(),
        "shared_mailbox": config.SHARED_MAILBOX,
        "smtp_configured": config.is_smtp_configured(),
        "smtp_host": config.SMTP_HOST,
    }


class TestConnectionRequest(BaseModel):
    channel: str = "graph"  # "graph" | "smtp"


@app.post("/api/test-connection")
def test_connection(req: TestConnectionRequest):
    mailer = _mailer(req.channel)
    if req.channel == "smtp":
        if not config.is_smtp_configured():
            return {"ok": False, "error": "未配置 SMTP（请先填写 .env）"}
    elif not config.is_configured():
        return {"ok": False, "error": "未配置 Azure 凭据（请先填写 .env）"}
    try:
        return mailer.test_connection()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        result = excel_parser.parse_workbook(raw, file.filename or "")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{e}")
    _store.update(result)
    _store["raw"] = raw
    _store["filename"] = file.filename or ""
    return _summary()


class EmailColumnRequest(BaseModel):
    column: int


@app.post("/api/email-column")
def set_email_column(req: EmailColumnRequest):
    """切换收件邮箱列：用留存的原始字节重新解析，不要求前端重新上传文件。

    重跑解析（而不是只换一列取值）是为了让摘要里的有邮箱/缺邮箱统计与警告一起刷新，
    避免列表和统计各说各话。
    """
    raw = _store.get("raw")
    if raw is None:
        raise HTTPException(status_code=400, detail="尚未上传 Excel 文件")
    try:
        result = excel_parser.parse_workbook(raw, _store.get("filename", ""), email_column=req.column)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{e}")
    _store.update(result)
    return _summary()


@app.get("/api/summary")
def get_summary():
    """与上传返回同一个结构：页面重开后靠它恢复第 1 节（解析摘要 + 收件列控件）。"""
    return _summary()


def _summary() -> dict:
    students = _store["students"]
    no_email = [s["student_id"] for s in students if not s["parent_email"]]
    return {
        "uploaded": _store.get("raw") is not None,
        "total_students": len(students),
        "with_email": sum(1 for s in students if s["parent_email"]),
        "no_email": no_email,
        "total_items": sum(len(s["items"]) for s in students),
        "warnings": _store.get("warnings", []),
        "email_columns": _store.get("email_columns", []),
        "email_column": _store.get("email_column"),
        "email_column_info": _store.get("email_column_info"),
    }


@app.get("/api/students")
def get_students():
    return [
        {
            "student_id": s["student_id"],
            "student_name": s.get("student_name", ""),
            "grade": s["grade"],
            "class": s["class"],
            "parent_email": s["parent_email"],
            "item_count": len(s["items"]),
        }
        for s in _store["students"]
    ]


def _find(student_id: str):
    for s in _store["students"]:
        if s["student_id"] == student_id:
            return s
    return None


@app.get("/api/preview/{student_id}")
def preview(student_id: str):
    s = _find(student_id)
    if s is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    subject, html = _render(s)
    return {
        "student_id": student_id,
        "student_name": s.get("student_name", ""),
        "subject": subject,
        "html": html,
        "parent_email": s["parent_email"],
    }


class SendRequest(BaseModel):
    mode: str = "test"  # "test" | "live"
    channel: str = "graph"  # "graph" | "smtp"
    student_ids: Optional[list[str]] = None
    test_email: Optional[str] = None


@app.post("/api/send", status_code=202)
def send(req: SendRequest):
    """校验 + 渲染 + 抢任务锁，立刻返回；实际发信在后台线程里跑。

    这里只做同步的准备工作（模板异常要当场暴露），不在这里发信——整批发完再返回
    会顶穿反向代理的读超时。运行期间内存中的 targets 已快照，重新上传 Excel 不影响
    进行中的任务。
    """
    students = [s for s in _store["students"] if s["parent_email"]]
    if req.student_ids:
        idset = set(req.student_ids)
        students = [s for s in students if s["student_id"] in idset]

    if req.mode == "test":
        if not req.test_email:
            raise HTTPException(status_code=400, detail="测试模式需填写测试邮箱")
        if not req.student_ids:
            students = students[:1]  # 未选择时仅发送一封样例
        targets = [(req.test_email.strip(), s) for s in students]
    else:
        targets = [(s["parent_email"], s) for s in students]

    if not targets:
        raise HTTPException(status_code=400, detail="没有可发送的学生（请检查是否缺少家长邮箱）")

    prepared = []
    for addr, s in targets:
        subject, html = _render(s)
        if req.mode == "test":
            subject = f"[测试 TEST] {subject}"
        prepared.append(
            {
                "student_id": s["student_id"],
                "name": s.get("student_name", ""),
                "to": addr,
                "subject": subject,
                "html": html,
                # 以下三项只为写发送日志：年级/班级/缺交条数只有此刻能拿到，发完就没了
                "grade": s.get("grade", ""),
                "class": s.get("class", ""),
                "item_count": len(s.get("items", [])),
            }
        )

    column_info = _store.get("email_column_info") or {}
    meta = {
        "filename": _store.get("filename", ""),
        "email_column": _store.get("email_column"),
        "email_column_header": column_info.get("header", ""),
    }
    try:
        job = send_job.start(
            prepared, _mailer(req.channel), mode=req.mode, channel=req.channel, meta=meta
        )
    except send_job.JobBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"job_id": job["id"], "total": job["total"]}


@app.get("/api/send/status")
def send_status():
    """当前/最近一次发送任务；前端每秒轮询，页面重开后靠它恢复进度。"""
    return {"job": send_job.snapshot()}


@app.get("/api/logs")
def logs(date: Optional[str] = None, ok: str = "all", limit: int = 200):
    """第 4 节「发送日志」：按日期与结果读 SQLite 里的投递记录。

    与内存里的任务状态互补：任务状态重启即失，日志留得住。
    """
    return send_log.read(day=date, ok=ok, limit=limit)
