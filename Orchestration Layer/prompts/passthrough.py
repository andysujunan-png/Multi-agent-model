PROMPT = """
The following data has been provided by the upstream agents. Use it as your input foundation.
Do not re-fetch any data already present below. Supplement only with data specific to your
sector as defined in your knowledge base.

{previous_outputs}

Produce your full analysis output now.
""".strip()
