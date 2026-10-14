"""Explicit desktop OAuth or service account authentication. Never implicit login."""
import os
from pathlib import Path
import tempfile

import httplib2
import requests
from requests.adapters import HTTPAdapter
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp, Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .client import SheetsError

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
TIMEOUT = 30


class _NoReplayHttp:
    """httplib2-compatible transport without its implicit disconnect replay.

    Sheets writes can succeed before a connection closes. Neither network
    failures, HTTP responses, nor redirects may cause this transport to resend.
    """
    def __init__(self):
        self.timeout = TIMEOUT
        self.session = requests.Session()
        self.session.mount('https://', HTTPAdapter(max_retries=0))
        self.session.mount('http://', HTTPAdapter(max_retries=0))

    def request(self, uri, method='GET', body=None, headers=None,
                redirections=0, connection_type=None):
        with self.session.request(method, uri, data=body, headers=headers,
                                  timeout=self.timeout, allow_redirects=False) as response:
            info = dict(response.headers)
            info['status'] = str(response.status_code)
            return httplib2.Response(info), response.content

    def close(self):
        self.session.close()


class _TimedFlow(InstalledAppFlow):
    def fetch_token(self, **kwargs):
        kwargs.setdefault('timeout', TIMEOUT)
        return super().fetch_token(**kwargs)


def _token_path(token_path=None):
    return Path(token_path or os.environ.get('GOOGLE_SHEETS_TOKEN_FILE') or '~/.config/google-sheets-mcp/token.json').expanduser().absolute()


def _check_token_path(path):
    if path.is_symlink():
        raise SheetsError('Token file must not be a symbolic link.')
    resolved = path.resolve()
    package_root = Path(__file__).resolve().parents[2]
    if package_root in resolved.parents or any((parent / '.git').exists() for parent in resolved.parents):
        raise SheetsError('Store credentials outside source repositories.')


def _save_token(path, content):
    _check_token_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.token-', dir=path.parent)
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def login(client_secrets: str, token_path: str | None = None) -> dict:
    path = _token_path(token_path)
    _check_token_path(path)
    try:
        flow = _TimedFlow.from_client_secrets_file(str(Path(client_secrets).expanduser()), SCOPES, autogenerate_code_verifier=True)
        credentials = flow.run_local_server(host='127.0.0.1', port=0, authorization_prompt_message='', timeout_seconds=180, access_type='offline', prompt='consent')
        _save_token(path, credentials.to_json())
        return {'status': 'authenticated', 'token_file': str(path)}
    except SheetsError:
        raise
    except Exception:
        raise SheetsError('OAuth login failed. Check the desktop OAuth client configuration and try again.') from None


def build_service():
    try:
        service_file = os.environ.get('GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE')
        http = _NoReplayHttp()
        if service_file:
            credentials = service_account.Credentials.from_service_account_file(str(Path(service_file).expanduser()), scopes=SCOPES)
            credentials.refresh(Request(http))
        else:
            path = _token_path()
            _check_token_path(path)
            if not path.is_file():
                raise SheetsError('No OAuth token configured; run google-sheets auth login first.')
            if path.stat().st_mode & 0o077:
                raise SheetsError('OAuth token permissions must be 0600; restrict access before continuing.')
            credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
            if not credentials.valid:
                if not credentials.refresh_token:
                    raise SheetsError('OAuth credentials need renewal; run google-sheets auth login.')
                credentials.refresh(Request(http))
                _save_token(path, credentials.to_json())
        authorized = AuthorizedHttp(credentials, http=http, max_refresh_attempts=0)
        return build('sheets', 'v4', http=authorized, cache_discovery=False, static_discovery=True, num_retries=0)
    except SheetsError:
        raise
    except Exception:
        raise SheetsError('Google Sheets authentication failed. Check credentials or run google-sheets auth login.') from None


def doctor() -> dict:
    """Local configuration inspection; does not refresh credentials or use network."""
    service_file = os.environ.get('GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE')
    path = Path(service_file).expanduser() if service_file else _token_path()
    present = path.is_file()
    secure = present and not path.is_symlink() and not (path.stat().st_mode & 0o077)
    return {'authenticated': False, 'credential_file_present': present, 'credential_file_private': secure, 'auth_mode': 'service_account' if service_file else 'oauth', 'network_checked': False, 'message': 'Credentials configured; access has not been verified.' if present else 'Run google-sheets auth login to configure credentials.'}
