"""
Memory System
-------------
Tiered persistent memory injected into Layer 2+ agent prompts each run.

  memory/daily/YYYY-MM-DD.md   -- high-signal daily event log
  memory/summary/YYYY-MM.md    -- monthly compressed summaries

load_memory()             -- loads last N daily + M monthly files into a context string
save_daily_memory()       -- extracts high-signal events from today's outputs and saves
compress_monthly_memory() -- on 1st of month, compresses previous month's daily files
"""

import anthropic
from pathlib import Path
from datetime import datetime, timedelta

# Memory file locations (relative to repo root)
MEMORY_DIR  = Path(__file__).parent.parent / "memory"
DAILY_DIR   = MEMORY_DIR / "daily"
SUMMARY_DIR = MEMORY_DIR / "summary"

# Models and token limits
MODEL_MEMORY_EXTRACT  = "claude-haiku-4-5-20251001"
MODEL_MEMORY_MONTHLY  = "claude-haiku-4-5-20251001"
MAX_TOKENS_DAILY      = 400   # tight — daily entries must stay concise
MAX_TOKENS_MONTHLY    = 600   # monthly summaries slightly longer

# How many files to inject per run
DAILY_LOOKBACK   = 7   # days
MONTHLY_LOOKBACK = 5   # months


def load_memory() -> str:
    """
    Returns a formatted prior context string to inject into specialist prompts.
    Monthly summaries first (oldest context), then recent daily logs.
    Returns empty string if no memory files exist yet.
    """
    sections = []

    # Monthly summaries (oldest to newest)
    if SUMMARY_DIR.exists():
        monthly_files = sorted(SUMMARY_DIR.glob("*.md"), reverse=True)[:MONTHLY_LOOKBACK]
        if monthly_files:
            content = "\n\n---\n\n".join(
                f.read_text(encoding="utf-8") for f in reversed(monthly_files)
            )
            sections.append(f"### MONTHLY SUMMARIES\n{content}")

    # Daily logs (oldest to newest)
    if DAILY_DIR.exists():
        daily_files = sorted(DAILY_DIR.glob("*.md"), reverse=True)[:DAILY_LOOKBACK]
        if daily_files:
            content = "\n\n---\n\n".join(
                f.read_text(encoding="utf-8") for f in reversed(daily_files)
            )
            sections.append(f"### RECENT DAILY LOG\n{content}")

    if not sections:
        return ""

    return "## PRIOR CONTEXT\n\n" + "\n\n".join(sections)


def save_daily_memory(client: anthropic.Anthropic, layer_outputs: dict[str, str], date_str: str) -> None:
    """
    Extracts high-signal events from all layer outputs and saves a concise daily entry.
    High-signal = earnings, price moves >2%, flag changes, major news,
    sector bias changes, rating actions, M&A.
    """
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    combined = "\n\n".join(
        f"## {name.upper()}\n{output}"
        for name, output in layer_outputs.items()
    )

    response = client.messages.create(
        model=MODEL_MEMORY_EXTRACT,
        max_tokens=MAX_TOKENS_DAILY,
        messages=[{
            "role": "user",
            "content": (
                f"Date: {date_str}\n\n"
                "Extract only high-signal events from the agent outputs below into a concise "
                "daily memory entry. Include: key price levels (indices, rates, FX, commodities), "
                "major news/events, sector biases, ticker moves >2%, earnings results, rating "
                "changes, flag severity changes, view changes. "
                "Exclude: routine price action, unchanged views, filler commentary. "
                "Max 300 tokens. Use markdown with ## headers per agent/topic.\n\n"
                + combined
            ),
        }],
    )

    entry = f"# {date_str}\n\n{response.content[0].text}"
    (DAILY_DIR / f"{date_str}.md").write_text(entry, encoding="utf-8")
    print(f"[Memory] Saved daily entry: {date_str}.md")


def compress_monthly_memory(client: anthropic.Anthropic, today: datetime) -> None:
    """
    On the 1st of the month, compresses the previous month's daily files into a
    monthly summary. Skips if summary already exists or no daily files found.
    """
    if today.day != 1:
        return

    prev_month   = (today.replace(day=1) - timedelta(days=1))
    month_str    = prev_month.strftime("%Y-%m")
    month_label  = prev_month.strftime("%B %Y")
    summary_path = SUMMARY_DIR / f"{month_str}.md"

    if summary_path.exists() or not DAILY_DIR.exists():
        return

    daily_files = sorted(DAILY_DIR.glob(f"{month_str}-*.md"))
    if not daily_files:
        return

    combined = "\n\n---\n\n".join(f.read_text(encoding="utf-8") for f in daily_files)

    response = client.messages.create(
        model=MODEL_MEMORY_MONTHLY,
        max_tokens=MAX_TOKENS_MONTHLY,
        messages=[{
            "role": "user",
            "content": (
                f"Compress these daily memory entries for {month_label} into a monthly summary. "
                "Preserve: persistent themes, recurring flags, major events (earnings, M&A, "
                "regulatory decisions), trend changes in sector biases, and events still relevant "
                "going forward. Remove: routine price action, one-day anomalies, resolved flags. "
                "Max 500 tokens. Use markdown with ## headers per topic/specialist.\n\n"
                + combined
            ),
        }],
    )

    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        f"# {month_label} Summary\n\n{response.content[0].text}",
        encoding="utf-8"
    )
    print(f"[Memory] Compressed monthly summary: {month_str}.md")
