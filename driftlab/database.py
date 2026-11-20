"""Isolated adapters with real transactions and bounded PostgreSQL statements."""
import json
import os
import sqlite3
import uuid

from . import ROOT
from .sql import quote, schema, operation


def configured():
    return bool(os.environ.get('DRIFTLAB_DATABASE_URL') or (ROOT / '.secrets' / 'postgres.json').is_file())


def connect_postgres():
    import psycopg
    try:
        dsn = os.environ.get('DRIFTLAB_DATABASE_URL')
        if dsn:
            return psycopg.connect(dsn, autocommit=True, connect_timeout=5)
        settings = json.loads((ROOT / '.secrets' / 'postgres.json').read_text())
        return psycopg.connect(**settings, autocommit=True, connect_timeout=5)
    except Exception:
        raise RuntimeError('Cannot connect to PostgreSQL; check its server and private configuration') from None


def error_info(error):
    message = str(error).split('\n')[0][:300]
    lower = message.lower()
    code = getattr(error, 'sqlstate', None)
    categories = {'23505': 'unique', '23502': 'not_null', '23503': 'foreign_key',
                  '22P02': 'datatype', '22003': 'numeric_range', '22021': 'encoding', '22P05': 'encoding'}
    category = categories.get(code)
    if category is None:
        if 'unique constraint' in lower:
            category = 'unique'
        elif 'not null constraint' in lower:
            category = 'not_null'
        elif 'foreign key constraint' in lower:
            category = 'foreign_key'
        elif 'cannot store' in lower or 'datatype mismatch' in lower:
            category = 'datatype'
        elif 'nul' in lower and any(word in lower for word in ('character', 'string', 'text', 'bytes')):
            category = 'encoding'
        else:
            category = 'database_error'
    return {'category': category, 'message': message, 'code': code or getattr(error, 'sqlite_errorname', None)}


class Adapter:
    def __init__(self, engine, case, folder):
        self.engine, self.case = engine, case
        self.namespace, self.created, self.connection = None, False, None
        try:
            if engine == 'sqlite':
                self.connection = sqlite3.connect(folder / 'sqlite.db', isolation_level=None)
                self.connection.execute('PRAGMA foreign_keys=' + ('ON' if case['sqlite']['foreign_keys'] else 'OFF'))
                self.version = sqlite3.sqlite_version
            else:
                self.connection = connect_postgres()
                self.namespace = 'drift_' + uuid.uuid4().hex
                self.connection.execute('SET statement_timeout = 2000').close()
                self.connection.execute('SET lock_timeout = 1000').close()
                self.version = self.connection.execute('SHOW server_version').fetchone()[0]
                self.connection.execute('CREATE SCHEMA ' + quote(self.namespace)).close()
                self.created = True
                self.connection.execute('SET search_path TO ' + quote(self.namespace)).close()
            for statement in schema(case, engine):
                self.connection.execute(statement).close()
        except BaseException:
            self.close()
            raise

    def step(self, op, source):
        statement, parameters = operation(op, self.engine)
        result = {'id': op['id'], 'source': source, 'type': op['type'], 'table': op['table'],
                  'sql': statement, 'parameters': parameters}
        try:
            self.connection.execute('BEGIN').close()
            cursor = self.connection.execute(statement, parameters)
            rows = self.normalize_rows(op['table'], op['columns'], cursor.fetchall()) if op['type'] == 'select' else None
            count = cursor.rowcount
            cursor.close()
            self.connection.execute('COMMIT').close()
            result.update(accepted=True, rows=rows, affected_rows=count if rows is None else None)
        except Exception as error:
            self.connection.execute('ROLLBACK').close()
            detail = error_info(error)
            if self.engine == 'postgres' and not getattr(error, 'sqlstate', None) and detail['category'] != 'encoding':
                raise RuntimeError('PostgreSQL driver/infrastructure failure; this is not a compatibility finding') from error
            if self.engine == 'sqlite' and isinstance(error, sqlite3.ProgrammingError):
                raise RuntimeError('SQLite driver failure; this is not a compatibility finding') from error
            result.update(accepted=False, error=detail)
        return result

    def normalize_rows(self, table, columns, rows):
        types = {c['name']: c['type'] for t in self.case['tables'] if t['name'] == table for c in t['columns']}
        result = []
        for row in rows:
            values = list(row)
            for index, column in enumerate(columns):
                if types[column] == 'JSON' and values[index] is not None and self.engine == 'sqlite':
                    values[index] = json.loads(values[index])
            result.append(values)
        return result

    def snapshot(self):
        result = {}
        for table in self.case['tables']:
            primary = next(c['name'] for c in table['columns'] if c['primary_key'])
            cursor = self.connection.execute('SELECT ' + ', '.join(quote(c['name']) for c in table['columns'])
                                             + ' FROM ' + quote(table['name']) + ' ORDER BY ' + quote(primary))
            result[table['name']] = {'columns': [c['name'] for c in table['columns']],
                                     'rows': self.normalize_rows(table['name'], [c['name'] for c in table['columns']], cursor.fetchall())}
            cursor.close()
        return result

    def close(self):
        if self.connection is not None:
            try:
                if self.created:
                    # Only the randomly generated schema owned by this adapter is removed.
                    self.connection.execute('ROLLBACK').close()
                    self.connection.execute('DROP SCHEMA ' + quote(self.namespace) + ' CASCADE').close()
                    self.created = False
            finally:
                self.connection.close()
                self.connection = None
