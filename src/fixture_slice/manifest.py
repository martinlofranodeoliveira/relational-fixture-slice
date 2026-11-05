"""Finite, typed bundle format; no SQL or caller-selected filenames."""

import json
import re
from pathlib import Path

from . import FixtureError

MAX_BYTES = 16 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
TYPES = {'bigint', 'integer', 'text', 'boolean'}
ACTIONS = {'a', 'r', 'c', 'n', 'd'}


def require(ok, message):
    if not ok:
        raise FixtureError('MANIFEST', message)


def exact(obj, keys):
    require(type(obj) is dict and set(obj) == set(keys.split()), 'object fields')


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, 'integer bound')


def identifier(value):
    require(type(value) is str and bool(value) and '\x00' not in value, 'identifier')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError as exc:
        raise FixtureError('MANIFEST', 'invalid Unicode identifier') from exc
    require(size <= 63, 'identifier exceeds PostgreSQL byte limit')


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def decode(data):
    require(len(data) <= MAX_MANIFEST, 'manifest byte limit')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=unique,
                           parse_constant=lambda _: require(False, 'nonfinite JSON'))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise FixtureError('MANIFEST', 'invalid JSON') from exc
    return validate(value)


def encode(value):
    validate(value)
    result = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    require(len(result) <= MAX_MANIFEST, 'manifest byte limit')
    return result


def validate(value):
    exact(value, 'format version encoding tables total_rows total_bytes')
    require(value['format'] == 'relational-fixture-slice' and type(value['version']) is int
            and value['version'] == 1 and value['encoding'] == 'UTF8', 'format/version/encoding')
    tables = value['tables']
    require(type(tables) is list and 1 <= len(tables) <= 32, 'table budget')
    names = []
    columns_total = 0
    fks_total = 0
    rows = 0
    size = 0
    by_name = {}
    for i, t in enumerate(tables):
        exact(t, 'name pk pk_name columns foreign_keys file rows bytes sha256')
        for k in ('name', 'pk', 'pk_name'):
            identifier(t[k])
        names.append(t['name'])
        by_name[t['name']] = t
        require(t['file'] == f't{i:03d}.csv', 'noncanonical filename')
        integer(t['rows'], 0, 10000)
        integer(t['bytes'], 0, MAX_BYTES)
        require(type(t['sha256']) is str and re.fullmatch('[0-9a-f]{64}', t['sha256']) is not None, 'SHA-256 syntax')
        rows += t['rows']
        size += t['bytes']
        cols = t['columns']
        require(type(cols) is list and 1 <= len(cols) <= 64, 'column budget')
        column_names = []
        for col in cols:
            exact(col, 'name type not_null')
            identifier(col['name'])
            require(type(col['type']) is str and col['type'] in TYPES and type(col['not_null']) is bool, 'column type/nullability')
            column_names.append(col['name'])
        require(len(set(column_names)) == len(column_names), 'duplicate column')
        pk = [c for c in cols if c['name'] == t['pk']]
        require(len(pk) == 1 and pk[0]['type'] == 'bigint' and pk[0]['not_null'], 'primary key')
        columns_total += len(cols)
        fks = t['foreign_keys']
        require(type(fks) is list and len(fks) <= 128, 'foreign key budget')
        constraints = {t['pk_name']}
        for fk in fks:
            exact(fk, 'name column target_table target_column match on_update on_delete initially_deferred')
            for k in ('name', 'column', 'target_table', 'target_column'):
                identifier(fk[k])
            require(fk['name'] not in constraints, 'duplicate constraint')
            constraints.add(fk['name'])
            require(type(fk['match']) is str and fk['match'] in {'s', 'f'}, 'match semantics')
            require(type(fk['on_update']) is str and fk['on_update'] in ACTIONS
                    and type(fk['on_delete']) is str and fk['on_delete'] in ACTIONS, 'FK actions')
            require(type(fk['initially_deferred']) is bool, 'deferral')
            require(any(c['name'] == fk['column'] and c['type'] == 'bigint' for c in cols), 'FK source column')
        fks_total += len(fks)
    require(names == sorted(set(names)), 'unique, sorted tables')
    require(columns_total <= 512 and fks_total <= 128, 'aggregate metadata budget')
    for t in tables:
        for fk in t['foreign_keys']:
            target = by_name.get(fk['target_table'])
            require(target is not None and target['pk'] == fk['target_column'], 'FK target primary key')
    integer(value['total_rows'], 0, 10000)
    integer(value['total_bytes'], 0, MAX_BYTES)
    require(value['total_rows'] == rows and value['total_bytes'] == size, 'aggregate totals')
    return value


def safe_path(path):
    """Reject symlink ancestors and lexical parent traversal; require an existing parent."""
    raw = Path(path)
    if '..' in raw.parts:
        raise FixtureError('PATH', 'parent traversal')
    absolute = raw.absolute()
    for part in reversed(absolute.parents):
        if part.is_symlink() or not part.is_dir():
            raise FixtureError('PATH', 'non-directory or symlink ancestor')
    if absolute.is_symlink():
        raise FixtureError('PATH', 'symlink')
    return absolute
