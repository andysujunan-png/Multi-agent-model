"""
Email Composer and Sender
--------------------------
compose_email() -- instructs Claude to fill the HTML template from agent outputs
send_email()    -- sends the composed email via Gmail SMTP

HTML template is embedded directly in this file — edit TEMPLATE to change formatting.
Model and token limit are defined here for easy audit.
"""

import os
import smtplib
import anthropic
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Model used for email composition
MODEL_EMAIL      = "claude-opus-4-6"   # quality matters for client-facing output
MAX_TOKENS_EMAIL = 4096


# ============================================================
# HTML Template
# Edit this block to change the email layout and styling.
# ============================================================

TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#ffffff;">
<div style="font-family:Arial, sans-serif; font-size:14px; color:#222222; max-width:700px;">

  <!-- Header -->
  <div style="background-color:#0D1B2A; padding:16px 20px 12px 20px;">
    <p style="margin:0; font-size:18px; font-weight:bold; color:#ffffff;">
      {title}
    </p>
    <p style="margin:4px 0 0 0; font-size:13px; color:#C9A84C;">
      {date}
    </p>
  </div>

  <!-- Gold rule -->
  <div style="height:3px; background-color:#C9A84C;"></div>

  <!-- MACRO & MARKETS section -->
  <div style="background-color:#0D1B2A; padding:8px 20px; margin-top:16px;">
    <p style="margin:0; font-size:11px; font-weight:bold; color:#ffffff; letter-spacing:1px; text-transform:uppercase;">
      Macro &amp; Markets
    </p>
  </div>
  <div style="padding:12px 20px 16px 20px; background-color:#ffffff;">
    {macro_table}
    {macro_bullets}
  </div>

  <!-- One block per sector specialist — repeat for each -->
  {sector_sections}

  <!-- Footer -->
  <div style="border-top:1px solid #cccccc; padding:10px 20px; margin-top:8px;">
    <p style="margin:0; font-size:11px; color:#aaaaaa; text-align:center;">
      Morning Briefing &nbsp;|&nbsp; {date}
    </p>
  </div>

</div>
</body>
</html>
""".strip()

SECTOR_SECTION_TEMPLATE = """
  <div style="background-color:#0D1B2A; padding:8px 20px; margin-top:8px;">
    <p style="margin:0; font-size:11px; font-weight:bold; color:#ffffff; letter-spacing:1px; text-transform:uppercase;">
      {section_title}
    </p>
  </div>
  <div style="padding:12px 20px 16px 20px; background-color:#ffffff;">
    {section_content}
  </div>
""".strip()

TABLE_ROW_EVEN = '<tr style="background-color:#f5f5f5;"><td style="padding:7px; border:1px solid #cccccc;">{col1}</td><td style="padding:7px; border:1px solid #cccccc;">{col2}</td><td style="padding:7px; border:1px solid #cccccc;">{col3}</td></tr>'
TABLE_ROW_ODD  = '<tr style="background-color:#ffffff;"><td style="padding:7px; border:1px solid #cccccc;">{col1}</td><td style="padding:7px; border:1px solid #cccccc;">{col2}</td><td style="padding:7px; border:1px solid #cccccc;">{col3}</td></tr>'

TABLE_HEADER = """
<table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom:16px;">
  <thead>
    <tr style="background-color:#0D1B2A;">
      <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Asset</th>
      <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Level</th>
      <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Change</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
""".strip()

BULLET = '<p style="margin:0 0 12px 0; font-size:14px; color:#222222; line-height:1.6;"><strong>{label}</strong> {body}</p>'


# ============================================================
# Compose prompt
# ============================================================

COMPOSE_PROMPT = """
You are composing a professional morning briefing email in HTML.
You will be given the full briefing data from all agents below.
Return only valid HTML that fills the template — no prose, no markdown, no explanation.

Your response must be structured as follows (each on its own line):
SUBJECT: <subject line>
TITLE: <email title>
DATE: <today's date, e.g. Friday, 17 April 2026>

MACRO_TABLE:
<table rows only — one row per asset, format: ASSET | LEVEL | CHANGE>

MACRO_BULLETS:
<key headlines and macro commentary as bullet points, one per line, format: LABEL: body>

SECTOR_SECTIONS:
<one block per specialist, format:>
SECTION: <section title>
BIAS: <overall sector bias line>
BULLETS:
<bullet per key ticker or theme, format: LABEL: body>
FLAGS:
<bullet per active flag, format: LABEL: body>
END_SECTION

Rules:
- Bold all key numbers using <strong> tags in bullet bodies
- Keep each bullet to 1-2 sentences
- Include all tickers with non-neutral views
- Include all RED and AMBER flags
- Do not truncate — include all material content

--- BRIEFING ---
{final_output}
""".strip()


# ============================================================
# Compose email
# ============================================================

def compose_email(client: anthropic.Anthropic, final_output: str) -> tuple[str, str]:
    """
    Uses MODEL_EMAIL (Opus) to extract structured content from agent outputs,
    then builds the HTML email from the embedded template.
    Returns (subject, html_body).
    """
    response = client.messages.create(
        model=MODEL_EMAIL,
        max_tokens=MAX_TOKENS_EMAIL,
        messages=[{"role": "user", "content": COMPOSE_PROMPT.format(final_output=final_output)}],
    )
    raw = next(b.text for b in response.content if b.type == "text")
    return _parse_and_build(raw)


def _parse_and_build(raw: str) -> tuple[str, str]:
    """Parses the structured response and builds the final HTML."""
    lines = raw.strip().splitlines()

    subject = "Morning Briefing"
    title   = "Morning Briefing"
    date    = ""
    macro_table_rows: list[str] = []
    macro_bullets: list[str]    = []
    sector_sections: list[str]  = []

    mode = None
    current_section: dict = {}
    current_bullets: list[str] = []
    current_flags: list[str]   = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("SUBJECT:"):
            subject = stripped[len("SUBJECT:"):].strip()
        elif stripped.startswith("TITLE:"):
            title = stripped[len("TITLE:"):].strip()
        elif stripped.startswith("DATE:"):
            date = stripped[len("DATE:"):].strip()
        elif stripped == "MACRO_TABLE:":
            mode = "macro_table"
        elif stripped == "MACRO_BULLETS:":
            mode = "macro_bullets"
        elif stripped == "SECTOR_SECTIONS:":
            mode = "sector_sections"
        elif stripped.startswith("SECTION:") and mode == "sector_sections":
            if current_section:
                sector_sections.append(_build_section(current_section, current_bullets, current_flags))
            current_section = {"title": stripped[len("SECTION:"):].strip()}
            current_bullets = []
            current_flags   = []
            mode = "section_header"
        elif stripped.startswith("BIAS:") and mode in ("section_header", "section_bullets", "section_flags"):
            current_section["bias"] = stripped[len("BIAS:"):].strip()
        elif stripped == "BULLETS:" :
            mode = "section_bullets"
        elif stripped == "FLAGS:":
            mode = "section_flags"
        elif stripped == "END_SECTION":
            if current_section:
                sector_sections.append(_build_section(current_section, current_bullets, current_flags))
            current_section = {}
            current_bullets = []
            current_flags   = []
            mode = "sector_sections"
        elif stripped and mode == "macro_table":
            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) == 3:
                idx = len(macro_table_rows)
                row_tpl = TABLE_ROW_EVEN if idx % 2 == 0 else TABLE_ROW_ODD
                macro_table_rows.append(row_tpl.format(col1=parts[0], col2=parts[1], col3=parts[2]))
        elif stripped and mode == "macro_bullets":
            if ":" in stripped:
                label, _, body = stripped.partition(":")
                macro_bullets.append(BULLET.format(label=label.strip(), body=body.strip()))
        elif stripped and mode == "section_bullets":
            if ":" in stripped:
                label, _, body = stripped.partition(":")
                current_bullets.append(BULLET.format(label=label.strip(), body=body.strip()))
        elif stripped and mode == "section_flags":
            if ":" in stripped:
                label, _, body = stripped.partition(":")
                current_flags.append(BULLET.format(label=label.strip(), body=body.strip()))

    # Catch any unclosed section
    if current_section:
        sector_sections.append(_build_section(current_section, current_bullets, current_flags))

    macro_table_html  = TABLE_HEADER.format(rows="\n".join(macro_table_rows)) if macro_table_rows else ""
    macro_bullets_html = "\n".join(macro_bullets)
    sector_html        = "\n".join(sector_sections)

    html = TEMPLATE.format(
        title=title,
        date=date,
        macro_table=macro_table_html,
        macro_bullets=macro_bullets_html,
        sector_sections=sector_html,
    )
    return subject, html


def _build_section(section: dict, bullets: list[str], flags: list[str]) -> str:
    bias_line = ""
    if section.get("bias"):
        bias_line = BULLET.format(label="Sector Bias", body=section["bias"])

    content = bias_line + "\n".join(bullets)
    if flags:
        content += '<p style="margin:8px 0 4px 0; font-size:11px; font-weight:bold; color:#888888; text-transform:uppercase; letter-spacing:1px;">Flags</p>'
        content += "\n".join(flags)

    return SECTOR_SECTION_TEMPLATE.format(
        section_title=section.get("title", "Sector"),
        section_content=content,
    )


# ============================================================
# Send email
# ============================================================

def send_email(subject: str, html_body: str) -> None:
    sender    = os.environ["EMAIL_ADDRESS"]
    password  = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_RECIPIENT"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    print(f"\n[OK] Email sent to {recipient}")
