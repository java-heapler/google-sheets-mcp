from unittest.mock import MagicMock
import pytest
from google_sheets_mcp.client import SheetsClient, SheetsError

@pytest.fixture
def service():
    s = MagicMock()
    for name in ('get', 'create', 'batchUpdate'):
        getattr(s.spreadsheets(), name)().execute.return_value = {'ok': True}
    for name in ('get', 'update', 'append', 'clear'):
        getattr(s.spreadsheets().values(), name)().execute.return_value = {'ok': True}
    return s

@pytest.mark.parametrize('op,args', [('create', ['Title']), ('write', ['abc', 'A1', [[1]]]), ('append', ['abc', 'A1', [[1]]]), ('clear', ['abc', 'A1']), ('batch', ['abc', [{'addSheet': {}}]])])
def test_preview_and_apply(service, op, args):
    c = SheetsClient(service)
    service.reset_mock()
    assert getattr(c, op)(*args)['status'] == 'preview'
    service.assert_not_called()
    assert not service.mock_calls
    assert getattr(c, op)(*args, confirm=True) == {'status': 'applied', 'result': {'ok': True}}
    executes = [call for call in service.mock_calls if call[0].endswith('execute')]
    assert executes[-1].kwargs == {'num_retries': 0}

@pytest.mark.parametrize('op,args,kwargs', [
    ('metadata', ['https://example.com'], {}), ('read', ['abc', ''], {}),
    ('read', ['abc', 'A1'], {'render': 'BAD'}), ('create', [' '], {}),
    ('write', ['abc','A1', [[float('nan')]]], {}), ('write', ['abc','A1', [[{}]]], {}),
    ('write', ['abc','A1', [1]], {}), ('write', ['abc','A1', []], {}),
    ('write', ['abc','A1', [[1]]], {'input_option':'bad'}),
    ('batch', ['abc', []], {}), ('batch', ['abc', [1]], {}),
    ('batch', ['abc', [{'x':float('inf')}]], {}), ('clear', ['abc','A1'], {'confirm':'true'}),
])
def test_invalid_without_network(op,args,kwargs,service):
    service.reset_mock()
    with pytest.raises(SheetsError): getattr(SheetsClient(service),op)(*args,**kwargs)
    assert not service.mock_calls

def test_read(service):
    c = SheetsClient(service)
    assert c.metadata('abc') == {'ok':True}
    assert c.read('abc', "'My Tab'!A1:B2", 'UNFORMATTED_VALUE') == {'ok':True}
    service.spreadsheets().values().get.assert_called_with(spreadsheetId='abc',range="'My Tab'!A1:B2",valueRenderOption='UNFORMATTED_VALUE')

def test_lazy_and_safe_error(monkeypatch,service):
    from google_sheets_mcp import auth
    build = MagicMock(return_value=service)
    monkeypatch.setattr(auth,'build_service',build)
    c=SheetsClient(); c.create('Local'); build.assert_not_called()
    service.spreadsheets().get().execute.side_effect = RuntimeError('TOP_SECRET')
    with pytest.raises(SheetsError,match='request failed') as e: c.metadata('abc')
    assert 'TOP_SECRET' not in str(e.value)
    build.assert_called_once()

@pytest.mark.parametrize('status', [401,403,404,429,500])
def test_http_errors_safe(service,status):
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    service.spreadsheets().create().execute.side_effect=HttpError(Response({'status':status}), b'{"error":{"message":"TOP_SECRET"}}')
    with pytest.raises(SheetsError) as exc:
        SheetsClient(service).create('Title',confirm=True)
    assert str(status) in str(exc.value)
    assert 'TOP_SECRET' not in str(exc.value)
    assert 'before retrying' in str(exc.value)

def test_auth_errors_passthrough(monkeypatch):
    from google_sheets_mcp import auth
    monkeypatch.setattr(auth,'build_service',MagicMock(side_effect=SheetsError('safe error')))
    with pytest.raises(SheetsError,match='safe error'): SheetsClient().metadata('abc')

def test_grid_metadata(service):
    SheetsClient(service).metadata('abc',ranges=['A1:B5'],include_grid_data=True)
    service.spreadsheets().get.assert_called_with(spreadsheetId='abc',ranges=['A1:B5'],includeGridData=True)

@pytest.mark.parametrize('kwargs',[{'ranges':[]},{'ranges':'A1'},{'ranges':['']},{'include_grid_data':'true'}])
def test_grid_metadata_validation(service,kwargs):
    service.reset_mock()
    with pytest.raises(SheetsError): SheetsClient(service).metadata('abc',**kwargs)
    assert not service.mock_calls

def test_http_read_error(service):
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    service.spreadsheets().get().execute.side_effect=HttpError(Response({'status':404}), b'private error')
    with pytest.raises(SheetsError,match='not found') as exc:
        SheetsClient(service).metadata('abc')
    assert 'write may' not in str(exc.value)

def test_append_inserts_rows(service):
    SheetsClient(service).append('abc','A1',[[1]],confirm=True)
    service.spreadsheets().values().append.assert_called_with(spreadsheetId='abc',range='A1',valueInputOption='RAW',body={'values':[[1]],'majorDimension':'ROWS'},insertDataOption='INSERT_ROWS')
