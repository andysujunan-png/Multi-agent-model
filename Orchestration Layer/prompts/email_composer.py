PROMPT = """
You are composing a professional morning briefing email in HTML.
Use the exact structure and inline styles from the template below.
Fill in every [PLACEHOLDER] with real content from the briefing data provided.

RULES:
- Subject line: first line of your response, prefixed with "SUBJECT: "
- Output only the HTML body (everything inside <body>). Do not include <html>, <head>, or <body> tags.
- Use as many sections as needed based on the agents' output (one section per agent / topic).
- For price data, use the table format shown in Section 3.
- For analysis and commentary, use the bullet item format shown in Section 2.
- Bold all key numbers and tickers using <strong>.
- Keep each bullet to 1-2 sentences.
- Footer: today's date and "Morning Briefing".

TEMPLATE:
<div style="font-family:Arial, sans-serif; font-size:14px; color:#222222; max-width:700px;">

  <!-- Header -->
  <div style="background-color:#0D1B2A; padding:16px 20px 12px 20px;">
    <p style="margin:0; font-size:18px; font-weight:bold; color:#ffffff;">
      [EMAIL TITLE]
    </p>
    <p style="margin:4px 0 0 0; font-size:13px; color:#C9A84C;">
      [SUBTITLE OR DATE]
    </p>
  </div>

  <!-- Gold rule -->
  <div style="height:3px; background-color:#C9A84C;"></div>

  <!-- Repeat this block for each section -->
  <div style="background-color:#0D1B2A; padding:8px 20px; margin-top:16px;">
    <p style="margin:0; font-size:11px; font-weight:bold; color:#ffffff; letter-spacing:1px; text-transform:uppercase;">
      [SECTION HEADER]
    </p>
  </div>
  <div style="padding:12px 20px 16px 20px; background-color:#ffffff;">

    <!-- Use paragraph format for analysis/commentary -->
    <p style="margin:0 0 12px 0; font-size:14px; color:#222222; line-height:1.6;">
      <strong>[Bold label or ticker]</strong> [1-2 sentences of content.]<br>
      <span style="font-size:12px; color:#888888; font-style:italic;">Source: [Agent name]</span>
    </p>

    <!-- Use table format for price data -->
    <table style="width:100%; border-collapse:collapse; font-size:13px;">
      <thead>
        <tr style="background-color:#0D1B2A;">
          <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Asset</th>
          <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Price</th>
          <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">Change</th>
          <th style="padding:8px; text-align:left; color:#ffffff; border:1px solid #cccccc;">% Move</th>
        </tr>
      </thead>
      <tbody>
        <!-- Alternate row colors: #f5f5f5 and #ffffff -->
        <tr style="background-color:#f5f5f5;">
          <td style="padding:7px; border:1px solid #cccccc;">[Asset]</td>
          <td style="padding:7px; border:1px solid #cccccc;">[Price]</td>
          <td style="padding:7px; border:1px solid #cccccc;">[Change]</td>
          <td style="padding:7px; border:1px solid #cccccc;">[% Move]</td>
        </tr>
      </tbody>
    </table>

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
