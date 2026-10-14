# General table updates

Use table planning when records are identified by header values rather than a fixed cell address. The same workflow works for interview schedules, inventory, project status, contact lists, and other rectangular tables. For a project tracker, for example, match `{"Issue":"TASK-42"}` and update `{"Owner":"Example owner","Status":"In progress"}`; no application-specific schema is required. Use ordinary `read`, `write`, `append`, and `batch` for coordinate-based operations, formulas, or workbook structure changes.

## Plan, review, apply, verify

The bounded range must start in column A and contain a header row followed by records. For example, `'Pipeline'!A1:F100` identifies the header row at row 1, six columns, and space through row 100. A range starting at a later row supports a table below introductory content. For a tab title containing an apostrophe, table commands require doubling that apostrophe inside the quoted A1 title: `Owner's fixture` becomes `'Owner''s fixture'!A1:C10`. Read `info` to get the numeric tab `sheetId` corresponding to the range's tab title.

Create input JSON files and save the plan in private storage. Plan files contain the read snapshot and therefore may contain sensitive spreadsheet data. This example uses only synthetic records:

```sh
umask 077
mkdir -p "$HOME/.local/share/google-sheets-mcp/plans"
printf '%s\n' '{"Company":"Example Co","Date":"2026-10-26"}' > /tmp/match.json
printf '%s\n' '{"Date":"2026-10-27","Time":"12:30 PM","Weekday":"Tuesday"}' > /tmp/updates.json
google-sheets table plan SPREADSHEET_ID "'Pipeline'!A1:F100" \
  --sheet-id 123 \
  --match-file /tmp/match.json \
  --updates-file /tmp/updates.json \
  > "$HOME/.local/share/google-sheets-mcp/plans/reschedule.json"
google-sheets table apply \
  --plan-file "$HOME/.local/share/google-sheets-mcp/plans/reschedule.json"
# Once the exact proposed edit is reviewed and authorized:
google-sheets table apply \
  --plan-file "$HOME/.local/share/google-sheets-mcp/plans/reschedule.json" \
  --confirm
google-sheets read SPREADSHEET_ID "'Pipeline'!A1:F10" --render FORMULA
```

Replace the example headers with the exact headers present in your table. Unlike a mutation preview, **`table plan` makes a read-only network call** to validate the tab name/ID against workbook metadata and obtain a FORMULA-rendered snapshot. **`table apply` without `--confirm` validates and previews locally**, with no credential loading or network call. A confirmed apply revalidates the tab name/ID and re-reads the bounded range and refuses a stale snapshot before submitting one batch. The plan envelope binds the spreadsheet ID and range to the reviewed operation; do not manually retarget a saved plan.

## Matching and preserving data

Headers are trimmed and must be unique and nonempty. Match and update keys refer to those header names. Matching is case-sensitive and type-aware, with no automatic date normalization: the boolean `true`, number `1`, and string `"1"` are distinct. Include enough fields to identify one record. Multiple matches are an error, not permission to update the first one. A missing match is an error unless `--allow-append` was explicitly supplied.

For an existing record, only the requested cells receive `userEnteredValue` updates. Other values, formulas, collaborator text, cell notes, formatting, and validation are not overwritten by a whole-row replacement. JSON `null` clears a cell's value. Strings are literal, including strings beginning with `=`; table edits do not implicitly evaluate formulas. Use explicit `write --input-option USER_ENTERED` or a reviewed native batch formula request when that is the intended operation.

Updates can change a matched key, which supports rescheduling by matching the original date and writing the new date. The tool does not infer date formats, weekdays, interview outcomes, or business semantics. The example writes Date and Weekday together explicitly. A FORMULA-rendered read returns native date values as numeric serials rather than the displayed date text. Match the returned value exactly. A spreadsheet-native date is a number with a date number format; use a deliberately prepared batch when you need typed date semantics, rather than assuming an ISO text value becomes a native date.

## Append with consistent formatting

`--allow-append` allows a missing match to become a new record using the union of match and update fields. Conflicting values for the same field are rejected when appending. An existing unique match is still updated. The new record is placed after the last nonempty row inside the supplied snapshot. The bounded range must have enough space; a full range causes refusal rather than a write into unread rows.

```sh
printf '%s\n' '{"SKU":"00123"}' > /tmp/match.json
printf '%s\n' '{"Product":"Example item","Quantity":4,"Status":"Pending"}' > /tmp/updates.json
google-sheets table plan SPREADSHEET_ID "'Inventory'!A1:D100" \
  --sheet-id 456 --match-file /tmp/match.json --updates-file /tmp/updates.json \
  --allow-append --template-row 2 \
  > "$HOME/.local/share/google-sheets-mcp/plans/inventory.json"
google-sheets table apply \
  --plan-file "$HOME/.local/share/google-sheets-mcp/plans/inventory.json"
```

`--template-row` is an absolute, one-based row number of an existing data row within the snapshot. It copies format and data validation over the table width before entering values. It does not copy values or formulas. Thus a generated total column needs an explicit formula operation if desired. A header-only table can append without a template. Omitted fields in a new record are left empty.

## Equivalent interview-tracker tasks

| Previous task | General operation |
| --- | --- |
| Find a booking by company and date | Read a bounded range and plan an edit with those headers as match fields. There is no implicit interview schema. |
| Reschedule while identifying the previous date | Match Company + old Date (+ Interview Round when needed), update Date + Time + Weekday deliberately; update status only when established. |
| Preserve collaborator notes | Update only the intended fields; omit note columns entirely. |
| Add a confirmed booking | Use `--allow-append` with enough bounded capacity and an appropriate template row. |
| Keep the last row's formatting consistent | Choose a known existing data row as `--template-row`; verify format and validation with `info --range ... --include-grid-data`. |
| Prevent ambiguous company-only changes | Use a composite match; duplicate matches fail instead of selecting arbitrarily. |
| Update arbitrary workbook formatting or tabs | Use the existing tabs commands and native batch requests with narrow field masks. |

Business decisions remain outside the tool. A positive conversation does not imply a passed interview, and a tentative lead does not imply a confirmed booking. The separate legacy `interview-sheet` endpoint can still be used for its specialized validation.

## MCP equivalents

`sheets_table_plan` reads and returns a plan; `sheets_table_apply` accepts the saved plan envelope and defaults to `confirm: false`. Obtain exact parameter definitions through `google-sheets agent schema` or the MCP host's tool discovery rather than rebuilding request objects by hand. MCP confirmation accepts a real boolean. Both interfaces share the same planning and application implementation.

## Concurrency and limits

The stale check detects differences in the snapshot values, including formula text. It is **not an atomic compare-and-swap**: another writer can change the spreadsheet between the guard read and the batch write. It also does not detect metadata-only changes, such as a formatting edit, because the snapshot is a values read. For a shared sheet, keep the review-to-apply interval short and coordinate edits where needed. After a stale-plan error, generate and review a fresh plan.

Do not treat a saved plan as a signed authorization artifact. Application rederives supported operations from its intent and snapshot rather than trusting arbitrary embedded requests, but callers still need the user's approval for the chosen operation. Keep plan files private and preserve the reviewed target and arguments.

Native batch requests remain available for operations that table edits intentionally do not infer: charts, merged cells, formulas, filter rules, row insertion, and typed dates. These are powerful operations and require reviewing their full scope. No write is blindly retried after an uncertain network failure; read back first.
