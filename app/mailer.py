"""Optional SMTP sender for password-reset codes. Without TRIPPY_SMTP_HOST, codes go to the server log.

Environment:
  TRIPPY_SMTP_HOST, TRIPPY_SMTP_PORT (default 587)
  TRIPPY_SMTP_USERNAME, TRIPPY_SMTP_PASSWORD
  TRIPPY_SMTP_FROM            e.g. "Trippy <trippy@example.com>" (default: the username)
  TRIPPY_SMTP_SECURITY        starttls (default) | ssl | none
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("trippy.mailer")


def configured() -> bool:
    return bool(os.getenv("TRIPPY_SMTP_HOST", "").strip())


def reset_message(to: str, code: str) -> EmailMessage:
    sender = os.getenv("TRIPPY_SMTP_FROM", "").strip() or os.getenv("TRIPPY_SMTP_USERNAME", "").strip()
    msg = EmailMessage()
    msg["Subject"] = "Your Trippy password reset code"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(
        f"Someone asked to reset the password for {to} on Trippy.\n\n"
        f"Your reset code: {code}\n\n"
        "Paste it into the app within an hour. If you didn't ask for this, ignore this email.\n")
    return msg


def send_reset_code(to: str, code: str) -> None:
    host = os.getenv("TRIPPY_SMTP_HOST", "").strip()
    port = int(os.getenv("TRIPPY_SMTP_PORT", "587") or 587)
    security = os.getenv("TRIPPY_SMTP_SECURITY", "starttls").strip().lower()
    user = os.getenv("TRIPPY_SMTP_USERNAME", "").strip()
    password = os.getenv("TRIPPY_SMTP_PASSWORD", "")
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if security == "starttls":
                server.starttls(context=ssl.create_default_context())
        with server:
            if user:
                server.login(user, password)
            server.send_message(reset_message(to, code))
        log.info("Sent a password reset code to %s", to)
    except Exception:  # never surface SMTP trouble to the caller; the code is still valid
        log.exception("Couldn't email the password reset code to %s; check the TRIPPY_SMTP_* settings", to)
