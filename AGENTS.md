# Jev Second Brain

Local-first, source-preserving Markdown memory tooling. The Markdown files are
authoritative; SQLite data and model judgments are derived. Do not silently
rewrite, merge, archive, delete, or promote a suggested relationship to fact.

Use synthetic fixtures in tests and examples. Never commit a real vault, prompt,
provider response containing private text, API key, or local index database.
Provider calls require an explicit key, policy gate, and bounded request budget.
Keep local search usable when Jev is unavailable.

Run `python3 -m unittest discover -s tests -v` for focused verification. Before
committing, stage only task-owned paths and inspect the staged diff. Public
releases and package-registry publication remain separate owner decisions.
