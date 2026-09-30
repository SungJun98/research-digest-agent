# Contributing

Use Python 3.11 or 3.12 and install `pip install -e '.[dev]'`. Run `pytest -q` and verify `research-digest preview --config config.example.yaml --offline-fixtures` before opening a pull request.

Keep adapters injectable and bounded. Use recorded or synthetic fixtures by default; never add credentials, mailbox contents, user profiles or state databases. Live checks must be opt-in and read-only.

A new source must preserve real IDs, timestamps and measured signals, explicitly handle missing values, sanitize errors and respect its published request limits. A new recommendation rule should have a behavioral regression test. Do not turn prestige, missing data or unobserved user activity into a quality signal.

For bugs, include a sanitized configuration excerpt, command, Python version and expected/actual behavior. Never include API keys, webhook URLs, SMTP passwords or raw private mail. Describe changes and validation clearly in the PR.
