"""
Interactive shell for manual testing.
Run from the repo root:

  python "Orchestration Layer/shell.py"

Then use the orchestrator and pipeline functions directly:

  o.run('market_data_retrieval', 'Run your morning data pull')
  o.run('insurance_specialist', 'Your prompt here')
  run_pipeline()
  load_memory()
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from orchestrator import Orchestrator, compress
from email import compose_email, send_email
from memory import load_memory, save_daily_memory
from main import run_pipeline, PIPELINE

o = Orchestrator()

print("Orchestrator ready.")
print(f"Agents loaded: {list(o.agents.keys())}")
print()
print("Available:")
print("  o.run('agent_name', 'prompt')   -- call a single agent")
print("  o.agents                         -- show loaded agents")
print("  PIPELINE                         -- show pipeline config")
print("  load_memory()                    -- show current memory context")
print("  run_pipeline()                   -- run the full pipeline")
print()

import code
code.interact(local={**globals(), **locals()}, banner="")
