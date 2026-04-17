"""
Web Publisher (stub)
---------------------
Future: publish morning briefing output to a website or dashboard.

publish() will be called from main.py after the email is sent.
"""


def publish(content: str, date_str: str) -> None:
    """
    Publish the final briefing to the web.
    Not yet implemented.
    """
    # TODO: implement web publishing
    # Options:
    #   - Static site generator (push markdown to GitHub Pages)
    #   - REST API call to a CMS or dashboard
    #   - Upload HTML to S3 / Azure Blob with a public URL
    print("[Publisher] Web publishing not yet implemented — skipping.")
