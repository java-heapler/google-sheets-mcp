"""Exercise actual SDK transports without granting access to any Google account."""
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlsplit

import httplib2
from googleapiclient.discovery import build
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest

from google_sheets_mcp.client import SheetsClient
from google_sheets_mcp.tables import plan_table


def test_real_stdio_initialization_discovery_and_offline_preview(tmp_path):
    async def scenario():
        env = dict(os.environ)
        for key in ('GOOGLE_SHEETS_TOKEN_FILE', 'GOOGLE_SHEETS_CLIENT_SECRET_FILE', 'GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE'):
            env[key] = str(tmp_path / 'nonexistent-credentials.json')
        server = StdioServerParameters(command=sys.executable, args=['-m', 'google_sheets_mcp.cli', 'mcp'], env=env)
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.capabilities.tools is not None
                listing = await session.list_tools()
                tools = {tool.name: tool for tool in listing.tools}
                assert {'sheets_write', 'sheets_batch', 'sheets_read', 'sheets_table_plan', 'sheets_table_apply'} <= tools.keys()
                assert tools['sheets_write'].inputSchema['properties']['confirm']['default'] is False
                assert tools['sheets_read'].annotations.readOnlyHint is True
                assert tools['sheets_table_plan'].annotations.readOnlyHint is True
                assert tools['sheets_table_apply'].inputSchema['properties']['confirm']['default'] is False
                result = await session.call_tool('sheets_write', {'spreadsheet_id': 'offline-sheet', 'range_name': "'Test tab'!A1", 'values': [['=1+2']]})
                assert not result.isError
                preview = json.loads(result.content[0].text)
                assert preview['status'] == 'preview'
                assert preview['values'] == [['=1+2']]
                assert preview['input_option'] == 'RAW'
                batch = await session.call_tool('sheets_batch', {'spreadsheet_id': 'offline-sheet', 'requests': [{'addSheet': {'properties': {'title': 'Offline'}}}]})
                assert not batch.isError
                assert json.loads(batch.content[0].text)['status'] == 'preview'
                invalid = await session.call_tool('sheets_write', {'spreadsheet_id': 'https://invalid.test/sheet', 'range_name': 'A1', 'values': [[1]]})
                assert invalid.isError
                table_plan = plan_table(
                    [['SKU', 'Quantity', 'Notes'], ['00123', 4, 'Keep collaborator text']],
                    123, 1, {'SKU': '00123'}, {'Quantity': 5})
                envelope = {'spreadsheet_id': 'offline-sheet', 'range': "'Inventory'!A1:C10", 'plan': table_plan}
                table = await session.call_tool('sheets_table_apply', {'plan': envelope})
                assert not table.isError
                table_preview = json.loads(table.content[0].text)
                assert table_preview['status'] == 'preview'
                assert table_preview['plan']['requests'] == table_plan['requests']
                assert len(table_preview['plan']['requests']) == 1
                assert table_preview['plan']['requests'][0]['updateCells']['start']['columnIndex'] == 1
                invalid_confirm = await session.call_tool('sheets_table_apply', {'plan': envelope, 'confirm': 'false'})
                assert invalid_confirm.isError
                table_plan['requests'][0]['updateCells']['start']['columnIndex'] = 2
                tampered = await session.call_tool('sheets_table_apply', {'plan': envelope})
                assert tampered.isError
                assert not Path(env['GOOGLE_SHEETS_TOKEN_FILE']).exists()

    async def bounded():
        await asyncio.wait_for(scenario(), timeout=30)

    asyncio.run(bounded())


class RecordingHttp:
    """Capture serialized requests produced by Google's real discovery resource."""

    def __init__(self):
        self.requests = []

    def request(self, uri, method='GET', body=None, headers=None, **kwargs):
        self.requests.append((uri, method, json.loads(body) if body else None))
        return httplib2.Response({'status': '200', 'content-type': 'application/json'}), b'{"verified":true}'


@pytest.fixture
def discovery_client():
    transport = RecordingHttp()
    service = build('sheets', 'v4', http=transport, static_discovery=True, cache_discovery=False)
    return SheetsClient(service=service), transport


@pytest.mark.parametrize('operation,method,suffix,input_option', [
    ('write', 'PUT', '', 'RAW'),
    ('append', 'POST', ':append', 'USER_ENTERED'),
])
def test_official_discovery_values_serialization(discovery_client, operation, method, suffix, input_option):
    client, transport = discovery_client
    values = [['=SUM(A1:A2)', 2, True, None]]
    result = getattr(client, operation)('sheet_123', "'Test tab'!A1:D1", values, input_option=input_option, confirm=True)
    assert result == {'status': 'applied', 'result': {'verified': True}}
    assert len(transport.requests) == 1
    uri, actual_method, body = transport.requests[0]
    parsed = urlsplit(uri)
    assert parsed.scheme == 'https'
    assert parsed.netloc == 'sheets.googleapis.com'
    assert unquote(parsed.path) == "/v4/spreadsheets/sheet_123/values/'Test tab'!A1:D1" + suffix
    assert actual_method == method
    assert parse_qs(parsed.query)['valueInputOption'] == [input_option]
    if operation == 'append':
        assert parse_qs(parsed.query)['insertDataOption'] == ['INSERT_ROWS']
    assert body == {'values': values, 'majorDimension': 'ROWS'}


def test_official_discovery_batch_serialization(discovery_client):
    client, transport = discovery_client
    requests = [
        {'addSheet': {'properties': {'sheetId': 123, 'title': 'Test'}}},
        {'updateSheetProperties': {'properties': {'sheetId': 123, 'title': 'Renamed'}, 'fields': 'title'}},
        {'repeatCell': {'range': {'sheetId': 123, 'startRowIndex': 0, 'endRowIndex': 1}, 'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat.bold'}},
        {'setDataValidation': {'range': {'sheetId': 123, 'startColumnIndex': 1, 'endColumnIndex': 2}, 'rule': {'condition': {'type': 'ONE_OF_LIST', 'values': [{'userEnteredValue': 'Done'}]}, 'strict': True}}},
        {'deleteSheet': {'sheetId': 123}},
    ]
    assert client.batch('sheet_123', requests)['status'] == 'preview'
    assert transport.requests == []
    assert client.batch('sheet_123', requests, confirm=True)['status'] == 'applied'
    assert len(transport.requests) == 1
    uri, method, body = transport.requests[0]
    parsed = urlsplit(uri)
    assert parsed.netloc == 'sheets.googleapis.com'
    assert parsed.path == '/v4/spreadsheets/sheet_123:batchUpdate'
    assert method == 'POST'
    assert body == {'requests': requests}
