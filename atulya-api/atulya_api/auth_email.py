"""Provider-neutral authentication email delivery."""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def verification_required() -> bool:
    value = os.getenv("ATULYA_AUTH_EMAIL_VERIFICATION", "required").strip().lower()
    return value == "required"


def validate_email_settings() -> None:
    environment = os.getenv("ATULYA_ENVIRONMENT", "development").strip().lower()
    transport = os.getenv("ATULYA_AUTH_EMAIL_TRANSPORT", "console").strip().lower()
    if environment == "production" and verification_required():
        required = ["ATULYA_AUTH_SMTP_HOST", "ATULYA_AUTH_EMAIL_FROM", "ATULYA_AUTH_PUBLIC_URL"]
        missing = [name for name in required if not os.getenv(name)]
        if os.getenv("ATULYA_AUTH_SMTP_USERNAME") and not os.getenv("ATULYA_AUTH_SMTP_PASSWORD"):
            missing.append("ATULYA_AUTH_SMTP_PASSWORD")
        if transport != "smtp" or missing:
            detail = f"; missing {', '.join(missing)}" if missing else ""
            raise RuntimeError(f"Production email verification requires SMTP{detail}")


async def send_auth_email(*, recipient: str, subject: str, text: str) -> None:
    transport = os.getenv("ATULYA_AUTH_EMAIL_TRANSPORT", "console").strip().lower()
    if transport == "console":
        logger.warning("[AUTH EMAIL] to=%s subject=%s\n%s", recipient, subject, text)
        return
    if transport != "smtp":
        raise RuntimeError("ATULYA_AUTH_EMAIL_TRANSPORT must be 'console' or 'smtp'")

    message = EmailMessage()
    message["From"] = os.environ["ATULYA_AUTH_EMAIL_FROM"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)

    host = os.environ["ATULYA_AUTH_SMTP_HOST"]
    port = int(os.getenv("ATULYA_AUTH_SMTP_PORT", "587"))
    username = os.getenv("ATULYA_AUTH_SMTP_USERNAME")
    password = os.getenv("ATULYA_AUTH_SMTP_PASSWORD")

    def _send() -> None:
        with smtplib.SMTP(host, port, timeout=20) as client:
            client.ehlo()
            if os.getenv("ATULYA_AUTH_SMTP_STARTTLS", "true").lower() in {"true", "1", "yes"}:
                client.starttls()
                client.ehlo()
            if username:
                client.login(username, password or "")
            client.send_message(message)

    await asyncio.to_thread(_send)
