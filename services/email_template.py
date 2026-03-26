import html
import os
import re

DEFAULT_HASH_LOGO = "https://res.cloudinary.com/dxjjigepf/image/upload/v1774469992/hash_logo_fmngta.png"


def _extract_body(content: str) -> str:
    text = str(content or "")
    match = re.search(r"<body[^>]*>(.*)</body>", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1)
    return text


def build_hfg_email_html(subject: str, content_html: str, preview_text: str = "") -> str:
    safe_subject = html.escape(subject or "Hash For Gamers Update")
    safe_preview = html.escape(preview_text or "")
    logo_url = (os.getenv("HASH_EMAIL_LOGO_URL") or DEFAULT_HASH_LOGO).strip()
    inner = _extract_body(content_html)

    return f"""<!doctype html>
<html>
  <head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>{safe_subject}</title>
  </head>
  <body style=\"margin:0;padding:0;background:#050912;font-family:Arial,Helvetica,sans-serif;color:#e5e7eb;\">
    <div style=\"display:none;max-height:0;overflow:hidden;opacity:0;\">{safe_preview}</div>
    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"padding:24px 12px;\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width:700px;background:#0b1220;border:1px solid #1e2a44;border-radius:12px;overflow:hidden;\">
            <tr>
              <td style=\"padding:20px 24px;background:#050b18;color:#ffffff;\">
                <img src=\"{html.escape(logo_url)}\" alt=\"Hash For Gamers\" style=\"display:block;height:46px;width:auto;margin:0 0 10px 0;\" />
                <div style=\"font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#22c55e;font-weight:700;\">Hash For Gamers</div>
                <div style=\"margin-top:8px;font-size:22px;line-height:1.35;font-weight:700;\">{safe_subject}</div>
              </td>
            </tr>
            <tr>
              <td style=\"padding:24px;color:#e5e7eb;\">{inner}</td>
            </tr>
            <tr>
              <td style=\"padding:14px 24px;border-top:1px solid #1e2a44;background:#091122;color:#94a3b8;font-size:12px;\">
                Need help? Contact <a href=\"mailto:support@hashforgamers.co.in\" style=\"color:#60a5fa;text-decoration:none;\">support@hashforgamers.co.in</a><br/>
                © 2026 Hash For Gamers. All rights reserved.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
