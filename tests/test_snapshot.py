from support import DatabaseCase, ROOT


class SnapshotTests(DatabaseCase):
    def test_update_after_snapshot_is_not_exported_and_ddl_is_blocked(self):
        with self.lab.connect('source') as other:
            def concurrent_change():
                other.execute("SET lock_timeout='80ms'")
                import psycopg
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    other.execute('ALTER TABLE sample.project ADD COLUMN forbidden text')
                other.execute('UPDATE sample.project SET organization_id=2 WHERE id=10')
                self.assertEqual(other.execute('SELECT organization_id FROM sample.project WHERE id=10').fetchone()[0], 2)
            path, _ = self.export(after_plan=concurrent_change)
        self.restore(path)
        self.target.execute((ROOT / 'tests/sql/assert_task.sql').read_text(encoding='utf-8'))
        self.assertEqual(self.target.execute('SELECT count(*) FROM restored.organization WHERE id=2').fetchone()[0], 0)

    def test_failed_callback_leaves_no_bundle_and_releases_locks(self):
        def fail():
            raise RuntimeError('synthetic observer failure')
        with self.assertRaisesRegex(RuntimeError, 'synthetic observer'):
            self.export(after_plan=fail)
        self.assertEqual(list(self.root.iterdir()), [])
        with self.lab.connect('source') as other:
            other.execute("SET lock_timeout='100ms'")
            other.execute('ALTER TABLE sample.project ADD COLUMN after_failure text')
