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

To add an agent to the pipeline:
  1. Create the agent in the Anthropic console (with its own system prompt / .md files)
  2. Add AGENT_ID_<NAME> to .env and GitHub Secrets
     Optionally: AGENT_VER_<NAME>, AGENT_VAULT_<NAME>
  3. Add the agent name to the correct layer in PIPELINE below
     Layer 1 agents: provide a prompt string (they fetch data from scratch)
     Layer 2+ agents: use None  (they receive compressed previous layer output;
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
MODEL_COMPRESS   = "claude-haiku-4-5-20251001"   # layer-boundary compression (cheap, fast)
MODEL_EMAIL      = "claude-opus-4-6"              # email composition (quality matters)

# Max tokens per direct API call
MAX_TOKENS_COMPRESS = 4096
MAX_TOKENS_EMAIL    = 2048


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

    def run_layer(self, layer: dict, previous_context: str = "") -> dict[str, str]:
        """Run all agents in a layer in parallel. Returns {agent_name: output}."""
        agents_prompts: dict[str, str] = {}
        for agent_name, prompt in layer["agents"].items():
            if prompt is not None:
                agents_prompts[agent_name] = prompt
            else:
                agents_prompts[agent_name] = PASSTHROUGH_PROMPT.format(
                    previous_outputs=previous_context
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
# Summarises all agent outputs from a layer into a compact
# context block before passing to the next layer.
# ============================================================

def compress_layer_output(client: anthropic.Anthropic, outputs: dict[str, str]) -> str:
    """
    Compresses all agent outputs from a layer into a concise structured summary.
    Uses MODEL_COMPRESS (Haiku) — cheap and fast.
    Preserves all key numbers, tickers, and data points.
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
    Uses MODEL_EMAIL (Opus) — quality matters for client-facing output.
    Returns (subject, html_body).
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
    sender = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_RECIPIENT"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
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
    sgt = timezone(timedelta(hours=8))
    today = datetime.now(sgt).strftime("%A, %d %B %Y")
    print(f"=== Morning Briefing Pipeline -- {today} ===\n")

    orchestrator = Orchestrator()
    previous_context = ""

    for i, layer in enumerate(PIPELINE, 1):
        print(f"-- Layer {i}: {layer['name']} --")
        outputs = orchestrator.run_layer(layer, previous_context)

        print(f"\n-- Compressing Layer {i} output --")
        previous_context = compress_layer_output(orchestrator.client, outputs)
        print(f"\n{'='*60}")
        print(f"COMPRESSED OUTPUT PASSED TO LAYER {i+1}:")
        print(f"{'='*60}")
        print(previous_context)
        print(f"{'='*60}\n")
        print(f"[Layer {i} complete]\n")

    print("-- Composing email --")
    subject, html_body = compose_email(orchestrator.client, previous_context)
    print(f"Subject: {subject}")

    print("-- Sending email --")
    send_email(subject, html_body)

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    run_pipeline()
