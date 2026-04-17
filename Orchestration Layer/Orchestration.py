"""
Orchestrator
------------
Manages Managed Agent sessions and runs pipeline layers.

Orchestrator   -- creates/deletes sessions, streams events, handles tool results
run_layer()    -- runs all agents in a layer in parallel
compress()     -- compresses layer outputs between layers (Haiku)
"""

import os
import anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed

from prompts.passthrough import PROMPT as PASSTHROUGH_PROMPT

# Model used for layer-boundary compression
MODEL_COMPRESS    = "claude-haiku-4-5-20251001"
MAX_TOKENS_COMPRESS = 6144


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


def compress(client: anthropic.Anthropic, outputs: dict[str, str]) -> str:
    """
    Compresses all agent outputs from a layer into a concise structured summary.
    Removes redundancy only — preserves all data points, numbers, and tickers.
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
