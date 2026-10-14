---
name: google-sheets
description: Read Google Sheets and preview or perform explicitly authorized changes through the google-sheets CLI or MCP tools, including values, tabs, formatting, and data validation.
---

# Google Sheets

Use the tools in `~/.config/tool-registry/registry.json`. Never send or mutate a spreadsheet without the user's OK. Use the registered `google-sheets` CLI or MCP server, backed by the official Sheets API. Read the repository README for setup and batch examples.

Run `google-sheets doctor` to inspect local configuration. If authentication is missing, explain that explicit desktop OAuth setup or an authorized service-account file is needed. Never search broadly for credentials, print secrets, or initiate an unrequested consent flow. CLI/MCP previews work without authentication.

Read spreadsheet metadata and a bounded relevant range first. A spreadsheet ID and a numeric tab `sheetId` are different identifiers. Preserve existing data, formulas, collaborator notes, and history. Quote sheet names containing spaces in A1 ranges.

For mutations, construct and inspect a preview with confirmation omitted. Verify the exact spreadsheet, tab/range, values or batch requests, and user-authorized scope. Only then execute the same request using CLI `--confirm` or MCP `confirm: true`; explicit authorization already provided in the conversation remains valid. The switch itself does not establish user permission. Follow with a bounded read or metadata check when possible.

Values default to RAW so formula-looking strings stay literal. Choose USER_ENTERED only for intentionally interpreted values and formulas. Raw batch requests can set formulaValue or delete data regardless of RAW; review every operation. Use precise field masks for formatting and property updates.

On an uncertain network failure, read current state before deciding whether another mutation is appropriate. Never blindly retry create, append, or a destructive batch. Do not claim success from a preview or local test. Keep the separate interview-sheet workflow intact and never use an existing tracker as a write-test fixture.
