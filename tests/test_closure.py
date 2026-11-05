from psycopg import sql
from psycopg.types.json import Jsonb

from support import DatabaseCase, ROOT


class ClosureTests(DatabaseCase):
    def test_exact_forward_sets_and_reasons(self):
        scenarios = [
            ([{'table': 'task', 'pk': 100}], {('task', 100), ('project', 10), ('organization', 1)}),
            ([{'table': 'task', 'pk': 100}, {'table': 'task', 'pk': 101}], {('task', 100), ('task', 101), ('project', 10), ('organization', 1)}),
            ([{'table': 'project', 'pk': 10}], {('project', 10), ('organization', 1)}),
            ([{'table': 'task', 'pk': 103}], {('task', 103)}),
            ([{'table': 'node', 'pk': 7}], {('node', 7), ('node', 8)}),
        ]
        for seeds, expected in scenarios:
            with self.subTest(seeds=seeds), self.source.transaction():
                self.source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                self.source.execute('LOCK TABLE ONLY sample.organization, ONLY sample.project, ONLY sample.task, ONLY sample.node IN SHARE UPDATE EXCLUSIVE MODE')
                self.source.execute('SELECT fixture.plan(%s,%s,%s)', ('sample', Jsonb(seeds), 10000))
                actual = set(self.source.execute('SELECT t.name,s.pk FROM pg_temp.rf_selected s JOIN pg_temp.rf_tables t USING(table_oid)').fetchall())
                self.assertEqual(actual, expected)
                reasons = self.source.execute('SELECT kind,count(*) FROM pg_temp.rf_reasons GROUP BY kind').fetchall()
                self.assertGreaterEqual(dict(reasons)['seed'], 1)
                if len(seeds) == 2:
                    self.assertEqual(dict(reasons)['fk'], 3)
                if seeds[0]['table'] == 'node':
                    self.assertEqual(dict(reasons)['fk'], 2)
            self.assertIsNone(self.source.execute("SELECT to_regclass('pg_temp.rf_selected')").fetchone()[0])

    def test_cycle_restores_deferred_edges(self):
        path, report = self.export([{'table': 'node', 'pk': 7}])
        self.assertEqual(report['rows'], 2)
        self.restore(path)
        self.target.execute((ROOT / 'tests/sql/assert_cycle.sql').read_text(encoding='utf-8'))

    def test_duplicate_seeds_do_not_duplicate_rows_or_reasons(self):
        path, report = self.export([{'table': 'task', 'pk': 100}] * 2)
        self.assertEqual(report['rows'], 3)
        self.assertEqual(report['reasons'], 3)
        self.restore(path)
        self.target.execute((ROOT / 'tests/sql/assert_task.sql').read_text(encoding='utf-8'))
