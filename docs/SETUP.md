# Setup and operational runbook

This document records how the standalone Google Sheets integration was configured, why each component exists, and how to repeat the setup on another machine. Examples intentionally omit real account addresses, project identifiers, spreadsheet contents, and credentials.

## Architecture and the migration path

The first implementation was a separate `interview-sheet` CLI calling a token-protected Apps Script web app. That endpoint understood a particular interview tracker: its headers, booking dates, and company matching rules. Its script was backed up, corrected, saved, and deployed in its existing Apps Script project. Saving an Apps Script source file and deploying a new web-app version are separate operations.

The broader requirement was a reusable Google Sheets integration. This repository therefore uses the official Google Sheets API, Google authentication libraries, and MCP SDK. The `google-sheets` command and stdio MCP server share the same implementation. The repository name ends in `-mcp`; the command remains `google-sheets`. No Apps Script web app or shared endpoint token is required by this package.

The existing interview-specific endpoint and repository remain separate. Installing this tool does not replace that deployment, change an existing workbook, migrate records, or edit a central agent-skills repository. Generic table planning adds header-based record updates without hard-coding interview fields. See [table workflows](table-workflows.md).

## What happened during the original setup

1. A new Google Cloud project was attempted. Its proposed name exceeded the console's length limit, and the selected account lacked `resourcemanager.projects.create` at the chosen parent. Those are different errors; shortening a name does not grant permissions.
2. An existing authorized project was selected instead. The original project was named NavAR. Reusing a project avoided needing project-creation permission; permissions to enable an API and manage OAuth clients were still required.
3. **Google Sheets API** was selected from the API library. The separate **Sheets MCP API** entry was not used. This package provides its own local MCP interface over the standard Sheets API.
4. A separate **Desktop app** OAuth client was created for the CLI, preserving existing application credentials. The console's AI-powered-agent designation was selected during this setup. That designation is not itself a grant of spreadsheet access; the OAuth scopes and user's workbook permissions govern access.
5. The downloaded client JSON was installed outside source control at `$HOME/.config/google-sheets-mcp/client_secret.json` with private file permissions. The login command opened the browser and waited for a local callback.
6. The first login failed with `403 access_denied`: the consent configuration was in Testing mode, and the selected account was not an approved test user. Adding that account under **Google Auth Platform → Audience → Test users**, saving, and starting a fresh login resolved this error. No public-verification claim is implied by that success.
7. Consent succeeded and the CLI stored a token privately. A live API read of the existing interview tracker's eleven headers succeeded. That verified authenticated read access; it did not establish write behavior or permission for unrelated spreadsheets.

The record above describes this installation, not prerequisites that every user must reproduce. A personal account, another permitted project, or a properly shared service account can use the same package.

## Repeatable installation

Use Python 3.11 or later and [uv](https://docs.astral.sh/uv/). From a checked-out copy of this repository:

```sh
uv sync --locked
uv run pytest
uv build
uv tool install .
google-sheets --help
google-sheets doctor
```

`doctor` is deliberately local. Its `network_checked: false` and `authenticated: false` do not mean a known login was revoked; they mean this command has not established live authentication. Check whether the credential file is present and private, then use a bounded API read to verify access.

## Configure Google Cloud

Select an existing project you are authorized to manage, or create one if your account has permission. A school or work account may be subject to administrator policy. Do not modify unrelated application clients or an existing consent screen merely to work around a restriction.

1. Under **APIs & Services → Library**, enable **Google Sheets API**. If it is already enabled, keep it enabled.
2. Review the existing **Google Auth Platform** consent configuration. Configure it if absent. If the audience is external and publishing status is Testing, add the exact Google account that will log in as a test user.
3. Under **Google Auth Platform → Clients**, create a separate client with type **Desktop app**, for example `Google Sheets CLI`. If using the API credentials wizard, select **User data**, not Application data.
4. Download the client JSON. Do not paste its contents into chat or commit it. Existing NavAR or other app credentials should remain intact.

Google's console labels can change. The authoritative setup reference is the [Sheets Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python); the authentication mechanism is the [OAuth installed-app flow](https://developers.google.com/identity/protocols/oauth2/native-app).

## Store credentials and authorize

Replace the downloaded filename below with your own. The destination is outside any repository:

```sh
mkdir -p "$HOME/.config/google-sheets-mcp"
chmod 700 "$HOME/.config/google-sheets-mcp"
install -m 600 "$HOME/Downloads/DOWNLOADED_CLIENT.json" \
  "$HOME/.config/google-sheets-mcp/client_secret.json"
google-sheets auth login \
  --client-secrets "$HOME/.config/google-sheets-mcp/client_secret.json"
```

Choose the account with access to your spreadsheets and review consent. The tool requests `https://www.googleapis.com/auth/spreadsheets`, allowing Sheets operations within that account's existing permissions. It does not grant access to files the user cannot already access. The browser callback binds to `127.0.0.1` on an available port and waits up to 180 seconds. Start a fresh login if the wait expires.

The default token file is `$HOME/.config/google-sheets-mcp/token.json`. Login writes it atomically with mode `600`. Refreshed tokens are also saved privately. The token must not be a symbolic link or reside inside a source repository. To choose a different location, use `auth login --token-file /absolute/private/token.json`, then set `GOOGLE_SHEETS_TOKEN_FILE` for subsequent commands and the MCP host.

The client JSON and token are distinct: the client describes the application; the token authorizes a user. Never publish either file. After confirming the installed copy works, manage any duplicate Downloads copy according to your own credential-retention policy.

Ordinary reads, writes, and MCP calls do not trigger an interactive browser login. When refresh fails or consent is revoked, rerun the explicit login command. For an external app in Testing mode, refresh tokens for the requested Sheets scope generally expire after seven days, requiring a fresh login; consult Google's [OAuth token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration) before relying on unattended operation. Do not silently change a shared project's publishing status.

## Verify the account without modifying data

Obtain a spreadsheet ID from a workbook you are authorized to read. It is the portion between `/d/` and `/edit` in the Sheets URL. Do not substitute the numeric tab ID (`gid`).

```sh
google-sheets info SPREADSHEET_ID
google-sheets read SPREADSHEET_ID "'Sheet1'!A1:K1"
```

An API success proves access to that workbook at that moment. A local `doctor` result, a successful login, or an offline preview is not equivalent. Keep output and plan files containing workbook data out of the repository.

## Configure an MCP host

Use the executable installed by `uv tool install`. Run `command -v google-sheets` to find its absolute path. Most hosts do not expand shell variables or `~` in configuration JSON:

```json
{
  "mcpServers": {
    "google-sheets": {
      "command": "/absolute/path/to/google-sheets",
      "args": ["mcp"],
      "env": {
        "GOOGLE_SHEETS_TOKEN_FILE": "/absolute/private/path/token.json"
      }
    }
  }
}
```

Restart or reconnect the host after changing its configuration. Run `google-sheets agent schema` for the actual tool definitions and `google-sheets agent guide` for usage guidance. MCP protocol output uses stdout; do not wrap the server in a shell script that prints banners there. Install the repository's `skills/google-sheets` instructions in your agent's skill directory using that host's supported process. The skill supplies operational guidance; the executable supplies functionality.

## Service-account alternative

Set `GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE` to a private key JSON file outside source control, and share the target spreadsheet with that service account's email using the appropriate role. This setting takes precedence over desktop OAuth. Keep the key private. The tool does not expose Drive sharing APIs or manage organizational policy. Remove an unintended service-account environment setting if you meant to use your saved OAuth login.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Project creation permission denied | Select an existing permitted project or obtain the required project-creation permission. OAuth does not require a new project. |
| Login says only approved testers can access | Add the exact signing-in account to the selected project's test users; save and restart login. |
| Login times out | Restart `auth login` and finish consent within the callback wait. |
| Organization blocks consent | Ask the account administrator about its policy; do not treat test-user registration as an override. |
| API disabled | Enable the standard Google Sheets API in the client credential's project. |
| Missing token or insecure file permissions | Confirm the selected token path and restrict it to mode `600`; run login if missing. |
| Read gets permission denied or not found | Check the signing-in identity, spreadsheet ID, and that account's access to the workbook. |
| A write times out | Read the affected range before any retry. A timeout may follow a successful write. |
| A table plan is stale | Re-read and create a fresh plan, then review it again. Do not force an old plan through. |

## Tests, releases, and live evidence

The `uv run pytest` gate measures package lines and branches and requires 100% coverage. It includes injected Google service behavior, credential and failure paths, official discovery-request serialization, and a real MCP stdio session that initializes, lists tools, and exercises offline previews. These tests need no Google credentials. Coverage establishes exercised code paths, not proof that every possible Google state or race is handled.

For live write verification, use an explicitly authorized disposable spreadsheet containing synthetic records. Exercise targeted edits, formulas, notes, format and validation preservation, append with a template, stale-plan rejection, and read-back. Never use an existing interview tracker as a mutation test fixture. Report actual successful checks separately from offline tests; retain no private workbook contents in test fixtures or public evidence.

Before releasing changes, run `uv sync --locked`, `uv run pytest`, and `uv build`; inspect the diff for credentials and personal data, commit the intended files, and push to the repository's configured remote within the user's authorization. GitHub Actions runs the same tests and build on Python 3.11, 3.12, and 3.13. Check the workflow result for the pushed commit rather than assuming that a push implies CI success. Reinstall the tool when using a non-editable local installation and reconnect long-running MCP hosts.

Google hosts the spreadsheet data and API; this repository hosts code, skill instructions, and tests. Neither committing code nor starting an MCP server changes a workbook. Mutations preview by default and require explicit execution confirmation, with user authorization for the actual operation.

## API quotas and cost boundary

This CLI has no subscription charge and setup does not enable paid services. It does not implement a local quota limiter or enforce a hard cost cap. Google controls API quotas and pricing; check its [current Sheets usage limits](https://developers.google.com/workspace/sheets/api/limits) for your project before scaling automation. A no-retry transport prevents automatic replay of uncertain writes, but is not a billing control.

## Recorded live verification, October 2026

Seventeen scenario groups passed against one newly created synthetic Google spreadsheet. The existing interview tracker was not modified. The first table update exercised the installed CLI's plan/apply path; subsequent checks used the shared implementation and verified actual Google state.

| Scenario | Observed result |
| --- | --- |
| Create workbook, rename and add tabs | New synthetic workbook and requested tab properties read back successfully. |
| RAW formula-looking text | Grid metadata retained a literal string rather than a formula. |
| Explicit formula | A deliberately entered formula calculated the expected result. |
| Targeted ordinary update | Untouched collaborator text, formula, cell note, formatting, and validation survived. |
| Ordinary append | A leading-zero SKU remained text. |
| Clear | Only the targeted cell value was cleared. |
| Tab deletion | A newly created test tab was removed. |
| Table rescheduling | Date, time, and status changed while untouched cells, formula, note, format, and validation survived. |
| Table append from a template | Formatting and dropdown validation copied; notes and formulas were not copied. |
| Inventory table update | Arbitrary SKU and quantity headers worked without interview-specific assumptions. |
| Stale snapshot | Apply rejected a plan after intervening cell changes. |
| Wrong tab ID | A tab-name/numeric-ID mismatch was rejected. |
| Altered requests | A plan containing modified generated requests was rejected. |
| Duplicate match | Ambiguous records were rejected. |
| Literal string and clearing | Formula-looking table text remained literal, and null cleared the intended value. |
| Apostrophe in tab title | An escaped A1 title such as `'Owner''s fixture'!A1:C10` resolved to the intended tab and supported a guarded update. |
| Native date serial and dependent formula | A numeric date serial matched and rescheduled correctly; custom `mmm d, yyyy` formatting survived, the dependent `=TEXT(B2,"dddd")` formula remained intact and recalculated Tuesday, and the cell note was untouched. |

These are observed live checks, not a claim of exhaustive Google-runtime coverage. Private verification scripts and raw evidence are retained locally outside the repository under `$HOME/.local/share/google-sheets-mcp/verification/`; they are not portable fixtures or committed credentials. Repeat the scenarios with a newly authorized synthetic workbook to validate another account or environment. The automated suite remains credential-free and repeatable in CI.
