"""Official MCP stdio server with explicit mutation previews."""
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import StrictBool, StrictInt

from .client import SheetsClient
from .cli import tab_requests

mcp = FastMCP('google-sheets', instructions='Read Google Sheets and preview mutations. Set confirm=true only after explicit user authorization. RAW is the default. Never blindly retry uncertain writes.')
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
APPEND = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
BATCH = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)


@mcp.tool(annotations=READ)
def sheets_info(spreadsheet_id: str, ranges: list[str] | None = None, include_grid_data: StrictBool = False) -> dict[str, Any]:
    """Read metadata and tab IDs; optionally inspect grid formatting/validation within specified ranges."""
    if ranges is not None or include_grid_data:
        return SheetsClient().metadata(spreadsheet_id, ranges=ranges, include_grid_data=include_grid_data)
    return SheetsClient().metadata(spreadsheet_id)


@mcp.tool(annotations=READ)
def sheets_read(spreadsheet_id: str, range_name: str, render: Literal['FORMATTED_VALUE', 'UNFORMATTED_VALUE', 'FORMULA'] = 'FORMATTED_VALUE') -> dict[str, Any]:
    """Read cell values in an A1 range."""
    return SheetsClient().read(spreadsheet_id, range_name, render=render)


@mcp.tool(annotations=APPEND)
def sheets_create(title: str, confirm: StrictBool = False) -> dict[str, Any]:
    """Preview creating a spreadsheet; confirm only with user authorization."""
    return SheetsClient().create(title, confirm=confirm)


@mcp.tool(annotations=WRITE)
def sheets_write(spreadsheet_id: str, range_name: str, values: list[list[Any]], input_option: Literal['RAW', 'USER_ENTERED'] = 'RAW', confirm: StrictBool = False) -> dict[str, Any]:
    """Preview replacing cells. USER_ENTERED explicitly enables formula interpretation."""
    return SheetsClient().write(spreadsheet_id, range_name, values, input_option=input_option, confirm=confirm)


@mcp.tool(annotations=APPEND)
def sheets_append(spreadsheet_id: str, range_name: str, values: list[list[Any]], input_option: Literal['RAW', 'USER_ENTERED'] = 'RAW', confirm: StrictBool = False) -> dict[str, Any]:
    """Preview appending rows. Never blindly retry an uncertain append."""
    return SheetsClient().append(spreadsheet_id, range_name, values, input_option=input_option, confirm=confirm)


@mcp.tool(annotations=WRITE)
def sheets_clear(spreadsheet_id: str, range_name: str, confirm: StrictBool = False) -> dict[str, Any]:
    """Preview clearing cell values, preserving formatting."""
    return SheetsClient().clear(spreadsheet_id, range_name, confirm=confirm)


@mcp.tool(annotations=BATCH)
def sheets_batch(spreadsheet_id: str, requests: list[dict[str, Any]], confirm: StrictBool = False) -> dict[str, Any]:
    """Preview Sheets API batchUpdate requests for tabs, formatting, validation, etc. Supply explicit field masks on update requests."""
    return SheetsClient().batch(spreadsheet_id, requests, confirm=confirm)


@mcp.tool(annotations=APPEND)
def sheets_tabs_add(spreadsheet_id: str, title: str, confirm: StrictBool = False) -> dict[str, Any]:
    """Preview adding a tab."""
    return SheetsClient().batch(spreadsheet_id, tab_requests('add', title=title), confirm=confirm)


@mcp.tool(annotations=WRITE)
def sheets_tabs_rename(spreadsheet_id: str, sheet_id: StrictInt, title: str, confirm: StrictBool = False) -> dict[str, Any]:
    """Preview renaming a tab identified by its numeric sheet ID."""
    return SheetsClient().batch(spreadsheet_id, tab_requests('rename', title=title, sheet_id=sheet_id), confirm=confirm)


@mcp.tool(annotations=BATCH)
def sheets_tabs_delete(spreadsheet_id: str, sheet_id: StrictInt, confirm: StrictBool = False) -> dict[str, Any]:
    """Preview permanently deleting a tab and its data."""
    return SheetsClient().batch(spreadsheet_id, tab_requests('delete', sheet_id=sheet_id), confirm=confirm)


def run():
    mcp.run(transport='stdio')


if __name__ == '__main__':
    run()
