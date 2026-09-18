import html
import os
import re
from datetime import datetime
from html.parser import HTMLParser

DEFAULT_HASH_LOGO = "https://res.cloudinary.com/dxjjigepf/image/upload/v1774472024/hash_for_gamer_logo_d1v4wc.png"


def _extract_body(content: str) -> str:
    text = str(content or "")
    match = re.search(r"<body[^>]*>(.*)</body>", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1)
    return text


def build_hfg_email_html(subject: str, content_html: str = "", preview_text: str = "", *, heading=None, body_text=None) -> str:
    if body_text is not None:
        content_html = "".join(
            '<p style="margin:0 0 16px;">' + html.escape(part).replace("\n", "<br />") + '</p>'
            for part in str(body_text).split("\n\n")
        )
    safe_subject = html.escape(subject or "Hash For Gamers Update")
    safe_preview = html.escape(" ".join(str(preview_text or "An update from Hash For Gamers.").split())[:160])
    display_heading = heading if heading is not None else subject or "Account update"
    if heading is None:
        display_heading = re.sub(r"\s*(?:\||-|·)\s*Hash For Gamers$", "", display_heading, flags=re.I)
        display_heading = re.sub(r"^Hash For Gamers\s*(?:\||-|·)\s*", "", display_heading, flags=re.I)
    safe_heading = html.escape(display_heading)
    logo_url = (os.getenv("HASH_EMAIL_LOGO_URL") or DEFAULT_HASH_LOGO).strip()
    inner = _extract_body(content_html)
    year = datetime.now().year
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="color-scheme" content="light dark" />
    <meta name="supported-color-schemes" content="light dark" />
    <title>{safe_subject}</title>
    <style>
      .hfg-content p {{ font-size:15px; line-height:1.65; }}
      .hfg-content table {{ max-width:100%; }}
      .hfg-content td, .hfg-content th {{ overflow-wrap:anywhere; word-break:break-word; }}
      .hfg-content a {{ overflow-wrap:anywhere; }}
      .hfg-content img {{ max-width:100%; height:auto; }}
      @media screen and (max-width: 480px) {{
        .hfg-padding {{ padding-left:20px !important; padding-right:20px !important; }}
        .hfg-title {{ font-size:24px !important; }}
        .hfg-content table {{ table-layout:fixed; width:100% !important; }}
        .hfg-content td, .hfg-content th {{ font-size:13px; padding-left:6px !important; padding-right:6px !important; }}
      }}
    </style>
  </head>
  <body style="margin:0;padding:0;background-color:#050912;font-family:Arial,Helvetica,sans-serif;color:#e5e7eb;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{safe_preview}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#050912" style="background-color:#050912;padding:20px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background-color:#0b1220;border:1px solid #1e2a44;border-radius:12px;overflow:hidden;">
            <tr>
              <td class="hfg-padding" bgcolor="#0b1220" style="padding:24px;background-color:#0b1220;color:#ffffff;">
                <img src="{html.escape(logo_url)}" alt="Hash For Gamers" style="display:block;height:44px;width:44px;margin:0 0 10px 0;border-radius:10px;" />
                <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#22c55e;font-weight:700;">Hash For Gamers</div>
                <h1 class="hfg-title" style="margin:12px 0 0;font-size:26px;line-height:1.3;font-weight:700;color:#ffffff;">{safe_heading}</h1>
              </td>
            </tr>
            <tr>
              <td class="hfg-padding hfg-content" bgcolor="#0b1220" style="padding:0 24px 24px;background-color:#0b1220;color:#e5e7eb;font-size:16px;line-height:1.6;">
                {inner}
              </td>
            </tr>
            <tr>
              <td class="hfg-padding" bgcolor="#091122" style="padding:18px 24px;border-top:1px solid #1e2a44;background:#091122;color:#b8c5d6;font-size:12px;line-height:1.6;">
                Need help? Contact <a href="mailto:support@hashforgamers.co.in" style="color:#60a5fa;text-decoration:none;">support@hashforgamers.co.in</a><br/>
                © {year} Hash For Gamers. All rights reserved.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


class _EmailText(HTMLParser):
    """Generate a useful plain-text alternative, retaining links and table values."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"p", "div", "tr", "h1", "h2", "h3", "br", "ul", "ol"}:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("\n- ")
        if tag in {"td", "th"}:
            self.parts.append(" | ")
        if tag == "a":
            self.links.append(attrs.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "a" and self.links:
            href = self.links.pop()
            if href.startswith(("https://", "http://", "mailto:")):
                self.parts.append(" (" + href.removeprefix("mailto:") + ")")
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(re.sub(r"\s+", " ", data))


def email_text(content_html: str) -> str:
    parser = _EmailText()
    parser.feed(_extract_body(content_html))
    lines = [re.sub(r"[ \t]+", " ", line).strip(" |") for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)
