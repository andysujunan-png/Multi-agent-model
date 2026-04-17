"""
Morning Briefing Pipeline
--------------------------
Runs daily via GitHub Actions at 8am SGT (00:00 UTC).

Flow (each layer runs in parallel, feeds into the next):
  Layer 1 -- Data Fetchers     : universal market data (macro, rates, FX, indices, commodities)
  Layer 2 -- Sector Specialists: insurance, banks, energy, etc. (each also fetches own niche data)
  Layer 3 -- Synthesis         : macro agent, value investing agent, portfolio agent, etc.
  Final   -- Claude API        : composes formatted email
             Gmail SMTP        : sends to recipient

Between each layer, a compression step (Haiku) summarises outputs before passing to the next
layer, keeping token usage minimal.

Memory system (tiered):
  memory/daily/YYYY-MM-DD.md   -- high-signal daily event log (last 7 injected per run)
  memory/summary/YYYY-MM.md    -- monthly summaries compressed from daily files (last 5 injected)
  On the 1st of each month, the previous month's daily files are compressed into a summary.

To add an agent to the pipeline:
  1. Create the agent in the Anthropic console (with its own system prompt / .md files)
  2. Add AGENT_ID_<NAME> to .env and GitHub Secrets
     Optionally: AGENT_VER_<NAME>, AGENT_VAULT_<NAME>
  3. Add the agent name to the correct layer in PIPELINE below
     Layer 1 agents: provide a prompt string (they fetch data from scratch)
     Layer 2+ agents: use None  (they receive compressed previous layer output + memory;
                                 their system prompts define what to do with the data)

SETUP:
  pip install -r requirements.txt

LOCAL ENV VARS (.env):
  ANTHROPIC_API_KEY, ENVIRONMENT_ID,
  AGENT_ID_<NAME>, AGENT_VER_<NAME> (optional), AGENT_VAULT_<NAME> (optional),
  EMAIL_ADDRESS, EMAIL_APP_PASSWORD, EMAIL_RECIPIENT

GITHUB SECRETS (mirrors .env):
  Same keys as above, set in repo Settings > Secrets > Actions
"""

import os
import sys
import smtplib
import anthropic
from pathlib import Path

# Ensure the Orchestration Layer directory is on the path so prompts/ is importable
sys.path.insert(0, str(Path(__file__).parent))

# Force UTF-8 output so special characters don't crash on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from prompts.market_data_retrieval import PROMPT as MARKET_PROMPT
from prompts.passthrough import PROMPT as PASSTHROUGH_PROMPT
from prompts.email_composer import PROMPT as EMAIL_COMPOSE_PROMPT

# Load .env for local runs (GitHub Actions uses repo secrets directly)
load_dotenv(Path(__file__).parent.parent / ".env")


# ============================================================
# MODEL DEFINITIONS
# Edit here to change models for any function. One place only.
# ============================================================

# Managed agents (set in each agent's YAML on Anthropic console, listed here for reference)
# market_data_retrieval : claude-sonnet-4-6
# sector specialists    : claude-sonnet-4-6
# synthesis agents      : claude-sonnet-4-6

# Direct Claude API calls made by this orchestrator:
MODEL_COMPRESS        = "claude-haiku-4-5-20251001"  # layer-boundary compression (cheap, fast)
MODEL_MEMORY_EXTRACT  = "claude-haiku-4-5-20251001"  # extract daily memory from outputs
MODEL_MEMORY_MONTHLY  = "claude-haiku-4-5-20251001"  # compress monthly memory summaries
MODEL_EMAIL           = "claude-opus-4-6"            # email composition (quality matters)

# Max tokens per direct API call
MAX_TOKENS_COMPRESS       = 4096
MAX_TOKENS_MEMORY_DAILY   = 400   # tight — daily entries must stay concise
MAX_TOKENS_MEMORY_MONTHLY = 600   # monthly summaries slightly longer
MAX_TOKENS_EMAIL          = 2048

# Memory configuration
MEMORY_DAILY_LOOKBACK   = 7   # days of daily files to inject per run
MEMORY_MONTHLY_LOOKBACK = 5   # months of summaries to inject per run


# ============================================================
# Pipeline configuration
# Edit this block to add/remove agents and layers.
# ============================================================

PIPELINE = [
    {
        "name": "Data Fetchers",
        "agents": {
            "market_data_retrieval": MARKET_PROMPT,
            # "news": NEWS_PROMPT,
        },
    },
    {
        "name": "Sector Specialists",
        "agents": {
            "insurance_specialist": None,
            # "banks_specialist": None,
            # "energy_specialist": None,
        },
    },
    # {
    #     "name": "Synthesis",
    #     "agents": {
    #         "macro_agent": None,
    #         "value_investing_agent": None,
    #         "portfolio_agent": None,
    #     },
    # },
]


# ============================================================
# Memory paths
# ============================================================

MEMORY_DIR   = Path(__file__).parent.parent / "memory"
DAILY_DIR    = MEMORY_DIR / "daily"
SUMMARY_DIR  = MEMORY_DIR / "summary"


# ============================================================
# Memory -- load
# Injects last N daily files + last M monthly summaries.
# Called once per run; output passed to all Layer 2+ agents.
# ============================================================

def load_memory() -> str:
    """
    Returns a formatted prior context string to inject into specialist prompts.
    Monthly summaries first (oldest context), then recent daily logs.
    Returns empty string if no memory files exist yet.
    """
    sections = []

    # Monthly summaries (last MEMORY_MONTHLY_LOOKBACK months)
    if SUMMARY_DIR.exists():
        monthly_files = sorted(SUMMARY_DIR.glob("*.md"), reverse=True)[:MEMORY_MONTHLY_LOOKBACK]
        if monthly_files:
            content = "\n\n---\n\n".join(
                f.read_text(encoding="utf-8") for f in reversed(monthly_files)
            )
            sections.append(f"### MONTHLY SUMMARIES\n{content}")

    # Daily logs (last MEMORY_DAILY_LOOKBACK days)
    if DAILY_DIR.exists():
        daily_files = sorted(DAILY_DIR.glob("*.md"), reverse=True)[:MEMORY_DAILY_LOOKBACK]
        if daily_files:
            content = "\n\n---\n\n".join(
                f.read_text(encoding="utf-8") for f in reversed(daily_files)
            )
            sections.append(f"### RECENT DAILY LOG\n{content}")

    if not sections:
        return ""

    return "## PRIOR CONTEXT\n\n" + "\n\n".join(sections)


# ============================================================
# Memory -- save daily
# Extracts high-signal events from today's outputs and writes
# a concise dated entry. Called after pipeline completes.
# ============================================================

def save_daily_memory(client: anthropic.Anthropic, layer_outputs: dict[str, str], date_str: str) -> None:
    """
    Uses MODEL_MEMORY_EXTRACT (Haiku) to extract only high-signal events
    from all layer outputs into a tight daily memory entry (~300 tokens max).
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
        max_tokens=MAX_TOKENS_MEMORY_DAILY,
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


# ============================================================
# Memory -- monthly compression
# Runs on the 1st of each month. Compresses previous month's
# daily files into a single summary, preserving only what is
# still relevant going forward.
# ============================================================

def compress_monthly_memory(client: anthropic.Anthropic, today: datetime) -> None:
    """
    On the 1st of the month, compresses the previous month's daily files
    into a monthly summary using MODEL_MEMORY_MONTHLY (Haiku).
    Skips if summary already exists or no daily files found.
    """
    if today.day != 1:
        return

    prev_month = (today.replace(day=1) - timedelta(days=1))
    month_str   = prev_month.strftime("%Y-%m")
    month_label = prev_month.strftime("%B %Y")
    summary_path = SUMMARY_DIR / f"{month_str}.md"

    if summary_path.exists() or not DAILY_DIR.exists():
        return

    daily_files = sorted(DAILY_DIR.glob(f"{month_str}-*.md"))
    if not daily_files:
        return

    combined = "\n\n---\n\n".join(f.read_text(encoding="utf-8") for f in daily_files)

    response = client.messages.create(
        model=MODEL_MEMORY_MONTHLY,
        max_tokens=MAX_TOKENS_MEMORY_MONTHLY,
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


# ============================================================
# Orchestrator
# ============================================================

class Orchestrator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.environment_id = os.environ["ENVIRONMENT_ID"]
        self.agents = self._load_agents()

    def _load_agents(self) -> dict:
        registry = {}
        for key, value in os.environ.items():
            if key.startswith("AGENT_ID_"):
                name = key[len("AGENT_ID_"):].lower()
                entry = {"id": value}
                version = os.environ.get(f"AGENT_VER_{name.upper()}")
                if version:
                    entry["version"] = version
                vault = os.environ.get(f"AGENT_VAULT_{name.upper()}")
                if vault:
                    entry["vault_id"] = vault
                registry[name] = entry
        return registry

    def run(self, agent_name: str, prompt: str, verbose: bool = True) -> str:
        agent_name = agent_name.lower()
        if agent_name not in self.agents:
            raise ValueError(
                f"Unknown agent '{agent_name}'. Available: {list(self.agents.keys())}"
            )

        agent_cfg = self.agents[agent_name]
        agent_ref = {"type": "agent", "id": agent_cfg["id"]}
        if "version" in agent_cfg:
            agent_ref["version"] = agent_cfg["version"]

        kwargs: dict = {
            "agent": agent_ref,
            "environment_id": self.environment_id,
            "title": f"Pipeline -- {agent_name}",
        }
        if "vault_id" in agent_cfg:
            kwargs["vault_ids"] = [agent_cfg["vault_id"]]

        session = self.client.beta.sessions.create(**kwargs)

        try:
            return self._stream_session(session.id, prompt, verbose)
        finally:
            try:
                self.client.beta.sessions.delete(session_id=session.id)
            except Exception:
                pass

    def _stream_session(self, session_id: str, prompt: str, verbose: bool) -> str:
        collected: list[str] = []

        self.client.beta.sessions.events.send(
            session_id=session_id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": prompt}]}],
        )

        while True:
            pending_tools: list[dict] = []

            with self.client.beta.sessions.events.stream(session_id=session_id) as stream:
                for event in stream:
                    if event.type == "agent.message":
                        for block in getattr(event, "content", []):
                            if getattr(block, "type", None) == "text":
                                collected.append(block.text)
                                if verbose:
                                    print(block.text, end="", flush=True)

                    elif event.type == "agent.custom_tool_use":
                        pending_tools.append({
                            "id": event.id,
                            "name": getattr(event, "tool_name", ""),
                            "input": getattr(event, "input", {}),
                        })

                    elif event.type == "session.status_terminated":
                        return "".join(collected)

                    elif event.type == "session.status_idle":
                        stop = getattr(event, "stop_reason", None)
                        stop_type = (
                            stop.get("type") if isinstance(stop, dict)
                            else getattr(stop, "type", None)
                        )
                        if stop_type != "requires_action":
                            return "".join(collected)
                        break

            if pending_tools:
                results = [
                    {
                        "type": "user.custom_tool_result",
                        "custom_tool_use_id": t["id"],
                        "content": [{"type": "text", "text": f"No handler for '{t['name']}'"}],
                        "is_error": True,
                    }
                    for t in pending_tools
                ]
                self.client.beta.sessions.events.send(session_id=session_id, events=results)
            else:
                break

        return "".join(collected)

    def run_layer(self, layer: dict, previous_context: str = "", memory: str = "") -> dict[str, str]:
        """Run all agents in a layer in parallel. Returns {agent_name: output}."""
        agents_prompts: dict[str, str] = {}
        for agent_name, prompt in layer["agents"].items():
            if prompt is not None:
                # Layer 1: use the agent's own prompt, no memory injection
                agents_prompts[agent_name] = prompt
            else:
                # Layer 2+: inject memory + today's data via passthrough prompt
                agents_prompts[agent_name] = PASSTHROUGH_PROMPT.format(
                    prior_context=memory,
                    previous_outputs=previous_context,
                )

        results: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(agents_prompts)) as executor:
            futures = {
                executor.submit(self.run, name, p): name
                for name, p in agents_prompts.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as e:
                    print(f"\n[ERROR] {name} failed: {e}")
                    results[name] = f"[Agent failed: {e}]"

        return results


# ============================================================
# Layer boundary compression  (MODEL_COMPRESS)
# ============================================================

def compress_layer_output(client: anthropic.Anthropic, outputs: dict[str, str]) -> str:
    """
    Compresses all agent outputs from a layer into a concise structured summary.
    Uses MODEL_COMPRESS (Haiku). Removes redundancy only — preserves all data points.
    """
    sections = []
    for agent_name, output in outputs.items():
        label = agent_name.upper().replace("_", " ")
        sections.append(f"=== {label} ===\n{output}\n=== END {label} ===")
    combined = "\n\n".join(sections)

    response = client.messages.create(
        model=MODEL_COMPRESS,
        max_tokens=MAX_TOKENS_COMPRESS,
        messages=[{
            "role": "user",
            "content": (
                "Compress the following agent outputs by removing redundancy, filler text, "
                "and repetition only. Preserve every data point, number, ticker, percentage "
                "move, yield, price level, and piece of analysis in full — do not summarise "
                "or drop any factual content. Use bullet points. Label each agent's section "
                "clearly.\n\n"
                + combined
            ),
        }],
    )
    return response.content[0].text


# ============================================================
# Email composer  (MODEL_EMAIL)
# ============================================================

def compose_email(client: anthropic.Anthropic, final_output: str) -> tuple[str, str]:
    """
    Composes the final HTML email from the last layer's compressed output.
    Uses MODEL_EMAIL (Opus). Returns (subject, html_body).
    """
    prompt = EMAIL_COMPOSE_PROMPT.format(final_output=final_output)
    response = client.messages.create(
        model=MODEL_EMAIL,
        max_tokens=MAX_TOKENS_EMAIL,
        messages=[{"role": "user", "content": prompt}],
    )
    full_text = next(b.text for b in response.content if b.type == "text")

    lines = full_text.strip().split("\n")
    subject = "Morning Briefing"
    body_start = 0
    if lines[0].startswith("SUBJECT:"):
        subject = lines[0].replace("SUBJECT:", "").strip()
        body_start = 1

    html_body = "\n".join(lines[body_start:]).strip()
    return subject, html_body


# ============================================================
# Email sender -- Gmail SMTP
# ============================================================

def send_email(subject: str, html_body: str) -> None:
    sender   = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_APP_PASSWORD"]
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


# ============================================================
# Daily pipeline
# ============================================================

def run_pipeline():
    sgt   = timezone(timedelta(hours=8))
    today = datetime.now(sgt)
    today_str = today.strftime("%Y-%m-%d")
    print(f"=== Morning Briefing Pipeline -- {today.strftime('%A, %d %B %Y')} ===\n")

    orchestrator = Orchestrator()
    client = orchestrator.client

    # Monthly memory compression (runs only on 1st of month)
    compress_monthly_memory(client, today)

    # Load prior context to inject into Layer 2+ agents
    print("-- Loading memory --")
    memory = load_memory()
    if memory:
        print(f"[Memory] Loaded prior context ({len(memory.split())} words)")
    else:
        print("[Memory] No prior context found — first run")

    # Run pipeline layers
    previous_context = ""
    all_outputs: dict[str, str] = {}

    for i, layer in enumerate(PIPELINE, 1):
        print(f"\n-- Layer {i}: {layer['name']} --")
        outputs = orchestrator.run_layer(layer, previous_context, memory)
        all_outputs.update(outputs)

        print(f"\n-- Compressing Layer {i} output --")
        previous_context = compress_layer_output(client, outputs)
        print(f"[Layer {i} complete]")

    # Compose and send email
    print("\n-- Composing email --")
    subject, html_body = compose_email(client, previous_context)
    print(f"Subject: {subject}")

    print("-- Sending email --")
    send_email(subject, html_body)

    # Save today's memory after successful send
    print("\n-- Saving memory --")
    save_daily_memory(client, all_outputs, today_str)

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    run_pipeline()
