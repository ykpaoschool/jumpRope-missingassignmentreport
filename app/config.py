"""从环境变量 / .env 读取配置。"""

import os

from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("TENANT_ID", "").strip()
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "").strip()
SHARED_MAILBOX = os.getenv("SHARED_MAILBOX", "").strip()
SENDER_DISPLAY_NAME = os.getenv("SENDER_DISPLAY_NAME", "教务部门 Academic Office").strip()

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


def is_configured() -> bool:
    """Azure 凭据与共享邮箱是否已配置齐全。"""
    return bool(TENANT_ID and CLIENT_ID and CLIENT_SECRET and SHARED_MAILBOX)


def is_smtp_configured() -> bool:
    """SMTP 渠道是否已配置（至少需 SMTP_HOST 与 SMTP_FROM）。"""
    return bool(SMTP_HOST and SMTP_FROM)
