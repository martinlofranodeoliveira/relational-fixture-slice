import psycopg
from psycopg.types.json import Jsonb

from fixture_slice.bundle import export_bundle, publish
from fixture_slice.demo import table_count
from support import DatabaseCase


class LimitTests(DatabaseCase):
    def test_row_cap_missing_seed_and_invalid_input(self):
        self.reject('ROW_CAP', lambda: self.export(cap=2))
        self.assertEqual(table_count(self.target), 0)
        self.assertEqual(list(self.root.iterdir()), [])
        for seeds in ([{'table': 'task', 'pk': 999}], [{'table': 'task', 'pk': 100}, {'table': 'task', 'pk': 999}]):
            self.reject('MISSING_SEED', lambda: self.export(seeds))
        bad_seeds = [
            [], None, {}, [None], [{'table': 'task', 'pk': True}],
            [{'table': 'task', 'pk': '100'}], [{'table': 'task', 'pk': 100.0}],
            [{'table': 'task', 'pk': float('nan')}], [{'table': 'task', 'pk': 2**63}],
            [{'table': 'task', 'pk': -(2**63)-1}],
            [{'table': 'task', 'pk': 100, 'sql': 'x'}],
            [{'table': 'x'*64, 'pk': 1}], [{'table': '\ud800', 'pk': 1}],
            [{'table': 'task', 'pk': 100}] * 257,
        ]
        for seeds in bad_seeds:
            with self.subTest(seeds=repr(seeds)[:100]):
                self.reject('INPUT', lambda: export_bundle(self.source, 'sample', seeds, self.root / 'invalid'))
        for cap in (0, 10001, True, 2.0, None, '2'):
            with self.subTest(cap=cap):
                self.reject('INPUT', lambda: export_bundle(self.source, 'sample', [{'table': 'task', 'pk': 100}], self.root / 'invalid', cap))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_statement_atomicity_leaves_no_partial_plan(self):
        with self.source.transaction():
            self.source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            self.source.execute('LOCK TABLE ONLY sample.organization, ONLY sample.project, ONLY sample.task, ONLY sample.node IN SHARE UPDATE EXCLUSIVE MODE')
            with self.assertRaises(psycopg.errors.RaiseException), self.source.transaction():
                self.source.execute('SELECT fixture.plan(%s,%s,2)', ('sample', Jsonb([{'table': 'task', 'pk': 100}])))
            self.assertIsNone(self.source.execute("SELECT to_regclass('pg_temp.rf_selected')").fetchone()[0])

    def test_failed_replan_restores_the_previous_plan_at_savepoint(self):
        with self.source.transaction():
            self.source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            self.source.execute('LOCK TABLE ONLY sample.organization, ONLY sample.project, ONLY sample.task, ONLY sample.node IN SHARE UPDATE EXCLUSIVE MODE')
            self.source.execute('SELECT fixture.plan(%s,%s,10)', ('sample', Jsonb([{'table': 'task', 'pk': 103}])))
            with self.assertRaisesRegex(psycopg.errors.RaiseException, 'ROW_CAP'), self.source.transaction():
                self.source.execute('SELECT fixture.plan(%s,%s,2)', ('sample', Jsonb([{'table': 'task', 'pk': 100}])))
            actual = self.source.execute('SELECT t.name,s.pk FROM pg_temp.rf_selected s JOIN pg_temp.rf_tables t USING(table_oid)').fetchall()
            self.assertEqual(actual, [('task', 103)])
            self.assertEqual(self.source.execute('SELECT kind,count(*) FROM pg_temp.rf_reasons GROUP BY kind').fetchall(), [('seed', 1)])

    def test_missing_reference_rejects_without_publication(self):
        self.source.execute('ALTER TABLE sample.task DISABLE TRIGGER ALL')
        self.source.execute('UPDATE sample.task SET project_id=999 WHERE id=100')
        self.reject('MISSING_REFERENCE', lambda: self.export())
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(table_count(self.target), 0)

    def test_byte_cap_and_owned_staging_cleanup(self):
        unrelated = self.root / '.rf-stage-unrelated'
        unrelated.mkdir()
        (unrelated / 'sentinel').write_text('not owned', encoding='utf-8')
        self.source.execute("UPDATE sample.task SET title=repeat('x',17*1024*1024) WHERE id=100")
        self.reject('BYTE_CAP', lambda: self.export())
        self.assertEqual(list(self.root.iterdir()), [unrelated])
        self.assertEqual((unrelated / 'sentinel').read_text(), 'not owned')

    def test_atomic_publish_refuses_existing_empty_directory(self):
        stage = self.root / 'stage'
        destination = self.root / 'destination'
        stage.mkdir()
        destination.mkdir()
        self.reject('PUBLISH', lambda: publish(stage, destination))
        self.assertTrue(stage.is_dir())
        self.assertTrue(destination.is_dir())

    def test_plan_requires_isolation_and_prelocks(self):
        with self.assertRaisesRegex(psycopg.errors.RaiseException, 'TRANSACTION'):
            self.source.execute('SELECT fixture.plan(%s,%s,10)', ('sample', Jsonb([{'table': 'task', 'pk': 100}])))
        with self.assertRaisesRegex(psycopg.errors.RaiseException, 'SCHEMA_CHANGED'), self.source.transaction():
            self.source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            self.source.execute('SELECT fixture.plan(%s,%s,10)', ('sample', Jsonb([{'table': 'task', 'pk': 100}])))
