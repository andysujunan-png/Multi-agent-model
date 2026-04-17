"""
Orchestration Layer — routes tasks to pre-created Managed Agents via the Claude API.

SETUP:
  pip install anthropic

REQUIRED ENV VARS:
  ANTHROPIC_API_KEY   — your Anthropic API key
  ENVIRONMENT_ID      — the managed-agents environment ID (env_...)

AGENT ENV VARS (add one per agent you created):
  AGENT_ID_<NAME>     — e.g. AGENT_ID_RESEARCHER, AGENT_ID_CODER, AGENT_ID_ANALYST
  AGENT_VER_<NAME>    — optional pinned version; omit to use latest

USAGE:
  orchestrator = Orchestrator()
  response = orchestrator.run("researcher", "Summarize the latest AI papers.")
  print(response)
"""

import os
import json
import anthropic


# ---------------------------------------------------------------------------
# Config — agent registry built from environment variables
# ---------------------------------------------------------------------------

def _load_agent_registry() -> dict[str, dict]:
    """
    Scans env vars for AGENT_ID_<NAME> entries and builds a registry like:
      { "researcher": {"id": "agent_abc123", "version": "..."}, ... }
    """
    registry: dict[str, dict] = {}
    for key, value in os.environ.items():
        if key.startswith("AGENT_ID_"):
            name = key[len("AGENT_ID_"):].lower()
            entry: dict = {"id": value}
            version = os.environ.get(f"AGENT_VER_{name.upper()}")
            if version:
                entry["version"] = version
            registry[name] = entry
    return registry


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Routes tasks to pre-created Managed Agents and streams their responses.

    Each call to `run()` creates a fresh session, sends one user message,
    streams all events until the agent goes idle, handles any custom tool
    calls your application owns, then cleans up the session.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )
        self.environment_id: str = os.environ["ENVIRONMENT_ID"]
        self.agents: dict[str, dict] = _load_agent_registry()

        if not self.agents:
            raise RuntimeError(
                "No agents found. Set AGENT_ID_<NAME> environment variables "
                "for each agent you created in the Managed Agents interface."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_agents(self) -> list[str]:
        """Return the names of all registered agents."""
        return list(self.agents.keys())

    def run(
        self,
        agent_name: str,
        user_message: str,
        custom_tool_handler: "dict[str, callable] | None" = None,
        resources: "list[dict] | None" = None,
        vault_ids: "list[str] | None" = None,
        verbose: bool = True,
    ) -> str:
        """
        Send `user_message` to the named agent and return the full text response.

        Args:
            agent_name:          Key matching an AGENT_ID_<NAME> env var (case-insensitive).
            user_message:        The message to send.
            custom_tool_handler: Optional dict mapping tool name → callable(input) → str.
                                 Called when the agent invokes a custom tool you defined.
            resources:           Optional list of session resources (files, GitHub repos).
            vault_ids:           Optional list of vault IDs for MCP credentials.
            verbose:             Print streaming events to stdout while running.

        Returns:
            Concatenated text from all agent.message events.
        """
        agent_name = agent_name.lower()
        if agent_name not in self.agents:
            available = ", ".join(self.agents)
            raise ValueError(
                f"Unknown agent '{agent_name}'. Available agents: {available}"
            )

        session = self._create_session(agent_name, resources, vault_ids)
        session_id = session.id

        try:
            return self._run_session(
                session_id=session_id,
                user_message=user_message,
                custom_tool_handler=custom_tool_handler or {},
                verbose=verbose,
            )
        finally:
            self._cleanup_session(session_id)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _create_session(
        self,
        agent_name: str,
        resources: "list[dict] | None",
        vault_ids: "list[str] | None",
    ):
        agent_cfg = self.agents[agent_name]
        agent_ref = {"type": "agent", "id": agent_cfg["id"]}
        if "version" in agent_cfg:
            agent_ref["version"] = agent_cfg["version"]

        kwargs: dict = {
            "agent": agent_ref,
            "environment_id": self.environment_id,
            "title": f"Orchestration — {agent_name}",
        }
        if resources:
            kwargs["resources"] = resources
        if vault_ids:
            kwargs["vault_ids"] = vault_ids

        return self.client.beta.sessions.create(**kwargs)

    def _cleanup_session(self, session_id: str) -> None:
        try:
            self.client.beta.sessions.delete(session_id=session_id)
        except Exception:
            pass  # best-effort cleanup

    # ------------------------------------------------------------------
    # Event streaming loop
    # ------------------------------------------------------------------

    def _run_session(
        self,
        session_id: str,
        user_message: str,
        custom_tool_handler: "dict[str, callable]",
        verbose: bool,
    ) -> str:
        """
        Opens the SSE stream before sending the message (stream-first pattern),
        collects all agent output, and handles custom tool calls in a loop
        until the session reaches a terminal idle state.
        """
        collected_text: list[str] = []

        # Send the initial user message
        self.client.beta.sessions.events.send(
            session_id=session_id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": user_message}],
                }
            ],
        )

        # Stream until the agent is done or the session terminates
        while True:
            pending_tool_calls: list[dict] = []

            with self.client.beta.sessions.stream(session_id=session_id) as stream:
                for event in stream:
                    self._handle_event(
                        event=event,
                        collected_text=collected_text,
                        pending_tool_calls=pending_tool_calls,
                        verbose=verbose,
                    )

                    # Terminal states — stop streaming
                    if event.type == "session.status_terminated":
                        return "".join(collected_text)

                    if event.type == "session.status_idle":
                        stop_reason = getattr(event, "stop_reason", None)
                        stop_type = (
                            stop_reason.get("type")
                            if isinstance(stop_reason, dict)
                            else getattr(stop_reason, "type", None)
                        )
                        if stop_type != "requires_action":
                            # Normal completion or retries exhausted — done
                            return "".join(collected_text)
                        # requires_action means we owe tool results — fall through
                        break

            # Resolve pending custom tool calls and send results back
            if pending_tool_calls:
                results = self._resolve_tool_calls(pending_tool_calls, custom_tool_handler)
                self.client.beta.sessions.events.send(
                    session_id=session_id,
                    events=results,
                )
            else:
                # requires_action but no tool calls — safety exit
                break

        return "".join(collected_text)

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def _handle_event(
        self,
        event,
        collected_text: list[str],
        pending_tool_calls: list[dict],
        verbose: bool,
    ) -> None:
        etype = event.type

        if etype == "agent.message":
            for block in getattr(event, "content", []):
                btype = getattr(block, "type", None)
                if btype == "text":
                    text = block.text
                    collected_text.append(text)
                    if verbose:
                        print(text, end="", flush=True)

        elif etype == "agent.thinking":
            if verbose:
                for block in getattr(event, "content", []):
                    if getattr(block, "type", None) == "thinking":
                        print(f"\n[thinking] {block.thinking[:120]}…", flush=True)

        elif etype == "agent.custom_tool_use":
            tool_name = getattr(event, "tool_name", "") or getattr(event, "name", "")
            tool_input = getattr(event, "input", {})
            event_id = event.id
            if verbose:
                print(f"\n[custom tool] {tool_name}({json.dumps(tool_input)[:80]})", flush=True)
            pending_tool_calls.append({
                "id": event_id,
                "name": tool_name,
                "input": tool_input,
            })

        elif etype == "session.error":
            error = getattr(event, "error", event)
            if verbose:
                print(f"\n[session error] {error}", flush=True)

        elif etype in ("session.status_idle", "session.status_running",
                       "session.status_terminated"):
            if verbose:
                print(f"\n[{etype}]", flush=True)

    # ------------------------------------------------------------------
    # Custom tool resolution
    # ------------------------------------------------------------------

    def _resolve_tool_calls(
        self,
        pending: list[dict],
        handler: "dict[str, callable]",
    ) -> list[dict]:
        results = []
        for call in pending:
            tool_name: str = call["name"]
            tool_input: dict = call["input"]

            fn = handler.get(tool_name)
            if fn:
                try:
                    result_text = fn(tool_input)
                    is_error = False
                except Exception as exc:
                    result_text = f"Error running {tool_name}: {exc}"
                    is_error = True
            else:
                result_text = f"No handler registered for tool '{tool_name}'."
                is_error = True

            results.append({
                "type": "user.custom_tool_result",
                "custom_tool_use_id": call["id"],
                "content": [{"type": "text", "text": result_text}],
                "is_error": is_error,
            })
        return results


# ---------------------------------------------------------------------------
# CLI entry point — quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    orchestrator = Orchestrator()
    print("Registered agents:", orchestrator.list_agents())

    if len(sys.argv) < 3:
        print("\nUsage: python Orchestration.py <agent_name> <message>")
        print('Example: python Orchestration.py researcher "Summarize AI news."')
        sys.exit(0)

    agent = sys.argv[1]
    message = " ".join(sys.argv[2:])

    print(f"\n--- Sending to agent '{agent}' ---\n")
    response = orchestrator.run(agent, message)
    print(f"\n\n--- Final response ---\n{response}")
