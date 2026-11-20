"""Non-destructive preflight for Open WebUI-shaped JSON chat exports."""
import copy
import hashlib
import json
from pathlib import Path
import uuid

from . import ROOT
from .engine import run_case
from .model import validate

MARKER = '[NUL]'
ISSUE = 'https://github.com/open-webui/open-webui/issues/15616'
SOURCE = 'https://github.com/open-webui/open-webui/blob/v0.6.15/backend/open_webui/models/chats.py'


def parse(text):
    if len(text.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('Chat input exceeds the 2 MiB preflight limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON keys would make repair ambiguous')
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
    except (RecursionError, UnicodeError):
        raise ValueError('Unsupported JSON encoding or nesting') from None


def chats(document):
    if isinstance(document, list):
        items = document
    elif isinstance(document, dict) and isinstance(document.get('chats'), list):
        items = document['chats']
    elif isinstance(document, dict) and ('chat' in document or 'messages' in document):
        items = [document]
    else:
        raise ValueError('Use a chat object, an array of chat objects, or an object with a chats array')
    if not 1 <= len(items) <= 1000:
        raise ValueError('Preflight supports 1..1000 chat objects')
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Each chat must be an object')
        payload = item.get('chat', item)
        if not isinstance(payload, dict) or not isinstance(payload.get('messages'), list):
            raise ValueError('Each payload must contain a messages array')
        if any(not isinstance(message, dict) for message in payload['messages']):
            raise ValueError('Messages must be objects')
    return items


def preflight(document, repair=False):
    chats(document)
    findings = []
    def pointer(value):
        return str(value).replace('~', '~0').replace('/', '~1')
    def inspect_string(value, path, kind):
        count = value.count('\x00')
        if count:
            findings.append({'path': path or '/', 'kind': kind, 'nul_count': count,
                             'value_sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()})
        return value.replace('\x00', MARKER) if repair else value
    def walk(value, path='', depth=0):
        if depth > 50:
            raise ValueError('Preflight nesting exceeds 50 levels')
        if isinstance(value, str):
            return inspect_string(value, path, 'value')
        if isinstance(value, list):
            return [walk(item, path + '/' + str(index), depth + 1) for index, item in enumerate(value)]
        if isinstance(value, dict):
            output = {}
            for key, item in value.items():
                clean_key = inspect_string(key, path + '/' + pointer(key) + '/@key', 'key')
                if clean_key in output:
                    raise ValueError('Repair would create a JSON key collision; original input was not modified')
                output[clean_key] = walk(item, path + '/' + pointer(key), depth + 1)
            return output
        return value
    output = walk(document)
    return {'input_passes_nul_policy': not findings, 'output_passes_nul_policy': bool(repair or not findings),
            'repair_applied': bool(repair and findings),
            'nul_occurrences': sum(f['nul_count'] for f in findings), 'locations': findings,
            'replacement': MARKER if repair else None, 'document': output}


def as_case(document, search='semax', name='Open WebUI JSON chat search'):
    rows = []
    for index, item in enumerate(chats(document)):
        payload = item.get('chat', item)
        rows.append({'id': 'chat_seed_' + str(index), 'table': 'chat', 'values': {
            'id': 'fixture_' + str(index), 'title': 'Fixture chat ' + str(index),
            'chat': json.dumps(payload, ensure_ascii=False)}})
    return validate({'version': 1, 'name': name, 'tables': [{'name': 'chat', 'columns': [
        {'name': 'id', 'type': 'TEXT', 'primary_key': True}, {'name': 'title', 'type': 'TEXT'},
        {'name': 'chat', 'type': 'JSON'}]}], 'rows': rows, 'operations': [{
            'id': 'search_chat_messages', 'type': 'select', 'table': 'chat', 'columns': ['id', 'title'],
            'where': [{'column': 'chat', 'op': 'json_array_text_contains', 'path': ['messages'],
                       'field': 'content', 'value': search}], 'order_by': [{'column': 'id'}]}]})


def run_preflight(input_path, repair=False, verify=False, output_root=None):
    path = Path(input_path)
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Chat input exceeds 2 MiB')
    document = parse(raw.decode('utf-8'))
    assessment = preflight(document, repair)
    base = (Path(output_root) if output_root else ROOT / 'runs' / 'chat-preflight').resolve()
    if base.drive.lower() != 'd:':
        raise ValueError('Preflight outputs must stay on D:')
    folder = base / uuid.uuid4().hex
    folder.mkdir(parents=True)
    (folder / 'original.json').write_bytes(raw)
    output = folder / ('repaired.json' if repair else 'checked.json')
    output.write_text(json.dumps(assessment['document'], indent=2, ensure_ascii=False), encoding='utf-8')
    audit = {k: v for k, v in assessment.items() if k != 'document'}
    audit.update(source=str(path.resolve()), input_sha256=hashlib.sha256(raw).hexdigest(),
                 output_file=str(output), run_dir=str(folder), policy='Replace actual decoded NUL code points with [NUL]; preserve literal backslash-u text')
    if verify:
        before_case = as_case(document)
        after_case = as_case(assessment['document'], name='Open WebUI chat search after explicit NUL repair')
        before = run_case(before_case, folder / 'verification')
        after = run_case(after_case, folder / 'verification')
        audit['verification'] = {'before_compatible': before['compatible'], 'after_compatible': after['compatible'],
                                 'before_report': str(Path(before['run_dir']) / 'report.json'),
                                 'after_report': str(Path(after['run_dir']) / 'report.json')}
        (folder / 'before-case.json').write_text(json.dumps(before_case, indent=2), encoding='utf-8')
        (folder / 'after-case.json').write_text(json.dumps(after_case, indent=2), encoding='utf-8')
    (folder / 'audit.json').write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding='utf-8')
    return audit


def fixture(count=100):
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError('Fixture count must be 1..1000')
    result = [{'id': 'synthetic_' + str(i), 'title': 'Imported chat ' + str(i), 'chat': {
        'messages': [{'id': 'message_' + str(i), 'role': 'assistant', 'content': 'Unrelated archive note ' + str(i)}],
        'history': {'messages': {}}}} for i in range(count)]
    result[count // 2]['chat']['messages'][0]['content'] = 'semax investigation clue\x00remaining text'
    return result
