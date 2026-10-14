import asyncio
from unittest.mock import Mock

from google_sheets_mcp import mcp_server


def test_tools_and_annotations():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    indexed = {tool.name: tool for tool in tools}
    assert set(indexed) == {'sheets_info', 'sheets_read', 'sheets_create', 'sheets_write', 'sheets_append', 'sheets_clear', 'sheets_batch', 'sheets_tabs_add', 'sheets_tabs_rename', 'sheets_tabs_delete'}
    for name, tool in indexed.items():
        readonly = name in {'sheets_info', 'sheets_read'}
        assert tool.annotations.readOnlyHint is readonly
        if not readonly:
            assert tool.inputSchema['properties']['confirm']['default'] is False
    assert indexed['sheets_append'].annotations.idempotentHint is False
    assert indexed['sheets_clear'].annotations.destructiveHint is True


def test_mcp_preview_and_forwarding(monkeypatch):
    client = Mock()
    client.write.return_value = {'status': 'preview'}
    monkeypatch.setattr(mcp_server, 'SheetsClient', lambda: client)
    assert mcp_server.sheets_write('abc', 'A1', [[1]]) == {'status': 'preview'}
    client.write.assert_called_once_with('abc', 'A1', [[1]], input_option='RAW', confirm=False)
    mcp_server.sheets_info('abc')
    mcp_server.sheets_read('abc', 'A1')
    mcp_server.sheets_create('Title')
    mcp_server.sheets_append('abc', 'A1', [[1]], confirm=True)
    mcp_server.sheets_clear('abc', 'A1')
    mcp_server.sheets_batch('abc', [{'addSheet': {}}])
    mcp_server.sheets_tabs_add('abc', 'New')
    mcp_server.sheets_tabs_rename('abc', 2, 'Renamed')
    mcp_server.sheets_tabs_delete('abc', 2)
    client.batch.assert_called_with('abc', [{'deleteSheet': {'sheetId': 2}}], confirm=False)


def test_stdio_run(monkeypatch):
    run = Mock()
    monkeypatch.setattr(mcp_server.mcp, 'run', run)
    mcp_server.run()
    run.assert_called_once_with(transport='stdio')


def test_metadata_grid_arguments(monkeypatch):
    client = Mock()
    monkeypatch.setattr(mcp_server, 'SheetsClient', lambda: client)
    mcp_server.sheets_info('abc', ['A1'], True)
    client.metadata.assert_called_once_with('abc', ranges=['A1'], include_grid_data=True)


def test_empty_ranges_rejected_before_credentials(monkeypatch):
    import pytest
    from google_sheets_mcp import auth
    from google_sheets_mcp.client import SheetsError
    monkeypatch.setattr(auth, 'build_service', lambda: pytest.fail('must validate before authentication'))
    with pytest.raises(SheetsError, match='nonempty array'):
        mcp_server.sheets_info('abc', ranges=[])


def test_module_entrypoint(monkeypatch):
    import runpy
    from mcp.server.fastmcp import FastMCP
    called = []
    monkeypatch.setattr(FastMCP, 'run', lambda self, **kwargs: called.append(kwargs))
    import sys
    monkeypatch.delitem(sys.modules, 'google_sheets_mcp.mcp_server', raising=False)
    runpy.run_module('google_sheets_mcp.mcp_server', run_name='__main__')
    assert called == [{'transport': 'stdio'}]


def test_mcp_rejects_coerced_flags_and_ids(monkeypatch):
    import pytest
    from mcp.server.fastmcp.exceptions import ToolError
    monkeypatch.setattr(mcp_server, 'SheetsClient', lambda: pytest.fail('invalid arguments must not reach the client'))
    cases = [
        ('sheets_tabs_delete', {'spreadsheet_id': 'abc', 'sheet_id': True}),
        ('sheets_tabs_delete', {'spreadsheet_id': 'abc', 'sheet_id': '0'}),
        ('sheets_create', {'title': 'Preview', 'confirm': 'false'}),
        ('sheets_create', {'title': 'Preview', 'confirm': 1}),
        ('sheets_info', {'spreadsheet_id': 'abc', 'include_grid_data': 'true'}),
    ]
    async def check():
        for name, arguments in cases:
            with pytest.raises(ToolError, match='validation error'):
                await mcp_server.mcp.call_tool(name, arguments)
    asyncio.run(check())
