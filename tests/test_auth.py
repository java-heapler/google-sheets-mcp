import json
import os
from unittest.mock import MagicMock
import pytest
from google_sheets_mcp import auth
from google_sheets_mcp.client import SheetsError

@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    for name in ('GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE','GOOGLE_SHEETS_CLIENT_SECRET_FILE'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('GOOGLE_SHEETS_TOKEN_FILE',str(tmp_path/'token.json'))

def test_doctor_no_network():
    assert auth.doctor()['authenticated'] is False
    with pytest.raises(SheetsError,match='auth login'): auth.build_service()

def test_secure_save(tmp_path):
    p=tmp_path/'nested'/'token.json'
    auth._save_token(p,'{"token":"secret"}')
    assert p.stat().st_mode & 0o777 == 0o600
    assert json.loads(p.read_text())['token']=='secret'

def test_symlink_rejected(tmp_path):
    target=tmp_path/'target'; target.write_text('keep')
    p=tmp_path/'token'; p.symlink_to(target)
    with pytest.raises(SheetsError): auth._save_token(p,'secret')
    assert target.read_text()=='keep'

def test_login(monkeypatch,tmp_path):
    flow=MagicMock(); flow.run_local_server.return_value.to_json.return_value='{}'
    factory=MagicMock(return_value=flow)
    monkeypatch.setattr(auth.InstalledAppFlow,'from_client_secrets_file',factory)
    assert auth.login('client.json')['status']=='authenticated'
    assert factory.call_args.kwargs['autogenerate_code_verifier'] is True
    assert flow.run_local_server.call_args.kwargs['host']=='127.0.0.1'
    assert flow.run_local_server.call_args.kwargs['authorization_prompt_message']==''

def test_login_safe_failure(monkeypatch):
    monkeypatch.setattr(auth.InstalledAppFlow,'from_client_secrets_file',MagicMock(side_effect=ValueError('secret')))
    with pytest.raises(SheetsError) as e: auth.login('client.json')
    assert 'secret' not in str(e.value)

def test_build_oauth(monkeypatch,tmp_path):
    p=tmp_path/'token.json'; p.write_text('{}'); p.chmod(0o600)
    creds=MagicMock(valid=True,expired=False)
    monkeypatch.setattr(auth.Credentials,'from_authorized_user_file',MagicMock(return_value=creds))
    build=MagicMock(); monkeypatch.setattr(auth,'build',build)
    auth.build_service()
    assert build.call_args.kwargs['num_retries']==0
    assert build.call_args.kwargs['http'].http.timeout==30
    assert build.call_args.kwargs['http']._max_refresh_attempts==0

def test_service_account(monkeypatch,tmp_path):
    monkeypatch.setenv('GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE',str(tmp_path/'sa.json'))
    factory=MagicMock(return_value=MagicMock())
    monkeypatch.setattr(auth.service_account.Credentials,'from_service_account_file',factory)
    monkeypatch.setattr(auth,'build',MagicMock())
    auth.build_service(); factory.assert_called_once()

def test_permissions(monkeypatch,tmp_path):
    p=tmp_path/'token.json'; p.write_text('{}'); p.chmod(0o644)
    with pytest.raises(SheetsError,match='0600'): auth.build_service()
    assert auth.doctor()['credential_file_private'] is False

@pytest.mark.parametrize('refresh_token', ['token', None])
def test_refresh(monkeypatch,tmp_path,refresh_token):
    p=tmp_path/'token.json'; p.write_text('{}'); p.chmod(0o600)
    creds=MagicMock(valid=False,refresh_token=refresh_token)
    creds.to_json.return_value='{}'
    monkeypatch.setattr(auth.Credentials,'from_authorized_user_file',MagicMock(return_value=creds))
    monkeypatch.setattr(auth,'build',MagicMock())
    if refresh_token:
        auth.build_service()
        assert creds.refresh.call_args.args[0].http.timeout==30
    else:
        with pytest.raises(SheetsError,match='renewal'): auth.build_service()

def test_bad_credentials(monkeypatch,tmp_path):
    monkeypatch.setenv('GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE',str(tmp_path/'missing'))
    with pytest.raises(SheetsError,match='authentication failed'): auth.build_service()

def test_repository_token_rejected(tmp_path):
    (tmp_path/'.git').mkdir()
    with pytest.raises(SheetsError,match='outside source'): auth.login('client',str(tmp_path/'token.json'))

def test_login_save_error(monkeypatch):
    flow=MagicMock()
    monkeypatch.setattr(auth.InstalledAppFlow,'from_client_secrets_file',MagicMock(return_value=flow))
    monkeypatch.setattr(auth,'_save_token',MagicMock(side_effect=SheetsError('safe')))
    with pytest.raises(SheetsError,match='safe'): auth.login('client')

def test_login_token_timeout(monkeypatch):
    fetch=MagicMock(return_value={'token':'secret'})
    monkeypatch.setattr(auth.InstalledAppFlow,'fetch_token',fetch)
    assert auth._TimedFlow.fetch_token(object.__new__(auth._TimedFlow),code='fake')=={'token':'secret'}
    assert fetch.call_args.kwargs['timeout']==30

def test_save_cleanup_on_failure(monkeypatch,tmp_path):
    monkeypatch.setattr(auth.os,'replace',MagicMock(side_effect=OSError('failed')))
    with pytest.raises(OSError): auth._save_token(tmp_path/'token','{}')
    assert list(tmp_path.iterdir())==[]

@pytest.mark.parametrize('response_status', [None, 200, 307, 401, 503])
def test_transport_never_replays_post(response_status):
    """A real loopback server records complete POST bodies before losing replies."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from google.auth.credentials import AnonymousCredentials
    from googleapiclient.http import HttpRequest
    import requests
    from googleapiclient.errors import HttpError

    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers['Content-Length'])))
            if response_status is None:
                self.close_connection = True
                return
            self.send_response(response_status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Location', '/redirect-target')
            self.end_headers()
            self.wfile.write(b'{}')
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval':0.01}, daemon=True)
    thread.start()
    transport = auth._NoReplayHttp()
    authorized = auth.AuthorizedHttp(AnonymousCredentials(), http=transport, max_refresh_attempts=0)
    request = HttpRequest(authorized, lambda response, body: body,
                          f'http://127.0.0.1:{server.server_port}/sheets',
                          method='POST', body='{"write":true}', headers={'Content-Type':'application/json'})
    try:
        if response_status is None:
            with pytest.raises(requests.exceptions.ConnectionError): request.execute(num_retries=0)
        elif response_status >= 300:
            with pytest.raises(HttpError): request.execute(num_retries=0)
        else:
            assert request.execute(num_retries=0) == b'{}'
        assert received == [b'{"write":true}']
        assert transport.timeout == 30
        assert transport.session.get_adapter('https://').max_retries.total == 0
    finally:
        authorized.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
