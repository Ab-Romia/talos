"""Branded HTML email builders (Talos "Research Desk" — warm neutral + amber).

Each builder returns an (html, text) pair; the text part is the plain-text
fallback carried alongside the HTML alternative for clients that reject HTML.
"""
from html import escape

BRAND = "Talos"
TAGLINE = "Your workspace, retrieved."

AMBER = "#C4913A"
INK = "#1C1B1A"
INK_SOFT = "#6B6560"
BG = "#F4F1ED"
CARD = "#FFFFFF"
BORDER = "#E7E1D8"
FONT = "'Inter', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:28px 0 8px;"><tr>'
        f'<td align="center" bgcolor="{AMBER}" style="border-radius:10px;">'
        f'<a href="{escape(url)}" target="_blank" '
        f'style="display:inline-block;padding:14px 30px;font-family:{FONT};font-size:15px;'
        'font-weight:600;line-height:1;color:#ffffff;text-decoration:none;border-radius:10px;">'
        f'{escape(label)}</a></td></tr></table>'
    )


def _shell(heading: str, body_html: str, preheader: str = "") -> str:
    return f"""\
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{escape(BRAND)}</title></head>
<body style="margin:0;padding:0;background:{BG};">
<span style="display:none!important;visibility:hidden;opacity:0;height:0;width:0;overflow:hidden;mso-hide:all;">{escape(preheader)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BG};padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;">
  <tr><td style="padding:4px 8px 22px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="width:38px;height:38px;background:{AMBER};border-radius:9px;text-align:center;vertical-align:middle;font-family:{FONT};font-size:19px;font-weight:700;color:#ffffff;">T</td>
      <td style="padding-left:12px;font-family:{FONT};font-size:19px;font-weight:700;color:{INK};letter-spacing:-0.2px;">{escape(BRAND)}</td>
    </tr></table>
  </td></tr>
  <tr><td style="background:{CARD};border:1px solid {BORDER};border-radius:16px;padding:38px 40px;">
    <h1 style="margin:0 0 16px;font-family:{FONT};font-size:22px;line-height:1.3;font-weight:700;color:{INK};letter-spacing:-0.3px;">{escape(heading)}</h1>
    {body_html}
  </td></tr>
  <tr><td style="padding:22px 12px 4px;font-family:{FONT};font-size:12px;line-height:1.6;color:{INK_SOFT};">
    {escape(BRAND)} · {escape(TAGLINE)}<br>
    You're receiving this email because an action was requested for your {escape(BRAND)} account.
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _p(text: str) -> str:
    return (
        f'<p style="margin:0 0 14px;font-family:{FONT};font-size:15px;line-height:1.65;color:{INK_SOFT};">'
        f'{text}</p>'
    )


def _fallback_link(url: str) -> str:
    return (
        f'<p style="margin:18px 0 0;font-family:{FONT};font-size:12px;line-height:1.6;color:{INK_SOFT};">'
        'If the button doesn\'t work, copy and paste this link into your browser:<br>'
        f'<a href="{escape(url)}" target="_blank" style="color:{AMBER};word-break:break-all;">{escape(url)}</a>'
        '</p>'
    )


def verification_email(verify_url: str) -> tuple[str, str]:
    body = (
        _p("Welcome aboard. You're one step away from your Talos workspace — confirm this email address to finish creating your account.")
        + _button("Verify my email", verify_url)
        + _p('<span style="font-size:13px;">This link expires in 1 hour. If you didn\'t sign up for Talos, you can safely ignore this email.</span>')
        + _fallback_link(verify_url)
    )
    html = _shell("Verify your email address", body, preheader="Confirm your email to finish setting up Talos.")
    text = (
        "Welcome to Talos!\n\n"
        "Confirm your email to finish creating your account:\n"
        f"{verify_url}\n\n"
        "This link expires in 1 hour. If you didn't sign up for Talos, ignore this email."
    )
    return html, text


def password_reset_email(reset_url: str) -> tuple[str, str]:
    body = (
        _p("We received a request to reset the password for your Talos account. Click below to choose a new one.")
        + _button("Reset my password", reset_url)
        + _p('<span style="font-size:13px;">If you didn\'t request this, you can safely ignore this email — your password won\'t change. This link expires shortly.</span>')
        + _fallback_link(reset_url)
    )
    html = _shell("Reset your password", body, preheader="Reset the password for your Talos account.")
    text = (
        "You requested a password reset for your Talos account.\n\n"
        "Choose a new password:\n"
        f"{reset_url}\n\n"
        "If you didn't request this, ignore this email. This link expires shortly."
    )
    return html, text


def notification_email(title: str, body_text: str, url: str | None = None) -> tuple[str, str]:
    inner = _p(escape(body_text).replace("\n", "<br>"))
    if url:
        inner += _button("Open in Talos", url)
    html = _shell(title, inner, preheader=body_text[:120])
    text = f"{body_text}\n\n— Talos"
    if url:
        text += f"\n\nOpen in Talos: {url}"
    return html, text
