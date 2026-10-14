import json
from unittest.mock import Mock

import pytest

from google_sheets_mcp import cli


@pytest.fixture
def client(monkeypatch):
    instance = Mock()
    for name in ('metadata', 'read', 'create', 'write', 'append', 'clear', 'batch'):
        getattr(instance, name).return_value = {'status': 'preview'}
    monkeypatch.setattr(cli, 'SheetsClient', lambda: instance)
    return instance


def test_write_preview_and_confirm(tmp_path, client, capsys):
    path = tmp_path / 'values.json'
    path.write_text('[["=1+2", 5]]')
    assert cli.main(['write', 'sheet123', 'A1', '--values-file', str(path)]) == 0
    client.write.assert_called_once_with('sheet123', 'A1', [['=1+2', 5]], input_option='RAW', confirm=False)
    assert json.loads(capsys.readouterr().out)['status'] == 'preview'
    cli.main(['append', 'sheet123', 'A1', '--values-file', str(path), '--input-option', 'USER_ENTERED', '--confirm'])
    client.append.assert_called_once_with('sheet123', 'A1', [['=1+2', 5]], input_option='USER_ENTERED', confirm=True)


@pytest.mark.parametrize('args,method,expected,kwargs', [
    (['info', 'abc'], 'metadata', ('abc',), {}),
    (['read', 'abc', 'A1', '--render', 'FORMULA'], 'read', ('abc', 'A1'), {'render': 'FORMULA'}),
    (['create', 'Title'], 'create', ('Title',), {'confirm': False}),
    (['clear', 'abc', 'A1', '--confirm'], 'clear', ('abc', 'A1'), {'confirm': True}),
])
def test_dispatch(args, method, expected, kwargs, client):
    assert cli.main(args) == 0
    getattr(client, method).assert_called_once_with(*expected, **kwargs)


def test_batch_and_tabs(tmp_path, client):
    path = tmp_path / 'batch.json'
    path.write_text('[{"addSheet":{"properties":{"title":"New"}}}]')
    cli.main(['batch', 'abc', '--requests-file', str(path)])
    assert client.batch.call_args.args[1][0]['addSheet']['properties']['title'] == 'New'
    cli.main(['tabs', 'rename', 'abc', '5', 'Renamed'])
    client.batch.assert_called_with('abc', [{'updateSheetProperties': {'properties': {'sheetId': 5, 'title': 'Renamed'}, 'fields': 'title'}}], confirm=False)
    cli.main(['tabs', 'add', 'abc', 'New'])
    cli.main(['tabs', 'delete', 'abc', '5', '--confirm'])
    client.batch.assert_called_with('abc', [{'deleteSheet': {'sheetId': 5}}], confirm=True)


@pytest.mark.parametrize('content', ['oops secret', '[NaN]', '[Infinity]'])
def test_invalid_json_safe(content, tmp_path, client, capsys):
    path = tmp_path / 'values.json'
    path.write_text(content)
    assert cli.main(['write', 'abc', 'A1', '--values-file', str(path)]) == 2
    output = capsys.readouterr()
    assert json.loads(output.err)['error']
    assert 'secret' not in output.err
    client.write.assert_not_called()


def test_file_size_and_missing(tmp_path, client, capsys, monkeypatch):
    path = tmp_path / 'big.json'
    path.write_text(' ' * 20)
    monkeypatch.setattr(cli, 'MAX_JSON_BYTES', 10)
    assert cli.main(['batch', 'abc', '--requests-file', str(path)]) == 2
    assert cli.main(['batch', 'abc', '--requests-file', str(tmp_path / 'missing')]) == 2
    assert 'Traceback' not in capsys.readouterr().err


def test_parser_errors_json(capsys):
    assert cli.main(['write']) == 2
    assert json.loads(capsys.readouterr().err)['error']


def test_unexpected_errors_are_redacted(client, capsys):
    client.metadata.side_effect = RuntimeError('token=supersecret')
    assert cli.main(['info', 'abc']) == 1
    assert 'supersecret' not in capsys.readouterr().err


def test_auth_and_mcp(monkeypatch):
    doctor = Mock(return_value={'ok': True})
    login = Mock(return_value={'ok': True})
    monkeypatch.setattr(cli.auth, 'doctor', doctor)
    monkeypatch.setattr(cli.auth, 'login', login)
    assert cli.main(['doctor']) == 0
    assert cli.main(['auth', 'login', '--client-secrets', 'client.json', '--token-file', 'token.json']) == 0
    login.assert_called_once_with('client.json', token_path='token.json')
    from google_sheets_mcp import mcp_server
    run = Mock()
    monkeypatch.setattr(mcp_server, 'run', run)
    assert cli.main(['mcp']) == 0
    run.assert_called_once()


def test_agent_commands(capsys):
    assert cli.main(['agent', 'guide']) == 0
    guide = json.loads(capsys.readouterr().out)
    assert guide['defaults'] == {'input_option': 'RAW', 'confirm': False}
    assert cli.main(['agent', 'schema']) == 0
    schema = json.loads(capsys.readouterr().out)
    assert any(tool['name'] == 'sheets_write' for tool in schema['tools'])


@pytest.mark.parametrize('action,title,sheet_id', [('add', '', None), ('rename', 'Name', -1), ('delete', None, True)])
def test_invalid_tab_arguments(action, title, sheet_id):
    with pytest.raises(cli.SheetsError):
        cli.tab_requests(action, title, sheet_id)


def test_info_grid_data(client):
    assert cli.main(['info', 'abc', '--range', 'A1:B2', '--range', 'D5', '--include-grid-data']) == 0
    client.metadata.assert_called_once_with('abc', ranges=['A1:B2', 'D5'], include_grid_data=True)


def test_module_entrypoint(monkeypatch, capsys):
    import runpy
    import sys
    monkeypatch.setattr(sys, 'argv', ['google-sheets', 'create', 'Offline preview'])
    monkeypatch.delitem(sys.modules, 'google_sheets_mcp.cli', raising=False)
    with pytest.raises(SystemExit) as result:
        runpy.run_module('google_sheets_mcp.cli', run_name='__main__')
    assert result.value.code == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'preview'


def test_table_plan_and_apply(tmp_path, client, capsys):
    client.metadata.return_value = {'sheets': [{'properties': {'sheetId': 0, 'title': 'Sheet1', 'index': 0}}]}
    snapshot = [['Account', 'Stage'], ['A', 'old']]
    client.read.return_value = {'values': snapshot}
    match = tmp_path / 'match.json'
    updates = tmp_path / 'updates.json'
    match.write_text('{"Account":"A"}')
    updates.write_text('{"Stage":"=literal"}')
    assert cli.main(['table', 'plan', 'abc', 'A1:B8', '--sheet-id', '0', '--match-file', str(match), '--updates-file', str(updates)]) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert set(envelope) == {'spreadsheet_id', 'range', 'plan'}
    assert envelope['spreadsheet_id'] == 'abc'
    assert envelope['range'] == 'A1:B8'
    client.read.assert_called_once_with('abc', 'A1:B8', render='FORMULA')
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(envelope))
    client.reset_mock()
    assert cli.main(['table', 'apply', '--plan-file', str(path)]) == 0
    client.read.assert_not_called()
    client.metadata.assert_not_called()
    client.reset_mock()
    assert cli.main(['table', 'apply', '--plan-file', str(path), '--confirm']) == 0
    client.read.assert_called_once_with('abc', 'A1:B8', render='FORMULA')
    assert client.batch.call_args.kwargs['confirm'] is True


@pytest.mark.parametrize('envelope', [None, [], {}, {'spreadsheet_id': 'abc', 'range': 'A1:B8', 'plan': {}, 'extra': True}])
def test_table_envelope_rejected_offline(envelope, client):
    with pytest.raises(cli.SheetsError, match='exactly'):
        cli.table_apply(client, envelope)
    assert not client.mock_calls


def test_table_invalid_range_before_read(client):
    with pytest.raises(cli.SheetsError):
        cli.table_plan(client, 'abc', 'A:B', 0, {'Account': 'A'}, {'Stage': 'new'})
    assert not client.mock_calls


def test_table_append_flags(tmp_path, client, capsys):
    client.metadata.return_value = {'sheets': [{'properties': {'sheetId': 0, 'title': 'Sheet1', 'index': 0}}]}
    client.read.return_value = {'values': [['Account', 'Stage'], ['A', 'old']]}
    match = tmp_path / 'match.json'
    updates = tmp_path / 'updates.json'
    match.write_text('{"Account":"B"}')
    updates.write_text('{"Stage":"new"}')
    assert cli.main(['table', 'plan', 'abc', 'A1:B8', '--sheet-id', '0', '--match-file', str(match), '--updates-file', str(updates), '--allow-append', '--template-row', '2']) == 0
    plan = json.loads(capsys.readouterr().out)['plan']
    assert plan['allow_append'] is True
    assert plan['template_row'] == 2


def test_table_apply_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.auth, 'build_service', lambda: pytest.fail('preview must be offline'))
    plan = cli.plan_table([['Key', 'Value'], ['a', 'old']], 0, 1, {'Key': 'a'}, {'Value': '=literal'})
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps({'spreadsheet_id': 'abc', 'range': 'A1:B10', 'plan': plan}))
    assert cli.main(['table', 'apply', '--plan-file', str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'preview'


def test_table_wrong_tab_before_snapshot(client):
    client.metadata.return_value = {'sheets': [{'properties': {'sheetId': 7, 'title': 'Other', 'index': 0}}]}
    with pytest.raises(cli.SheetsError):
        cli.table_plan(client, 'abc', "'Other'!A1:B10", 0, {'Key': 'a'}, {'Value': 'new'})
    client.read.assert_not_called()
    client.batch.assert_not_called()
