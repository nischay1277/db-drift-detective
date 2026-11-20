"""Create a separate database and non-superuser on the existing D-drive server."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import driftlab
import psycopg
from psycopg import sql


def main():
    private = ROOT / '.secrets'
    private.mkdir(parents=True, exist_ok=True)
    file = private / 'postgres.json'
    if not file.exists():
        file.write_text(json.dumps({'host': '127.0.0.1', 'port': 55432, 'dbname': 'driftlab',
            'user': 'driftlab', 'password': secrets.token_urlsafe(40)}, indent=2), encoding='utf-8')
    account = subprocess.check_output(['whoami'], text=True).strip()
    subprocess.run(['icacls', str(file), '/inheritance:r', '/grant:r', account + ':(F)'],
                   check=True, capture_output=True)
    settings = json.loads(file.read_text())
    admin_file = Path(r'D:\crashlab\.secrets\postgres-admin-password.txt')
    password = os.environ.get('DRIFTLAB_ADMIN_PASSWORD')
    if password is None:
        if not admin_file.exists():
            raise RuntimeError('Set DRIFTLAB_ADMIN_PASSWORD for a local PostgreSQL administrator, or configure DRIFTLAB_DATABASE_URL for an existing test database')
        password = admin_file.read_text().strip()
    with psycopg.connect(host=settings['host'], port=settings['port'], dbname='postgres',
                         user=os.environ.get('DRIFTLAB_ADMIN_USER', 'crashlab_admin'), password=password, autocommit=True) as db:
        if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', ('driftlab',)).fetchone():
            db.execute(sql.SQL('CREATE ROLE driftlab LOGIN PASSWORD {}').format(sql.Literal(settings['password'])))
        if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s', ('driftlab',)).fetchone():
            db.execute('CREATE DATABASE driftlab OWNER driftlab')
    with psycopg.connect(**settings) as db:
        row = db.execute('SELECT current_database(), current_user').fetchone()
        version = db.execute('SHOW server_version').fetchone()[0]
    print('Ready: database={}, role={}, PostgreSQL={}'.format(*row, version))


if __name__ == '__main__':
    main()
