"""从环境变量 / .env 读取配置。"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("TENANT_ID", "").strip()
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "").strip()
SHARED_MAILBOX = os.getenv("SHARED_MAILBOX", "").strip()
SENDER_DISPLAY_NAME = os.getenv(
    "SENDER_DISPLAY_NAME", "包校初中部学术办公室/YK Pao Middle School Academic Affairs Office"
).strip()
SENDER_CONTACT_EMAIL = os.getenv("SENDER_CONTACT_EMAIL", "hq-aao@ykpaoschool.cn").strip()

# 邮件正文中「请点击此处查看未按时提交作业处理程序」的跳转地址；留空则该句退化为普通文字
PROCEDURE_URL = os.getenv("PROCEDURE_URL", "https://shorturl.myykps.cn/ms-pfswt").strip()

# SMTP（快速测试渠道）
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").strip().lower() in ("1", "true", "yes", "on")


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


SEND_DELAY_SECONDS = _as_float(os.getenv("SEND_DELAY_SECONDS", "0.5"), 0.5)

# 发送日志（SQLite）的库文件。锚定到项目根的绝对路径（同 main.py 的 BASE_DIR / "static"），
# 免得落点由 uvicorn 的 CWD 决定；容器里自然就是 /app/data/mailer.db。
DB_PATH = os.getenv("DB_PATH", "").strip() or str(
    Path(__file__).resolve().parent.parent / "data" / "mailer.db"
)


def is_configured() -> bool:
    """Azure 凭据与共享邮箱是否已配置齐全。"""
    return bool(TENANT_ID and CLIENT_ID and CLIENT_SECRET and SHARED_MAILBOX)


def is_smtp_configured() -> bool:
    """SMTP 渠道是否已配置（至少需 SMTP_HOST 与 SMTP_FROM）。"""
    return bool(SMTP_HOST and SMTP_FROM)
