"""Literal table edits with a bounded snapshot guard (not an atomic CAS)."""
from copy import deepcopy
import json
import math
import re

from .client import SheetsError, _id


def validate_table_range(range_name):
    """Return inclusive, 1-based (header row, last row, last column)."""
    pattern = r"(?:(?:'[^'\r\n]*(?:''[^'\r\n]*)*'|[A-Za-z_][A-Za-z0-9_ ]*)!)?A([1-9][0-9]{0,7}):([A-Z]+)([1-9][0-9]{0,7})"
    matched = re.fullmatch(pattern, range_name) if isinstance(range_name, str) else None
    if not matched:
        raise SheetsError('Table range must be bounded A1 notation starting in column A, such as \'Tab\'!A1:K100.')
    first, letters, last = matched.groups()
    column = 0
    for letter in letters:
        column = column * 26 + ord(letter) - ord('A') + 1
    if int(last) < int(first) or column > 18278:
        raise SheetsError('Table range has invalid bounds.')
    return int(first), int(last), column



def validate_table_target(client, spreadsheet_id, range_name, sheet_id):
    """Resolve the read tab before permitting requests using its numeric ID."""
    _id(spreadsheet_id)
    validate_table_range(range_name)
    if type(sheet_id) is not int or sheet_id < 0:
        raise SheetsError('sheet_id must be a nonnegative integer.')
    sheets = [s['properties'] for s in client.metadata(spreadsheet_id).get('sheets', [])]
    if '!' in range_name:
        title = range_name.rsplit('!', 1)[0]
        if title.startswith("'"):
            title = title[1:-1].replace("''", "'")
        selected = [s for s in sheets if s['title'] == title]
    else:
        selected = sorted((s for s in sheets if not s.get('hidden', False)), key=lambda s: s.get('index', 0))[:1]
    if len(selected) != 1 or selected[0]['sheetId'] != sheet_id:
        raise SheetsError('Range tab does not match sheet_id; create a new plan with the correct target.')


def _primitive(value):
    if value is not None and (type(value) not in (str, bool, int, float) or (type(value) is float and not math.isfinite(value))):
        raise SheetsError('Table cells must be finite primitive JSON values.')


def _equal(left, right):
    # JSON distinguishes bool from number and preserves the exact read snapshot.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def plan_table(values, sheet_id, start_row, match, updates, allow_append=False, template_row=None):
    """Plan cell-only RAW changes; the first snapshot row supplies headers."""
    if type(sheet_id) is not int or sheet_id < 0 or type(start_row) is not int or start_row < 1:
        raise SheetsError('sheet_id must be a nonnegative integer and start_row a positive integer.')
    if type(allow_append) is not bool:
        raise SheetsError('allow_append must be a boolean.')
    if not isinstance(values, list) or not values or any(not isinstance(row, list) for row in values) or not values[0]:
        raise SheetsError('values must contain a nonempty header row and row arrays.')
    headers = values[0]
    if any(not isinstance(h, str) or not h.strip() for h in headers):
        raise SheetsError('Headers must be nonempty strings.')
    headers = [h.strip() for h in headers]
    if len(set(headers)) != len(headers):
        raise SheetsError('Headers must be unique after trimming.')
    for row in values:
        if len(row) > len(headers):
            raise SheetsError('Snapshot rows cannot exceed the header width.')
        for value in row:
            _primitive(value)
    for mapping in (match, updates):
        if not isinstance(mapping, dict) or not mapping:
            raise SheetsError('match and updates must be nonempty objects.')
        for key, value in mapping.items():
            if key not in headers:
                raise SheetsError('match and updates keys must match trimmed headers exactly.')
            _primitive(value)
    if template_row is not None and (type(template_row) is not int or not start_row < template_row < start_row + len(values)):
        raise SheetsError('template_row must identify an existing data row in the snapshot.')
    indices = {header: i for i, header in enumerate(headers)}
    found = []
    for offset, record in enumerate(values[1:], 1):
        if all(_equal(record[indices[key]] if indices[key] < len(record) else None, value) for key, value in match.items()):
            found.append(start_row + offset)
    if len(found) > 1:
        raise SheetsError('Match is ambiguous; more than one row matches.')
    action = 'update'
    cells = updates
    if found:
        target_row = found[0]
    else:
        if not allow_append:
            raise SheetsError('No matching row; allow_append is required to add one.')
        if any(key in updates and not _equal(value, updates[key]) for key, value in match.items()):
            raise SheetsError('Append match and update values conflict.')
        action = 'append'
        cells = {**match, **updates}
        last = max((i for i, row in enumerate(values) if any(value is not None and value != '' for value in row)), default=0)
        target_row = start_row + last + 1
    requests = []
    if action == 'append' and template_row is not None:
        source = {'sheetId': sheet_id, 'startRowIndex': template_row - 1, 'endRowIndex': template_row, 'startColumnIndex': 0, 'endColumnIndex': len(headers)}
        destination = {**source, 'startRowIndex': target_row - 1, 'endRowIndex': target_row}
        requests.extend({'copyPaste': {'source': source, 'destination': destination, 'pasteType': paste_type}} for paste_type in ('PASTE_FORMAT', 'PASTE_DATA_VALIDATION'))
    for header in headers:
        if header not in cells:
            continue
        value = cells[header]
        cell = {}
        if value is not None:
            field = 'boolValue' if type(value) is bool else 'numberValue' if type(value) in (int, float) else 'stringValue'
            cell['userEnteredValue'] = {field: value}
        requests.append({'updateCells': {'start': {'sheetId': sheet_id, 'rowIndex': target_row - 1, 'columnIndex': indices[header]}, 'rows': [{'values': [cell]}], 'fields': 'userEnteredValue'}})
    return deepcopy({'version': 1, 'sheet_id': sheet_id, 'start_row': start_row, 'snapshot': values, 'match': match, 'updates': updates, 'allow_append': allow_append, 'template_row': template_row, 'action': action, 'row': target_row, 'requests': requests})


def apply_table(client, spreadsheet_id, range_name, plan, confirm=False):
    """Validate/rederive locally; confirmed writes reread before one batch."""
    _id(spreadsheet_id)
    if type(confirm) is not bool:
        raise SheetsError('confirm must be a boolean.')
    first, last, width = validate_table_range(range_name)
    if not isinstance(plan, dict):
        raise SheetsError('Table plan must be an object.')
    try:
        expected = plan_table(plan['snapshot'], plan['sheet_id'], plan['start_row'], plan['match'], plan['updates'], plan['allow_append'], plan['template_row'])
        identical = _equal(plan, expected)
    except (KeyError, ValueError, TypeError, OverflowError, RecursionError):
        raise SheetsError('Invalid table plan; create a new plan.') from None
    if not identical:
        raise SheetsError('Table plan was modified; create a new plan.')
    if first != plan['start_row'] or len(plan['snapshot'][0]) > width or first + len(plan['snapshot']) - 1 > last:
        raise SheetsError('Table range does not cover the planned snapshot.')
    if plan['row'] > last:
        raise SheetsError('Table range has no append capacity; choose a larger bounded range.')
    if not confirm:
        return {'status': 'preview', 'operation': 'table', 'spreadsheet_id': spreadsheet_id, 'range': range_name, 'plan': expected}
    validate_table_target(client, spreadsheet_id, range_name, plan['sheet_id'])
    current = client.read(spreadsheet_id, range_name, render='FORMULA').get('values', [])
    if not _equal(current, plan['snapshot']):
        raise SheetsError('Table changed since planning; create and review a new plan.')
    return client.batch(spreadsheet_id, expected['requests'], confirm=True)
