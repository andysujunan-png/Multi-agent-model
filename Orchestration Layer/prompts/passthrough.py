PROMPT = """
{prior_context}

---

The following data has been provided by the upstream agents today. Use it as your input \
foundation. Do not re-fetch any data already present below. Supplement only with data \
specific to your sector as defined in your knowledge base.

Where prior context is provided above, reference relevant developments explicitly \
(e.g. earnings from last week, prior flag changes, trend continuations or reversals). \
Be specific — cite dates and prior levels where relevant.

{previous_outputs}

Produce your full analysis output now.
""".strip()
