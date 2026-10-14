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
