import asyncio
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from html import unescape

import jinja2


def _smtp_settings():
    """Read SMTP settings from env (supports both SMTP__X nested and flat SMTP_X)."""
    def env(*names, default=None):
        for n in names:
            v = os.environ.get(n)
            if v:
                return v
        return default

    host = env("SMTP__HOST", "SMTP_HOST")
    user = env("SMTP__USER", "SMTP_USER")
    password = env("SMTP__PASSWORD", "SMTP_PASSWORD")
    port = int(env("SMTP__PORT", "SMTP_PORT", default="587"))
    sender = env("SMTP__FROM", "SMTP_FROM", default=user)
    return host, port, user, password, sender


def _html_to_text(html: str) -> str:
    """Crude tag strip so an HTML-only body still has a readable text part."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6]|table)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _send_sync(to: str, subject: str, body: str, text: str | None = None):
    host, port, user, password, sender = _smtp_settings()

    is_html = "<" in body and "</" in body

    # Dev / not-configured fallback: log the message so the verification link is
    # still reachable from the app logs. Keeps signup working without SMTP creds.
    if not (host and user and password):
        preview = text or (_html_to_text(body) if is_html else body)
        print(f"[email:dev] (no SMTP configured) To {to} | Subject: {subject}\n{preview}")
        return

    msg = EmailMessage()
    # A display name reads as legitimate mail (bare addresses look more spammy).
    msg["From"] = formataddr(("Talos", sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Reply-To"] = sender
    if is_html:
        msg.set_content(text or _html_to_text(body))
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        print(f"[email] sent to {to} | Subject: {subject}")
    except Exception as e:  # noqa: BLE001 - don't let email failure break the request flow
        print(f"[email:error] failed to send to {to}: {e!r}")
        # keep the dev flow usable even if sending fails
        print(f"[email:dev-fallback] To {to} | Subject: {subject}\n{body}")


async def send_email(
        to: str,
        template: jinja2.Template | str,
        subject: str = "Talos",
        *,
        text: str | None = None,
        **kwargs
):
    """
    Email the specified recipient with the given template and context.

    `template` may be a jinja Template, a plain-text string, or an HTML string
    (auto-detected). Pass `text` to supply the plain-text alternative for an
    HTML body. Uses SMTP when SMTP__HOST/USER/PASSWORD are configured
    (Gmail-compatible), otherwise falls back to logging so dev flows keep working.
    """
    if isinstance(template, jinja2.Template):
        body = template.render(**kwargs)
    elif isinstance(template, str):
        body = template
    else:
        raise ValueError("Invalid template type")

    # smtplib is blocking; run it off the event loop.
    await asyncio.to_thread(_send_sync, to, subject, body, text)
