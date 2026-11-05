"""Synthetic, offline acceptance demonstration with independent SQL checks."""

import csv
import hashlib
import json
from pathlib import Path
import shutil

from . import FixtureError
from .bundle import export_bundle, import_bundle
from .resources import read_sql


def check(condition, message):
    if not condition:
        raise FixtureError('DEMO_ASSERT', message)


def table_count(conn):
    return conn.execute("SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                        "ON n.oid=c.relnamespace WHERE n.nspname='restored' AND c.relkind='r'").fetchone()[0]


def clear_target(conn):
    conn.execute('DROP SCHEMA IF EXISTS restored CASCADE')


def restored_counts(conn):
    return dict(zip(('organization', 'project', 'task', 'node'), conn.execute(
        'SELECT (SELECT count(*) FROM restored.organization),(SELECT count(*) FROM restored.project),'
        '(SELECT count(*) FROM restored.task),(SELECT count(*) FROM restored.node)').fetchone()))


def no_orphans(conn):
    count = conn.execute('SELECT '
        '(SELECT count(*) FROM restored.task t LEFT JOIN restored.project p ON p.id=t.project_id WHERE t.project_id IS NOT NULL AND p.id IS NULL)+'
        '(SELECT count(*) FROM restored.project p LEFT JOIN restored.organization o ON o.id=p.organization_id WHERE o.id IS NULL)+'
        '(SELECT count(*) FROM restored.node n LEFT JOIN restored.node p ON p.id=n.next_id WHERE n.next_id IS NOT NULL AND p.id IS NULL)').fetchone()[0]
    check(count == 0, 'independent orphan query')


def verify_task(conn):
    check(restored_counts(conn) == {'organization': 1, 'project': 1, 'task': 1, 'node': 0},
          'exact three-row fixture')
    actual = conn.execute(
        'SELECT t.id,p.id,o.id,p.label,t.title,t.done,t.effort,o.label '
        'FROM restored.task t JOIN restored.project p ON p.id=t.project_id '
        'JOIN restored.organization o ON o.id=p.organization_id').fetchall()
    check(actual == [(100, 10, 1, '', 'texto,"quoted"\nlinha — ação', False, -4,
                      'Organização "A"\nline')], 'independent joined keys and payload values')


def verify_cycle(conn):
    check(conn.execute('SELECT id,next_id,label FROM restored.node ORDER BY id').fetchall()
          == [(7, 8, 'seven'), (8, 7, 'eight')], 'exact cycle rows')
    check(conn.execute("SELECT condeferrable,condeferred,convalidated,confmatchtype "
                       "FROM pg_catalog.pg_constraint WHERE conrelid='restored.node'::regclass "
                       "AND conname='node_next_fk'").fetchall() == [(True, True, True, 'f')],
          'validated deferred MATCH FULL cycle')


def corrupt_reference(original, changed):
    """Create a well-formed, rehashed but relationally invalid synthetic fixture."""
    shutil.copytree(original, changed)
    manifest = json.loads((changed / 'manifest.json').read_text(encoding='utf-8'))
    entry = next(t for t in manifest['tables'] if t['name'] == 'task')
    path = changed / entry['file']
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.reader(stream))
    rows[0][1] = '999'
    with path.open('w', encoding='utf-8', newline='') as stream:
        csv.writer(stream, lineterminator='\n').writerows(rows)
    data = path.read_bytes()
    manifest['total_bytes'] += len(data) - entry['bytes']
    entry['bytes'] = len(data)
    entry['sha256'] = hashlib.sha256(data).hexdigest()
    (changed / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')


def run(lab, directory, verify=True):
    source, target = lab.source, lab.target
    source.execute(read_sql('install.sql'))
    source.execute('DROP SCHEMA IF EXISTS sample CASCADE')
    source.execute(read_sql('demo_data.sql'))
    directory = Path(directory)
    cases = []
    definitions = [
        ('task-100', [{'table': 'task', 'pk': 100}], (1, 1, 1, 0)),
        ('shared-parent', [{'table': 'task', 'pk': 100}, {'table': 'task', 'pk': 101}], (1, 1, 2, 0)),
        ('project-only', [{'table': 'project', 'pk': 10}], (1, 1, 0, 0)),
        ('null-reference', [{'table': 'task', 'pk': 103}], (0, 0, 1, 0)),
        ('cycle', [{'table': 'node', 'pk': 7}], (0, 0, 0, 2)),
    ]
    original = directory / 'task-100'
    for name, seeds, expected in definitions:
        path = directory / name
        export_bundle(source, 'sample', seeds, path)
        clear_target(target)
        import_bundle(target, 'restored', path)
        counts = restored_counts(target)
        check(tuple(counts.values()) == expected, name + ' exact counts')
        no_orphans(target)
        if name == 'task-100':
            verify_task(target)
        if name == 'cycle':
            verify_cycle(target)
        if name == 'null-reference':
            check(target.execute('SELECT project_id IS NULL AND title=%s FROM restored.task WHERE id=103', ('\\N',)).fetchone() == (True,), 'null unchanged')
        cases.append({'case': name, 'rows': sum(expected), 'counts': counts})
    clear_target(target)
    failures = []
    for name, schema, cap, expected_code in [('row-cap', 'sample', 2, 'ROW_CAP'),
                                            ('composite', 'bad', 10000, 'UNSUPPORTED_SCHEMA')]:
        if schema == 'bad':
            source.execute('DROP SCHEMA IF EXISTS bad CASCADE; CREATE SCHEMA bad; '
                           'CREATE TABLE bad.task(id bigint,part bigint,PRIMARY KEY(id,part)); '
                           'INSERT INTO bad.task VALUES(100,1)')
        try:
            export_bundle(source, schema, [{'table': 'task', 'pk': 100}], directory / name, cap)
            raise FixtureError('DEMO_ASSERT', 'expected export rejection')
        except FixtureError as exc:
            check(exc.code == expected_code, 'export rejection category')
        check(not (directory / name).exists() and table_count(target) == 0, 'no publication or target table')
        failures.append({'case': name, 'code': expected_code, 'published': 0, 'target_tables': 0})
    snapshot = directory / 'snapshot'
    with lab.connect('source') as updater:
        def update():
            updater.execute('UPDATE sample.project SET organization_id=2 WHERE id=10')
        export_bundle(source, 'sample', [{'table': 'task', 'pk': 100}], snapshot, after_plan=update)
    import_bundle(target, 'restored', snapshot)
    verify_task(target)
    no_orphans(target)
    organization_2 = target.execute('SELECT count(*) FROM restored.organization WHERE id=2').fetchone()[0]
    check(organization_2 == 0, 'snapshot excludes organization 2')
    cases.append({'case': 'snapshot', 'rows': 3, 'counts': restored_counts(target), 'organization_2_rows': organization_2})
    clear_target(target)
    corrupt_reference(original, directory / 'corrupt')
    try:
        import_bundle(target, 'restored', directory / 'corrupt')
        raise FixtureError('DEMO_ASSERT', 'corrupt reference accepted')
    except FixtureError as exc:
        check(exc.code == 'FOREIGN_KEY', 'constraint rejection, not digest rejection')
    check(table_count(target) == 0, 'failed import rolled back DDL')
    import_bundle(target, 'restored', original)
    verify_task(target)
    failures.append({'case': 'corrupt-reference', 'code': 'FOREIGN_KEY', 'target_tables_after_failure': 0, 'retry_rows': 3})
    if verify:
        check(len(cases) == 6 and len(failures) == 3, 'all acceptance cases completed')
    return {'development_version': '0.1.0', 'cases': cases, 'rejections': failures, 'status': 'ok'}
