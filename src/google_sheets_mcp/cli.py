"""JSON CLI for Google Sheets. Mutations preview unless explicitly confirmed."""
import argparse
import json
import sys
from pathlib import Path

from . import auth
from .client import SheetsClient, SheetsError
from .tables import apply_table, plan_table, validate_table_range, validate_table_target

MAX_JSON_BYTES = 2 * 1024 * 1024


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SheetsError('Invalid command arguments. Use --help for usage.')


def _reject_constant(value):
    raise ValueError('Nonfinite JSON')


def load_json(path):
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise SheetsError('JSON file exceeds the 2 MiB limit.')
        return json.loads(data, parse_constant=_reject_constant)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise SheetsError('Cannot read a valid finite JSON file.') from None


def tab_requests(action, title=None, sheet_id=None):
    if action in ('add', 'rename') and (not isinstance(title, str) or not title.strip()):
        raise SheetsError('A nonempty tab title is required.')
    if action in ('rename', 'delete') and (type(sheet_id) is not int or sheet_id < 0):
        raise SheetsError('Tab ID must be a nonnegative integer.')
    if action == 'add':
        return [{'addSheet': {'properties': {'title': title}}}]
    if action == 'rename':
        return [{'updateSheetProperties': {'properties': {'sheetId': sheet_id, 'title': title}, 'fields': 'title'}}]
    return [{'deleteSheet': {'sheetId': sheet_id}}]


def table_plan(client, spreadsheet_id, range_name, sheet_id, match, updates, allow_append=False, template_row=None):
    """Read a bounded snapshot and return a target-bound, locally checked plan."""
    start_row, _, _ = validate_table_range(range_name)
    validate_table_target(client, spreadsheet_id, range_name, sheet_id)
    snapshot = client.read(spreadsheet_id, range_name, render='FORMULA')
    plan = plan_table(snapshot.get('values', []), sheet_id, start_row, match, updates,
                      allow_append=allow_append, template_row=template_row)
    apply_table(client, spreadsheet_id, range_name, plan)
    return {'spreadsheet_id': spreadsheet_id, 'range': range_name, 'plan': plan}


def table_apply(client, envelope, confirm=False):
    """Apply only to the target persisted in the plan artifact."""
    if not isinstance(envelope, dict) or set(envelope) != {'spreadsheet_id', 'range', 'plan'}:
        raise SheetsError('Table plan must contain exactly spreadsheet_id, range, and plan.')
    return apply_table(client, envelope['spreadsheet_id'], envelope['range'], envelope['plan'], confirm=confirm)


def parser():
    root = Parser(prog='google-sheets', description=__doc__)
    commands = root.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    commands.add_parser('mcp')
    agent = commands.add_parser('agent').add_subparsers(dest='agent_command', required=True)
    agent.add_parser('schema')
    agent.add_parser('guide')
    login = commands.add_parser('auth').add_subparsers(dest='auth_command', required=True).add_parser('login')
    login.add_argument('--client-secrets', required=True)
    login.add_argument('--token-file')
    for name in ('info', 'read', 'create', 'write', 'append', 'clear', 'batch'):
        cmd = commands.add_parser(name)
        cmd.add_argument('title' if name == 'create' else 'spreadsheet_id')
        if name in ('read', 'write', 'append', 'clear'):
            cmd.add_argument('range_name')
        if name == 'info':
            cmd.add_argument('--range', dest='ranges', action='append')
            cmd.add_argument('--include-grid-data', action='store_true')
        if name == 'read':
            cmd.add_argument('--render', choices=['FORMATTED_VALUE', 'UNFORMATTED_VALUE', 'FORMULA'], default='FORMATTED_VALUE')
        if name in ('write', 'append'):
            cmd.add_argument('--values-file', required=True)
            cmd.add_argument('--input-option', choices=['RAW', 'USER_ENTERED'], default='RAW')
        if name == 'batch':
            cmd.add_argument('--requests-file', required=True)
        if name not in ('info', 'read'):
            cmd.add_argument('--confirm', action='store_true')
    table = commands.add_parser('table').add_subparsers(dest='table_action', required=True)
    plan = table.add_parser('plan', help='Read a bounded FORMULA snapshot and produce a plan (network read).')
    plan.add_argument('spreadsheet_id')
    plan.add_argument('range_name')
    plan.add_argument('--sheet-id', type=int, required=True)
    plan.add_argument('--match-file', required=True)
    plan.add_argument('--updates-file', required=True)
    plan.add_argument('--allow-append', action='store_true')
    plan.add_argument('--template-row', type=int)
    apply = table.add_parser('apply', help='Preview a saved plan offline; confirm rereads before writing.')
    apply.add_argument('--plan-file', required=True)
    apply.add_argument('--confirm', action='store_true')
    tabs = commands.add_parser('tabs').add_subparsers(dest='tab_action', required=True)
    for name in ('add', 'rename', 'delete'):
        cmd = tabs.add_parser(name)
        cmd.add_argument('spreadsheet_id')
        if name != 'add':
            cmd.add_argument('sheet_id', type=int)
        if name != 'delete':
            cmd.add_argument('title')
        cmd.add_argument('--confirm', action='store_true')
    return root


def dispatch(args):
    if args.command == 'agent':
        if args.agent_command == 'guide':
            return {'steps': ['Run doctor; explicitly run auth login if needed.', 'Use info to inspect tab IDs and read to inspect values.', 'Preview a mutation, inspect the exact request, then use --confirm only with user authorization.', 'Never blindly retry a write after an uncertain failure.'], 'defaults': {'input_option': 'RAW', 'confirm': False}, 'json_file_limit_bytes': MAX_JSON_BYTES}
        import asyncio
        from .mcp_server import mcp
        return {'tools': [tool.model_dump(mode='json', exclude_none=True) for tool in asyncio.run(mcp.list_tools())], 'cli': parser().format_help()}
    if args.command == 'doctor':
        return auth.doctor()
    if args.command == 'auth':
        return auth.login(args.client_secrets, token_path=args.token_file)
    if args.command == 'mcp':
        from .mcp_server import run
        run()
        return None
    client = SheetsClient()
    if args.command == 'table':
        if args.table_action == 'plan':
            return table_plan(client, args.spreadsheet_id, args.range_name, args.sheet_id,
                              load_json(args.match_file), load_json(args.updates_file),
                              allow_append=args.allow_append, template_row=args.template_row)
        return table_apply(client, load_json(args.plan_file), confirm=args.confirm)
    if args.command == 'info':
        if args.ranges or args.include_grid_data:
            return client.metadata(args.spreadsheet_id, ranges=args.ranges, include_grid_data=args.include_grid_data)
        return client.metadata(args.spreadsheet_id)
    if args.command == 'read':
        return client.read(args.spreadsheet_id, args.range_name, render=args.render)
    if args.command == 'create':
        return client.create(args.title, confirm=args.confirm)
    if args.command in ('write', 'append'):
        return getattr(client, args.command)(args.spreadsheet_id, args.range_name, load_json(args.values_file), input_option=args.input_option, confirm=args.confirm)
    if args.command == 'clear':
        return client.clear(args.spreadsheet_id, args.range_name, confirm=args.confirm)
    requests = load_json(args.requests_file) if args.command == 'batch' else tab_requests(args.tab_action, getattr(args, 'title', None), getattr(args, 'sheet_id', None))
    return client.batch(args.spreadsheet_id, requests, confirm=args.confirm)


def main(argv=None):
    try:
        result = dispatch(parser().parse_args(argv))
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except SheetsError as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({'error': 'Operation failed. Check configuration and permissions; do not blindly retry writes.'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
