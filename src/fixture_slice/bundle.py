"""COPY-only transport and transactional supported-DDL regeneration."""

import ctypes
import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from . import FixtureError
from .manifest import MAX_BYTES, MAX_MANIFEST, decode, encode, identifier, safe_path

TYPES = {k: sql.SQL('pg_catalog.' + v) for k, v in
         {'bigint': 'int8', 'integer': 'int4', 'text': 'text', 'boolean': 'bool'}.items()}
ACTIONS = {k: sql.SQL(v) for k, v in
           {'a': 'NO ACTION', 'r': 'RESTRICT', 'c': 'CASCADE', 'n': 'SET NULL', 'd': 'SET DEFAULT'}.items()}
COPY_OPTIONS = sql.SQL(" (FORMAT CSV, NULL '\\N', ENCODING 'UTF8')")


def database_error(exc):
    detail = exc.diag.message_primary or 'PostgreSQL operation failed'
    prefix = detail.split(':', 1)[0]
    known = {'ROW_CAP', 'REASON_CAP', 'INPUT', 'MISSING_SEED', 'MISSING_REFERENCE',
             'UNSUPPORTED_SCHEMA', 'SCHEMA_CHANGED', 'TRANSACTION'}
    code = prefix if prefix in known else ('FOREIGN_KEY' if exc.sqlstate == '23503' else 'DATABASE')
    return FixtureError(code, detail)


def ready(conn):
    try:
        if not conn.autocommit or conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            raise FixtureError('TRANSACTION', 'supply an idle autocommit connection')
        if conn.info.server_version // 10000 != 17:
            raise FixtureError('VERSION', 'PostgreSQL 17 is required')
        if conn.execute('SHOW server_encoding').fetchone()[0] != 'UTF8':
            raise FixtureError('VERSION', 'UTF8 database required')
        conn.execute("SET client_encoding = 'UTF8'")
    except psycopg.Error as exc:
        raise database_error(exc) from exc


def inputs(seeds, row_cap):
    # Validate before JSON serialization, staging or database work. In particular,
    # Python bool is not a PostgreSQL integer argument and must not become one.
    if type(row_cap) is not int or not 1 <= row_cap <= 10000:
        raise FixtureError('INPUT', 'row_cap must be an integer in 1..10000')
    if type(seeds) is not list or not 1 <= len(seeds) <= 256:
        raise FixtureError('INPUT', 'supply an array of 1..256 seeds')
    for seed in seeds:
        if type(seed) is not dict or set(seed) != {'table', 'pk'}:
            raise FixtureError('INPUT', 'seed requires exactly table and pk')
        try:
            identifier(seed['table'])
        except FixtureError as exc:
            raise FixtureError('INPUT', 'seed table must be a PostgreSQL identifier') from exc
        if type(seed['pk']) is not int or not -(2**63) <= seed['pk'] < 2**63:
            raise FixtureError('INPUT', 'seed pk must be a bigint integer')


def local_settings(conn):
    conn.execute("SET LOCAL statement_timeout = '5s'")
    conn.execute("SET LOCAL lock_timeout = '5s'")
    # The COPY NULL literal must not change with the caller's session settings.
    conn.execute("SET LOCAL standard_conforming_strings = 'on'")


def publish(stage, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise FixtureError('PLATFORM', 'Linux renameat2 required')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1) != 0:
        raise FixtureError('PUBLISH', os.strerror(ctypes.get_errno()))


def export_bundle(conn, schema, seeds, destination, row_cap=10000, *, after_plan=None):
    """Export one source snapshot. after_plan is an in-process observation hook."""
    identifier(schema)
    inputs(seeds, row_cap)
    ready(conn)
    destination = safe_path(destination)
    if destination.exists():
        raise FixtureError('PATH', 'destination already exists')
    stage = Path(tempfile.mkdtemp(prefix='.rf-stage-', dir=destination.parent))
    owned = stage.stat()
    try:
        # Discovery is outside REPEATABLE READ. Its result is bounded before
        # fetching, and fixture.plan independently revalidates the locked schema.
        tables = conn.execute('SELECT c.relname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n '
                              'ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind=\'r\' '
                              'ORDER BY c.oid LIMIT 33', (schema,)).fetchall()
        if len(tables) > 32:
            raise FixtureError('UNSUPPORTED_SCHEMA', 'table budget')
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            local_settings(conn)
            if tables:
                conn.execute(sql.SQL('LOCK TABLE {} IN SHARE UPDATE EXCLUSIVE MODE').format(
                    sql.SQL(', ').join(sql.SQL('ONLY {}').format(sql.Identifier(schema, t[0])) for t in tables)))
            conn.execute('SELECT fixture.plan(%s, %s, %s)', (schema, Jsonb(seeds), row_cap))
            if after_plan is not None:
                after_plan()
            entries = []
            total_bytes = 0
            for oid, name, pk, pk_name, count in conn.execute(
                    'SELECT t.table_oid,t.name,t.pk,t.pk_name,c.row_count FROM pg_temp.rf_tables t '
                    'JOIN pg_temp.rf_counts c USING(table_oid) ORDER BY t.name COLLATE "C"').fetchall():
                columns = [{'name': n, 'type': typ, 'not_null': nn} for n, typ, nn in conn.execute(
                    'SELECT name,type,not_null FROM pg_temp.rf_columns WHERE table_oid=%s ORDER BY ordinal', (oid,)).fetchall()]
                fks = [dict(zip(('name', 'column', 'target_table', 'target_column', 'match', 'on_update', 'on_delete', 'initially_deferred'), row))
                       for row in conn.execute('SELECT name,column_name,target_table,target_column,match_type,on_update,on_delete,initially_deferred '
                                               'FROM pg_temp.rf_fks WHERE table_oid=%s ORDER BY name COLLATE "C"', (oid,)).fetchall()]
                filename = f't{len(entries):03d}.csv'
                digest = hashlib.sha256()
                size = 0
                query = sql.SQL('COPY (SELECT {} FROM {} AS t JOIN pg_temp.rf_selected AS s '
                                'ON s.table_oid={} AND s.pk=t.{} ORDER BY t.{}) TO STDOUT').format(
                    sql.SQL(',').join(sql.Identifier('t', c['name']) for c in columns), sql.Identifier(schema, name),
                    sql.Literal(oid), sql.Identifier(pk), sql.Identifier(pk)) + COPY_OPTIONS
                with (stage / filename).open('xb') as out, conn.cursor() as cursor:
                    with cursor.copy(query) as copy:
                        for block in copy:
                            size += len(block)
                            total_bytes += len(block)
                            if total_bytes > MAX_BYTES:
                                raise FixtureError('BYTE_CAP', 'CSV payload exceeds 16 MiB')
                            digest.update(block)
                            out.write(block)
                    out.flush()
                    os.fsync(out.fileno())
                entries.append({'name': name, 'pk': pk, 'pk_name': pk_name, 'columns': columns,
                                'foreign_keys': fks, 'file': filename, 'rows': count,
                                'bytes': size, 'sha256': digest.hexdigest()})
            manifest = {'format': 'relational-fixture-slice', 'version': 1, 'encoding': 'UTF8',
                        'tables': entries, 'total_rows': sum(t['rows'] for t in entries), 'total_bytes': total_bytes}
            with (stage / 'manifest.json').open('xb') as out:
                out.write(encode(manifest))
                out.flush()
                os.fsync(out.fileno())
            reason_count = conn.execute('SELECT count(*) FROM pg_temp.rf_reasons').fetchone()[0]
        directory = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        publish(stage, destination)
        return {'rows': manifest['total_rows'], 'counts': {t['name']: t['rows'] for t in entries}, 'reasons': reason_count}
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    finally:
        if stage.exists() and not stage.is_symlink():
            now = stage.stat()
            if (now.st_dev, now.st_ino, now.st_uid) == (owned.st_dev, owned.st_ino, os.geteuid()):
                shutil.rmtree(stage)


def open_regular(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise FixtureError('PATH', 'bundle files must be singly-linked regular files')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


def import_bundle(conn, schema, bundle):
    """Regenerate finite DDL, stream verified bytes, and validate all FKs atomically."""
    identifier(schema)
    if schema == 'fixture' or schema == 'information_schema' or schema.startswith('pg_'):
        raise FixtureError('INPUT', 'reserved target schema')
    ready(conn)
    bundle = safe_path(bundle)
    directory = os.open(bundle, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with open_regular(directory, 'manifest.json') as source:
            manifest = decode(source.read(MAX_MANIFEST + 1))
        expected = {'manifest.json'} | {t['file'] for t in manifest['tables']}
        # At most 33 names are allowed. Do not materialize an unbounded directory.
        found = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name not in expected or entry.name in found:
                    raise FixtureError('PATH', 'unexpected bundle entry')
                found.add(entry.name)
        if found != expected:
            raise FixtureError('PATH', 'missing bundle entry')
        with conn.transaction():
            local_settings(conn)
            ns = conn.execute('SELECT oid FROM pg_catalog.pg_namespace WHERE nspname=%s', (schema,)).fetchone()
            if ns:
                occupied = conn.execute(
                    'SELECT EXISTS(SELECT FROM pg_catalog.pg_class WHERE relnamespace=%s) '
                    'OR EXISTS(SELECT FROM pg_catalog.pg_type WHERE typnamespace=%s) '
                    'OR EXISTS(SELECT FROM pg_catalog.pg_proc WHERE pronamespace=%s) '
                    'OR EXISTS(SELECT FROM pg_catalog.pg_depend '
                    'WHERE refclassid=\'pg_catalog.pg_namespace\'::regclass AND refobjid=%s)',
                    (ns[0], ns[0], ns[0], ns[0])).fetchone()[0]
                if occupied:
                    raise FixtureError('TARGET_NOT_EMPTY', 'target schema contains objects')
            else:
                conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            for t in manifest['tables']:
                cols = [sql.SQL('{} {}{}').format(sql.Identifier(c['name']), TYPES[c['type']],
                        sql.SQL(' NOT NULL' if c['not_null'] else '')) for c in t['columns']]
                cols.append(sql.SQL('CONSTRAINT {} PRIMARY KEY ({})').format(sql.Identifier(t['pk_name']), sql.Identifier(t['pk'])))
                conn.execute(sql.SQL('CREATE TABLE {} ({})').format(sql.Identifier(schema, t['name']), sql.SQL(',').join(cols)))
            for t in manifest['tables']:
                for fk in t['foreign_keys']:
                    conn.execute(sql.SQL('ALTER TABLE {} ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {} ({}) '
                                         'MATCH {} ON UPDATE {} ON DELETE {} DEFERRABLE INITIALLY {}').format(
                        sql.Identifier(schema, t['name']), sql.Identifier(fk['name']), sql.Identifier(fk['column']),
                        sql.Identifier(schema, fk['target_table']), sql.Identifier(fk['target_column']),
                        sql.SQL('SIMPLE' if fk['match'] == 's' else 'FULL'), ACTIONS[fk['on_update']], ACTIONS[fk['on_delete']],
                        sql.SQL('DEFERRED' if fk['initially_deferred'] else 'IMMEDIATE')))
            conn.execute('SET CONSTRAINTS ALL DEFERRED')
            for t in manifest['tables']:
                query = sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(schema, t['name']),
                    sql.SQL(',').join(sql.Identifier(c['name']) for c in t['columns'])) + COPY_OPTIONS
                digest = hashlib.sha256()
                size = 0
                with open_regular(directory, t['file']) as source, conn.cursor() as cursor:
                    with cursor.copy(query) as copy:
                        while True:
                            block = source.read(65536)
                            if not block:
                                break
                            size += len(block)
                            if size > t['bytes']:
                                raise FixtureError('DIGEST', 'file exceeds declared size')
                            digest.update(block)
                            copy.write(block)
                if size != t['bytes'] or digest.hexdigest() != t['sha256']:
                    raise FixtureError('DIGEST', 'CSV content does not match manifest')
                count = conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(schema, t['name']))).fetchone()[0]
                if count != t['rows']:
                    raise FixtureError('ROW_COUNT', 'CSV count does not match manifest')
            conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
        return {'rows': manifest['total_rows'], 'counts': {t['name']: t['rows'] for t in manifest['tables']}}
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    finally:
        os.close(directory)
