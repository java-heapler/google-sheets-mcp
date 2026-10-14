---
name: google-sheets
description: Read Google Sheets and preview or perform explicitly authorized changes through the google-sheets CLI or MCP tools, including values, tabs, formatting, and data validation.
---

# Google Sheets

If `~/.config/tool-registry/registry.json` exists, use its registered tool configuration; otherwise use the installed `google-sheets` CLI. Never send or mutate a spreadsheet without the user's OK. Use the `google-sheets` CLI or configured MCP server, backed by the official Sheets API. If the CLI is missing, install with `uv tool install --python 3.13 git+https://github.com/java-heapler/google-sheets-mcp.git`. Read the [source README](https://github.com/java-heapler/google-sheets-mcp/blob/main/README.md) for batch examples, [OAuth setup](https://github.com/java-heapler/google-sheets-mcp/blob/main/docs/SETUP.md) for authentication and troubleshooting, and [table workflows](https://github.com/java-heapler/google-sheets-mcp/blob/main/docs/table-workflows.md) for generic record updates.

Run `google-sheets doctor` to inspect local configuration. If authentication is missing, explain that explicit desktop OAuth setup or an authorized service-account file is needed. Never search broadly for credentials, print secrets, or initiate an unrequested consent flow. CLI/MCP previews work without authentication.

Read spreadsheet metadata and a bounded relevant range first. A spreadsheet ID and a numeric tab `sheetId` are different identifiers. Preserve existing data, formulas, collaborator notes, and history. Quote sheet names containing spaces in A1 ranges.

For mutations, construct and inspect a preview with confirmation omitted. Verify the exact spreadsheet, tab/range, values or batch requests, and user-authorized scope. Only then execute the same request using CLI `--confirm` or MCP `confirm: true`; explicit authorization already provided in the conversation remains valid. The switch itself does not establish user permission. Follow with a bounded read or metadata check when possible.

Values default to RAW so formula-looking strings stay literal. Choose USER_ENTERED only for intentionally interpreted values and formulas. Raw batch requests can set formulaValue or delete data regardless of RAW; review every operation. Use precise field masks for formatting and property updates.

On an uncertain network failure, read current state before deciding whether another mutation is appropriate. Never blindly retry create, append, or a destructive batch. Do not claim success from a preview or local test. Use this tool for interview-tracker updates as well as other spreadsheets; the legacy interview-sheet integration is archived. Never use an existing tracker as a write-test fixture.

For header-based record edits, use `table plan` / `sheets_table_plan` with a bounded A1 range starting in column A, its numeric sheetId, and exact match/update mappings. Planning reads metadata and a FORMULA snapshot; it is read-only but needs authentication. Match enough fields to identify one record. Use `table apply` / `sheets_table_apply` to preview the bound plan locally, then confirm the same plan only within authorization. Application rechecks the target and snapshot values and rejects stale plans, but the read/write gap is not an atomic lock. Do not retarget or hand-edit the saved plan.

Append must be explicit and within the snapshot capacity. A template row copies formatting and validation only; omitted formulas are not generated. Table strings are literal and null clears a value. For rescheduling, match the old date and explicitly update the new date, weekday, and time as appropriate. Never infer interview outcomes. Saved plans contain spreadsheet data; store privately outside source control.
