"""
Interactive shell for the Morning Briefing Orchestrator.
Run this from the terminal to manually call agents and inspect outputs.

Usage:
  cd "C:/Users/Admin/OneDrive/Desktop/Code/Multi Agent Model"
  python "Orchestration Layer/shell.py"
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from Orchestration import Orchestrator, run_pipeline, format_outputs, compose_email

# Instantiate — credentials loaded automatically from .env
o = Orchestrator()

print("Orchestrator ready.")
print(f"Loaded agents: {list(o.agents.keys())}")
print()
print("Available commands:")
print("  o.run('agent_name', 'your prompt')   -- call a single agent")
print("  run_pipeline()                         -- run the full pipeline")
print("  o.agents                               -- show all loaded agents")
print()
print("Example:")
print("  out = o.run('market_data_retrieval', 'Give me S&P 500 closing price')")
print()

# Drop into interactive Python shell with o already in scope
import code
code.interact(local={**globals(), **locals()}, banner="")
