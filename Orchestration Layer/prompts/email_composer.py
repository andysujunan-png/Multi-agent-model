PROMPT = """
You are composing a professional morning briefing email in HTML.
Use the exact structure and inline styles from the template below.
Fill in every [PLACEHOLDER] with real content from the briefing data provided.

RULES:
- Subject line: first line of your response, prefixed with "SUBJECT: "
- Output only the HTML body content inside the outer <div>. Do not include <html>, <head>, or <body> tags.
- The email must have exactly two main sections:
  1. MACRO & MARKETS — drawn from the universal market data (indices, FX, rates, commodities, headlines)
  2. P&C INSURANCE SECTOR — drawn from the insurance specialist output (sector bias, ticker views, themes, flags)
- Within each section, use the table format for price/data rows and the bullet format for analysis/commentary.
- Bold all key numbers and tickers using <strong>.
- Keep each bullet to 1-2 sentences.
- Footer: today's date and "Morning Briefing".
- As more sector specialists are added in future, add a new section per specialist between MACRO and the footer.

TEMPLATE:
<div style="font-family:Arial, sans-serif; font-size:14px; color:#222222; max-width:700px;">

  <!-- Header -->
  <div style="background-color:#0D1B2A; padding:16px 20px 12px 20px;">
    <p style="margin:0; font-size:18px; font-weight:bold; color:#ffffff;">
      [EMAIL TITLE]
    </p>
    <p style="margin:4px 0 0 0; font-size:13px; color:#C9A84C;">
      [DATE]
    </p>
  </div>

  <!-- Gold rule -->
  <div style="height:3px; background-color:#C9A84C;"></div>

  <!-- SECTION: MACRO & MARKETS -->
  <div style="background-color:#0D1B2A; padding:8px 20px; margin-top:16px;">
    <p style="margin:0; font-size:11px; font-weight:bold; color:#ffffff; letter-spacing:1px; text-transform:uppercase;">
      Macro &amp; Markets
    </p>
  </div>
  <div style="padding:12px 20px 16px 20px; background-color:#ffffff;">

    <!-- Price table — indices, FX, commodities, rates -->
    <table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom:16px;">
      <thead>
        <tr style="background-color:#0D1B2A;">
          <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Asset</th>
          <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Level</th>
          <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Change</th>
        </tr>
      </thead>
      <tbody>
        <!-- Alternate row colors: #f5f5f5 and #ffffff -->
        <tr style="background-color:#f5f5f5;">
          <td style="padding:7px; border:1px solid #cccccc;">[Asset]</td>
          <td style="padding:7px; border:1px solid #cccccc;">[Level]</td>
          <td style="padding:7px; border:1px solid #cccccc;">[Change]</td>
        </tr>
      </tbody>
    </table>

    <!-- Key headlines as bullets -->
    <p style="margin:0 0 12px 0; font-size:14px; color:#222222; line-height:1.6;">
      <strong>[Headline label]</strong> [1-2 sentence summary.]
    </p>

  </div>

  <!-- SECTION: P&C INSURANCE -->
  <div style="background-color:#0D1B2A; padding:8px 20px; margin-top:8px;">
    <p style="margin:0; font-size:11px; font-weight:bold; color:#ffffff; letter-spacing:1px; text-transform:uppercase;">
      P&amp;C Insurance Sector
    </p>
  </div>
  <div style="padding:12px 20px 16px 20px; background-color:#ffffff;">

    <!-- Sector bias line -->
    <p style="margin:0 0 12px 0; font-size:14px; color:#222222; line-height:1.6;">
      <strong>Sector Bias:</strong> [CONSTRUCTIVE/NEUTRAL/CAUTIOUS] — [one sentence rationale.]
    </p>

    <!-- Key themes and ticker views as bullets -->
    <p style="margin:0 0 12px 0; font-size:14px; color:#222222; line-height:1.6;">
      <strong>[Ticker or Theme]</strong> [1-2 sentence view.]<br>
      <span style="font-size:12px; color:#888888; font-style:italic;">View: [OVERWEIGHT/NEUTRAL/UNDERWEIGHT]</span>
    </p>

    <!-- Flags -->
    <p style="margin:0 0 12px 0; font-size:14px; color:#222222; line-height:1.6;">
      <strong>[Flag title]</strong> [1-2 sentence detail.]
    </p>

  </div>

  <!-- Footer -->
  <div style="border-top:1px solid #cccccc; padding:10px 20px; margin-top:8px;">
    <p style="margin:0; font-size:11px; color:#aaaaaa; text-align:center;">
      Morning Briefing &nbsp;|&nbsp; [Date]
    </p>
  </div>

</div>

--- BRIEFING ---
{final_output}
""".strip()
