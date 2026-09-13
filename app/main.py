"""FastAPI 入口：上传解析、预览、发送。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, email_template, excel_parser, graph_mailer, smtp_mailer

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Missing Work Mailer")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 内存缓存：仅适合单机单人内部工具
_store: dict = {"students": [], "warnings": []}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


def _mailer(channel: str):
    """根据渠道返回对应的邮件发送模块。"""
    if channel == "smtp":
        return smtp_mailer
    return graph_mailer


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
    return _summary()


def _summary() -> dict:
    students = _store["students"]
    no_email = [s["student_id"] for s in students if not s["parent_email"]]
    return {
        "total_students": len(students),
        "with_email": sum(1 for s in students if s["parent_email"]),
        "no_email": no_email,
        "total_items": sum(len(s["items"]) for s in students),
        "warnings": _store.get("warnings", []),
    }


@app.get("/api/students")
def get_students():
    return [
        {
            "student_id": s["student_id"],
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
    subject, html = email_template.render_email(s, config.SENDER_DISPLAY_NAME)
    return {
        "student_id": student_id,
        "subject": subject,
        "html": html,
        "parent_email": s["parent_email"],
    }


class SendRequest(BaseModel):
    mode: str = "test"  # "test" | "live"
    channel: str = "graph"  # "graph" | "smtp"
    student_ids: Optional[list[str]] = None
    test_email: Optional[str] = None


@app.post("/api/send")
def send(req: SendRequest):
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

    results = []
    mailer = _mailer(req.channel)
    for addr, s in targets:
        subject, html = email_template.render_email(s, config.SENDER_DISPLAY_NAME)
        if req.mode == "test":
            subject = f"[测试 TEST] {subject}"
        try:
            mailer.send_email(addr, subject, html)
            results.append({"student_id": s["student_id"], "to": addr, "ok": True})
        except Exception as e:  # noqa: BLE001
            results.append({"student_id": s["student_id"], "to": addr, "ok": False, "error": str(e)})
        time.sleep(config.SEND_DELAY_SECONDS)

    sent = sum(1 for r in results if r["ok"])
    return {"sent": sent, "failed": len(results) - sent, "results": results}
