"""
Morning Briefing Pipeline — Entry Point
-----------------------------------------
Runs daily via GitHub Actions at 8am SGT (00:00 UTC).

Flow:
  Layer 1 -- Data Fetchers     : universal market data (macro, rates, FX, indices, commodities)
  Layer 2 -- Sector Specialists: each receives Layer 1 output + fetches own niche data
  Layer 3 -- Synthesis         : (future) macro, value investing, portfolio agents
  Final   -- Email             : composed from final layer output and sent via Gmail SMTP
             Publisher         : (future) web/dashboard publishing

To add an agent:
  1. Create the agent in the Anthropic console (with its own system prompt / .md files)
  2. Add AGENT_ID_<NAME> to .env and GitHub Secrets
     Optionally: AGENT_VER_<NAME>, AGENT_VAULT_<NAME>
  3. Add the agent name to the correct layer in PIPELINE below

SETUP:
  pip install -r requirements.txt

LOCAL ENV VARS (.env):
  ANTHROPIC_API_KEY, ENVIRONMENT_ID,
  AGENT_ID_<NAME>, AGENT_VER_<NAME> (optional), AGENT_VAULT_<NAME> (optional),
  EMAIL_ADDRESS, EMAIL_APP_PASSWORD, EMAIL_RECIPIENT

GITHUB SECRETS (mirrors .env):
  Same keys as above, set in repo Settings > Secrets > Actions
"""

import sys
import os
from pathlib import Path

# Ensure this directory is on the path for local imports
sys.path.insert(0, str(Path(__file__).parent))

# Force UTF-8 output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

from orchestrator import Orchestrator, compress
from email import compose_email, send_email
from memory import load_memory, save_daily_memory, compress_monthly_memory
from publisher import publish
from prompts.market_data_retrieval import PROMPT as MARKET_PROMPT

# Load .env for local runs (GitHub Actions injects secrets directly)
load_dotenv(Path(__file__).parent.parent / ".env")


# ============================================================
# Pipeline configuration
# Edit this block to add/remove agents and layers.
#
# Layer 1 agents: provide a prompt string (fetch data from scratch)
# Layer 2+ agents: use None (receive compressed previous layer output + memory)
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
# Pipeline runner
# ============================================================

def run_pipeline():
    sgt       = timezone(timedelta(hours=8))
    today     = datetime.now(sgt)
    today_str = today.strftime("%Y-%m-%d")
    print(f"=== Morning Briefing Pipeline -- {today.strftime('%A, %d %B %Y')} ===\n")

    orchestrator = Orchestrator()
    client = orchestrator.client

    # Monthly memory compression (runs only on 1st of month)
    compress_monthly_memory(client, today)

    # Load prior context to inject into Layer 2+ agents
    print("-- Loading memory --")
    memory = load_memory()
    print(f"[Memory] {'Loaded prior context' if memory else 'No prior context — first run'}")

    # Run pipeline layers sequentially; agents within each layer run in parallel
    previous_context = ""
    all_outputs: dict[str, str] = {}

    for i, layer in enumerate(PIPELINE, 1):
        print(f"\n-- Layer {i}: {layer['name']} --")
        outputs = orchestrator.run_layer(layer, previous_context, memory)
        all_outputs.update(outputs)

        print(f"\n-- Compressing Layer {i} output --")
        previous_context = compress(client, outputs)
        print(f"[Layer {i} complete]")

    # Compose and send email
    print("\n-- Composing email --")
    subject, html_body = compose_email(client, previous_context)
    print(f"Subject: {subject}")

    print("-- Sending email --")
    send_email(subject, html_body)

    # Publish to web (future)
    publish(previous_context, today_str)

    # Save today's memory after successful send
    print("\n-- Saving memory --")
    save_daily_memory(client, all_outputs, today_str)

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    run_pipeline()
