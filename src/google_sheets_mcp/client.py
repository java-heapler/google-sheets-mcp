"""Small, preview-first wrapper around the official Sheets API."""
import json
import re

from googleapiclient.errors import HttpError


class SheetsError(Exception):
    """A safe error intended for display to CLI and MCP users."""


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise SheetsError(f'{label} must be nonempty text without control characters.')


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise SheetsError('Use a spreadsheet ID, not a URL.')


def _json(value):
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise SheetsError('Payload must contain finite JSON data.') from None


class SheetsClient:
    def __init__(self, service=None):
        self._service = service

    def _execute(self, kind, method, kwargs, mutation=False):
        try:
            if self._service is None:
                from .auth import build_service
                self._service = build_service()
            resource = self._service.spreadsheets()
            if kind == 'values':
                resource = resource.values()
            result = getattr(resource, method)(**kwargs).execute(num_retries=0)
            return {'status': 'applied', 'result': result} if mutation else result
        except SheetsError:
            raise
        except HttpError as error:
            status = error.resp.status
            reason = {401: 'Authentication expired; run google-sheets auth login.', 403: 'Access denied; check sharing, scope, and Sheets API enablement.', 404: 'Spreadsheet or range not found; check the ID and access.', 429: 'Rate limited; wait before another request.'}.get(status, 'Google Sheets request failed.')
            if mutation:
                reason += ' Inspect the sheet before retrying; the write may have applied.'
            raise SheetsError(f'Google Sheets HTTP {status}: {reason}') from None
        except Exception:
            suffix = ' The write may have applied; inspect the sheet before retrying.' if mutation else ''
            raise SheetsError('Google Sheets request failed.' + suffix) from None

    def _mutate(self, operation, preview, kind, method, kwargs, confirm):
        if not isinstance(confirm, bool):
            raise SheetsError('confirm must be a boolean.')
        if not confirm:
            return {'status': 'preview', 'operation': operation, **preview}
        return self._execute(kind, method, kwargs, mutation=True)

    def metadata(self, spreadsheet_id, ranges=None, include_grid_data=False):
        _id(spreadsheet_id)
        if not isinstance(include_grid_data, bool):
            raise SheetsError('include_grid_data must be a boolean.')
        kwargs = {'spreadsheetId': spreadsheet_id, 'includeGridData': include_grid_data}
        if ranges is not None:
            if not isinstance(ranges, list) or not ranges:
                raise SheetsError('ranges must be a nonempty array of ranges.')
            for range_name in ranges:
                _text(range_name, 'Range')
            kwargs['ranges'] = ranges
        return self._execute('sheets', 'get', kwargs)

    def read(self, spreadsheet_id, range_name, render='FORMATTED_VALUE'):
        _id(spreadsheet_id); _text(range_name, 'Range')
        if render not in ('FORMATTED_VALUE', 'UNFORMATTED_VALUE', 'FORMULA'):
            raise SheetsError('Invalid value render option.')
        return self._execute('values', 'get', {'spreadsheetId': spreadsheet_id, 'range': range_name, 'valueRenderOption': render})

    def create(self, title, confirm=False):
        _text(title, 'Title')
        return self._mutate('create', {'title': title}, 'sheets', 'create', {'body': {'properties': {'title': title}}}, confirm)

    def _values(self, operation, spreadsheet_id, range_name, values, input_option, confirm):
        _id(spreadsheet_id); _text(range_name, 'Range'); _json(values)
        if input_option not in ('RAW', 'USER_ENTERED'):
            raise SheetsError('input_option must be RAW or USER_ENTERED.')
        if not isinstance(values, list) or not values or any(not isinstance(row, list) for row in values):
            raise SheetsError('values must be a nonempty array of row arrays.')
        if any(cell is not None and not isinstance(cell, (str, bool, int, float)) for row in values for cell in row):
            raise SheetsError('Cells must be strings, numbers, booleans, or null.')
        preview = {'spreadsheet_id': spreadsheet_id, 'range': range_name, 'values': values, 'input_option': input_option}
        kwargs = {'spreadsheetId': spreadsheet_id, 'range': range_name, 'valueInputOption': input_option, 'body': {'values': values, 'majorDimension': 'ROWS'}}
        if operation == 'append':
            kwargs['insertDataOption'] = 'INSERT_ROWS'
        return self._mutate(operation, preview, 'values', 'update' if operation == 'write' else 'append', kwargs, confirm)

    def write(self, spreadsheet_id, range_name, values, input_option='RAW', confirm=False):
        return self._values('write', spreadsheet_id, range_name, values, input_option, confirm)

    def append(self, spreadsheet_id, range_name, values, input_option='RAW', confirm=False):
        return self._values('append', spreadsheet_id, range_name, values, input_option, confirm)

    def clear(self, spreadsheet_id, range_name, confirm=False):
        _id(spreadsheet_id); _text(range_name, 'Range')
        return self._mutate('clear', {'spreadsheet_id': spreadsheet_id, 'range': range_name}, 'values', 'clear', {'spreadsheetId': spreadsheet_id, 'range': range_name, 'body': {}}, confirm)

    def batch(self, spreadsheet_id, requests, confirm=False):
        _id(spreadsheet_id); _json(requests)
        if not isinstance(requests, list) or not requests or any(not isinstance(r, dict) or len(r) != 1 for r in requests):
            raise SheetsError('requests must be a nonempty array of single-operation objects.')
        return self._mutate('batch', {'spreadsheet_id': spreadsheet_id, 'requests': requests}, 'sheets', 'batchUpdate', {'spreadsheetId': spreadsheet_id, 'body': {'requests': requests}}, confirm)
