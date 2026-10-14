"""Bounded, literal, guarded table changes."""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from google_sheets_mcp.client import SheetsError
from google_sheets_mcp.tables import apply_table, plan_table, validate_table_range

VALUES = [[' ID ', 'Name', 'Done', 'Formula'], ['a', 'Alice', False, '=1+1'], ['b', 'Bob', True]]


def plan(**kwargs):
    return plan_table(**{'values': VALUES, 'sheet_id': 7, 'start_row': 3,
                         'match': {'ID': 'a'}, 'updates': {'Name': '=literal'}, **kwargs})


def test_literal_partial_update_and_no_network_preview():
    p = plan(updates={'Name': '=literal', 'Done': None})
    assert p['action'] == 'update' and p['row'] == 4
    assert p['requests'] == [
        {'updateCells': {'start': {'sheetId': 7, 'rowIndex': 3, 'columnIndex': 1},
                         'rows': [{'values': [{'userEnteredValue': {'stringValue': '=literal'}}]}], 'fields': 'userEnteredValue'}},
        {'updateCells': {'start': {'sheetId': 7, 'rowIndex': 3, 'columnIndex': 2},
                         'rows': [{'values': [{}]}], 'fields': 'userEnteredValue'}}]
    client = MagicMock()
    assert apply_table(client, 'abc', "'My Tab'!A3:D20", p)['status'] == 'preview'
    assert client.mock_calls == []


def test_append_template_and_types():
    p = plan(match={'ID': 'new'}, updates={'Name': '=literal', 'Done': True, 'Formula': 42.5}, allow_append=True, template_row=4)
    assert p['row'] == 6 and p['action'] == 'append'
    assert [r['copyPaste']['pasteType'] for r in p['requests'][:2]] == ['PASTE_FORMAT', 'PASTE_DATA_VALIDATION']
    assert p['requests'][0]['copyPaste']['source']['startRowIndex'] == 3
    assert p['requests'][-2]['updateCells']['rows'][0]['values'][0]['userEnteredValue'] == {'boolValue': True}
    assert p['requests'][-1]['updateCells']['rows'][0]['values'][0]['userEnteredValue'] == {'numberValue': 42.5}
    assert plan(values=[['ID'], [], [None], ['']], match={'ID': 0}, updates={'ID': 0}, allow_append=True)['row'] == 4


def test_confirm_and_stale_and_type_guard():
    p = plan()
    client = MagicMock()
    client.metadata.return_value = {'sheets': [{'properties': {'sheetId': 7, 'title': 'Tab', 'index': 0}}]}
    client.read.return_value = {'values': deepcopy(VALUES)}
    client.batch.return_value = {'status': 'applied'}
    assert apply_table(client, 'abc', 'A3:D9', p, True) == {'status': 'applied'}
    client.read.assert_called_once_with('abc', 'A3:D9', render='FORMULA')
    client.batch.assert_called_once_with('abc', p['requests'], confirm=True)
    client.reset_mock()
    client.read.return_value = {'values': [['changed']]}
    with pytest.raises(SheetsError, match='changed'): apply_table(client, 'abc', 'A3:D9', p, True)
    client.batch.assert_not_called()
    client.read.return_value = {}
    with pytest.raises(SheetsError, match='changed'): apply_table(client, 'abc', 'A3:D9', p, True)
    assert plan(values=[['ID'], [True], [1]], match={'ID': 1}, updates={'ID': 2})['row'] == 5


@pytest.mark.parametrize('range_name', ['', None, 'A:A', 'A1', 'B1:D10', 'A0:D2', 'A9:D1', 'A1:A0', 'a1:b3', 'x!y!A1:B3', "'bad!A1:B3", 'A1:AAAA2'])
def test_bad_range(range_name):
    with pytest.raises(SheetsError): validate_table_range(range_name)


def test_ranges():
    assert validate_table_range("'Joe''s tab'!A3:AA100") == (3, 100, 27)
    assert validate_table_range('Sheet1!A1:A1') == (1, 1, 1)


@pytest.mark.parametrize('kwargs', [
    {'sheet_id': True}, {'sheet_id': -1}, {'start_row': 0}, {'start_row': False},
    {'values': []}, {'values': 'bad'}, {'values': [[]]}, {'values': [['ID'], 'bad']},
    {'values': [['ID'], [1, 2]]}, {'values': [['ID'], [{}]]}, {'values': [['ID'], [float('nan')]]},
    {'values': [[1]]}, {'values': [[' ']]}, {'values': [['ID', ' ID ']]},
    {'match': {}}, {'match': []}, {'match': {'missing': 'x'}}, {'match': {1: 'x'}},
    {'updates': {}}, {'updates': {'Name': []}}, {'updates': {'Name': float('inf')}},
    {'allow_append': 1}, {'match': {'ID': 'missing'}},
    {'values': [['ID'], ['a'], ['a']], 'updates': {'ID': 'b'}},
    {'template_row': True}, {'template_row': 3}, {'template_row': 99},
    {'match': {'ID': 'new'}, 'updates': {'ID': 'other'}, 'allow_append': True},
])
def test_invalid_plan(kwargs):
    with pytest.raises(SheetsError): plan(**kwargs)


@pytest.mark.parametrize('change', [lambda p: p.update(extra=True), lambda p: p['requests'].append({'deleteSheet': {'sheetId': 7}}), lambda p: p.update(row=True), lambda p: p.pop('snapshot')])
def test_tampered(change):
    p = plan(); change(p)
    client = MagicMock()
    with pytest.raises(SheetsError): apply_table(client, 'abc', 'A3:D9', p, True)
    assert not client.mock_calls


@pytest.mark.parametrize('id,range_name,p,confirm', [
    ('https://bad', 'A3:D9', None, False), ('abc', 'A3:D9', [], False),
    ('abc', 'A3:D9', None, 1), ('abc', 'A1:D9', None, False),
    ('abc', 'A3:C9', None, False), ('abc', 'A3:D4', None, False),
])
def test_apply_local_validation(id, range_name, p, confirm):
    client = MagicMock()
    with pytest.raises(SheetsError): apply_table(client, id, range_name, plan() if p is None else p, confirm)
    assert not client.mock_calls


def test_append_capacity_and_detached_snapshot():
    p = plan(match={'ID': 'new'}, allow_append=True)
    with pytest.raises(SheetsError, match='capacity'): apply_table(MagicMock(), 'abc', 'A3:D5', p)
    apply_table(MagicMock(), 'abc', 'A3:D6', p)
    p['snapshot'][1][0] = 'different'
    assert VALUES[1][0] == 'a'


def test_target_binding():
    from google_sheets_mcp.tables import validate_table_target
    client = MagicMock()
    client.metadata.return_value = {'sheets': [
        {'properties': {'sheetId': 1, 'title': 'Hidden', 'index': 0, 'hidden': True}},
        {'properties': {'sheetId': 7, 'title': "Joe's tab", 'index': 2}},
        {'properties': {'sheetId': 3, 'title': 'First', 'index': 1}}]}
    validate_table_target(client, 'abc', "'Joe''s tab'!A1:D9", 7)
    validate_table_target(client, 'abc', 'First!A1:D9', 3)
    validate_table_target(client, 'abc', 'A1:D9', 3)
    with pytest.raises(SheetsError, match='sheet_id'):
        validate_table_target(client, 'abc', 'A1:D9', 7)
    with pytest.raises(SheetsError, match='sheet_id'):
        validate_table_target(client, 'abc', 'Missing!A1:D9', 7)
    client.metadata.return_value = {}
    with pytest.raises(SheetsError, match='sheet_id'):
        validate_table_target(client, 'abc', 'A1:D9', 7)
    with pytest.raises(SheetsError):
        validate_table_target(client, 'abc', 'A1:D9', True)


def test_guard_checks_target_before_read():
    client = MagicMock()
    client.metadata.return_value = {'sheets': [{'properties': {'sheetId': 99, 'title': 'Tab'}}]}
    with pytest.raises(SheetsError, match='sheet_id'):
        apply_table(client, 'abc', 'Tab!A3:D9', plan(), True)
    client.read.assert_not_called()
    client.batch.assert_not_called()


def test_excessive_range_coordinate_is_safe_error():
    range_name = 'A' + '9' * 5000 + ':Z' + '9' * 5000
    with pytest.raises(SheetsError):
        validate_table_range(range_name)
