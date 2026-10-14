# Google Sheets CLI + MCP

A Python CLI and stdio MCP server using Google's official Sheets API and the official MCP SDK. Read spreadsheets and preview changes locally; mutations require explicit confirmation.

Implementation and automated tests do not establish that a Google account is authenticated or that a live spreadsheet operation has succeeded. See authentication and live verification below.

Repository: [java-heapler/google-sheets-mcp](https://github.com/java-heapler/google-sheets-mcp). The executable is `google-sheets` and the agent skill is `google-sheets`.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run google-sheets --help
uv tool install .
google-sheets doctor
```

`doctor` reports local credential configuration; it is not a live access check. For installation history, Cloud permissions, OAuth setup, troubleshooting, and release steps, see [the setup runbook](docs/SETUP.md). Authentication and live reads were verified in the original installation; each new installation must establish its own access.

## Authenticate once

1. In a Google Cloud project, enable the Google Sheets API, configure the OAuth consent screen and add your account as a test user if the app is in external testing mode.
2. Create an OAuth client of type **Desktop app**. Save its downloaded JSON outside this repository, for example `~/.config/google-sheets-mcp/client_secret.json`, with permissions `600`.
3. Run the explicit login command and complete Google's consent flow:

```sh
google-sheets auth login --client-secrets "$HOME/.config/google-sheets-mcp/client_secret.json"
```

The token is stored at `~/.config/google-sheets-mcp/token.json` with permissions `600`. Use `--token-file` during login or `GOOGLE_SHEETS_TOKEN_FILE` to choose another location. Ordinary commands and MCP tools never initiate interactive login. The requested scope is `https://www.googleapis.com/auth/spreadsheets`; access still depends on your account's permissions. See Google's [Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python) for project and OAuth setup.

For service accounts, set `GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE` to a private JSON key outside the repository and share the target spreadsheet with that account's email using the needed permission. Treat that key as a secret. Do not use this tool to manage Drive sharing; it does not expose Drive permissions APIs.

## Read and change values

Use the spreadsheet ID from its URL, not the full URL. Quote A1 ranges containing spaces. Reading an explicit small range is preferable to dumping a workbook.

```sh
google-sheets info SPREADSHEET_ID
# Inspect formatting, validation, and other cell metadata in a bounded range:
google-sheets info SPREADSHEET_ID --range "'Sheet 1'!A1:C10" --include-grid-data
google-sheets read SPREADSHEET_ID "'Sheet 1'!A1:C10"
google-sheets read SPREADSHEET_ID "'Sheet 1'!A1:C10" --render FORMULA
printf '%s\n' '[["Name","Total"],["Example",42]]' > /tmp/values.json
google-sheets write SPREADSHEET_ID "'Sheet 1'!A1:B2" --values-file /tmp/values.json
# After reviewing the preview and obtaining authorization:
google-sheets write SPREADSHEET_ID "'Sheet 1'!A1:B2" --values-file /tmp/values.json --confirm
```

Every mutation defaults to a local `status: preview` response without credential loading or network calls. `--confirm` (MCP `confirm: true`) executes the supplied request and returns `status: applied` on success. Confirmation is a caller-controlled switch, not an authorization system or a saved transaction: preserve the exact reviewed arguments. A preview does not validate Google permissions, current data, or the complete Google request schema.

`write` replaces cells in a range, `append` inserts rows after the detected table (`INSERT_ROWS`), `clear` removes cell values, and `create TITLE` creates a spreadsheet. Each takes `--confirm` to execute. `info --range` may be repeated; add `--include-grid-data` to inspect cell metadata such as formatting and validation, keeping ranges bounded. `read --render` accepts `FORMATTED_VALUE` (default), `UNFORMATTED_VALUE`, or `FORMULA`.

`write` and `append` default to `--input-option RAW`: strings such as `=SUM(A1:A3)` remain literal text. Explicit `--input-option USER_ENTERED` allows Google to interpret formulas, dates, and numbers as if typed into Sheets; interpretation can depend on spreadsheet locale. Only choose it intentionally for reviewed data. `--render FORMULA` reads formula text; it does not change input behavior. See [ValueInputOption](https://developers.google.com/workspace/sheets/api/reference/rest/v4/ValueInputOption).

## Update records by their headers

Use `table plan` to read a bounded table and prepare a header-based match/update, then `table apply --plan-file PLAN.json` to preview locally and add `--confirm` to execute. Matching is unique and type-aware; ambiguous records and stale snapshots are rejected. Optional append can copy a template row’s formatting and validation. This works with arbitrary headers rather than a fixed interview schema. See [general table workflows](docs/table-workflows.md) for rescheduling, inventory, append, and preservation examples, plus the non-atomic concurrency limits.

## Tabs, formatting, and validation

```sh
google-sheets tabs add SPREADSHEET_ID "New tab"
google-sheets tabs rename SPREADSHEET_ID 123 "Renamed tab"
google-sheets tabs delete SPREADSHEET_ID 123
```

The numeric `sheetId` identifies a tab and is distinct from the spreadsheet ID. Get it from `info`. Deleting a tab is destructive. The commands above preview; append `--confirm` only within authorization.

`batch` accepts a JSON array of native [Sheets batch requests](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request). This supports formatting, validation, dimensions, named ranges, charts, filters, and other Sheets operations without additional wrapper commands. Use narrow field masks. For example, save this as `/tmp/requests.json`, replacing `123` with the target tab's ID:

```json
[
  {
    "repeatCell": {
      "range": {"sheetId": 123, "startRowIndex": 0, "endRowIndex": 1},
      "cell": {"userEnteredFormat": {"textFormat": {"bold": true}}},
      "fields": "userEnteredFormat.textFormat.bold"
    }
  },
  {
    "setDataValidation": {
      "range": {"sheetId": 123, "startRowIndex": 1, "endRowIndex": 100, "startColumnIndex": 2, "endColumnIndex": 3},
      "rule": {
        "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Pending"}, {"userEnteredValue": "Done"}]},
        "strict": true,
        "showCustomUi": true
      }
    }
  }
]
```

```sh
google-sheets batch SPREADSHEET_ID --requests-file /tmp/requests.json
# Same exact file and target, after authorization:
google-sheets batch SPREADSHEET_ID --requests-file /tmp/requests.json --confirm
```

Grid indices are zero-based with exclusive end indices. `repeatCell` uses a field mask to preserve unrelated formatting; `setDataValidation` has no `fields` property. A raw `updateCells` request can explicitly set `userEnteredValue.formulaValue`, independent of the values API's RAW default. Review raw batches carefully: they can include destructive actions and formula writes.

## MCP configuration

Install the CLI first, then add a stdio server entry to your MCP host's configuration. Replace the command and token paths with absolute paths valid on that machine; host JSON configurations do not generally expand `~` or shell variables.

```json
{
  "mcpServers": {
    "google-sheets": {
      "command": "/absolute/path/to/google-sheets",
      "args": ["mcp"],
      "env": {"GOOGLE_SHEETS_TOKEN_FILE": "/absolute/path/to/token.json"}
    }
  }
}
```

Tools: `sheets_info`, `sheets_read`, `sheets_create`, `sheets_write`, `sheets_append`, `sheets_clear`, `sheets_batch`, `sheets_tabs_add`, `sheets_tabs_rename`, `sheets_tabs_delete`, `sheets_table_plan`, and `sheets_table_apply`. Mutating tools have `confirm: false` by default and expose mutation annotations. Transport messages use stdout; operational diagnostics must not pollute it. Authentication is configured separately through the CLI. `google-sheets agent schema` outputs the MCP tool schemas as JSON; `google-sheets agent guide` prints operational guidance for agent integration.

## Verification and limits

```sh
uv sync --locked
uv run pytest
uv build
```

Tests use injected fake Google services and a real MCP stdio subprocess. The coverage gate requires 100% line and branch coverage for package code; subprocess-only execution is separately exercised and is not a reason to exclude code from coverage. Automated tests do not use live credentials or modify spreadsheets.

Live tests on a newly created synthetic workbook verified create and tab operations, literal RAW strings, explicit formula calculation, targeted update preservation of text/formulas/notes/format/validation, append, clear, and removal of a test tab. Ten additional live table scenarios verified rescheduling and preservation, template append, inventory edits, stale/mismatched/tampered/ambiguous plan rejection, literal-string/null behavior, native date serial updates preserving date formatting and dependent formulas, and escaped apostrophes in tab titles. All seventeen scenario groups passed; the existing interview tracker was not modified. See the [sanitized live verification record](docs/SETUP.md#recorded-live-verification-october-2026). These results are separate from the automated coverage gate.

After authentication, run `info` and `read` on an explicitly authorized spreadsheet to verify live access. Live write verification requires authorization for a disposable spreadsheet and must verify the resulting values and metadata. Do not test mutations against the interview tracker or other existing data without explicit scope.

Network calls have a bounded transport timeout and no automatic write retries. If a mutation times out, its outcome may be unknown: inspect Google state before deciding whether a retry is safe, especially for create and append. API error bodies and secrets are not printed. The CLI does not accept arbitrary endpoints or execute Apps Script. This package is now the active replacement for the archived `interview-sheet` integration.
