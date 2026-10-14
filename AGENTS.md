# Contributor instructions

Use the tools in `~/.config/tool-registry/registry.json`. Never send without the user's OK.

Keep changes generic to Google Sheets. Do not alter the interview-sheet project, existing spreadsheets, OAuth project settings, billing, or unrelated tool registrations without authorization. Never commit client secrets, service-account keys, tokens, or user spreadsheet contents.

Use `uv sync --locked`, `uv run pytest`, and `uv build`. Keep the 100% line and branch coverage gate; test meaningful failure and authorization paths rather than excluding them. Real protocol tests must initialize a stdio session, list tools, and exercise credential-free previews.

Mutations must preview with no credentials or network unless `confirm=True`. Treat the switch as execution intent; an agent still needs user authorization for the exact operation. Never blindly retry an uncertain write. RAW remains the values-input default; formula parsing must be explicit. Keep CLI and MCP on the same client methods, bound network timeouts, redact remote error bodies, and use official Google and MCP SDKs.
