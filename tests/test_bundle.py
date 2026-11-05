import os

from fixture_slice.bundle import import_bundle
from fixture_slice.demo import corrupt_reference, table_count
from support import DatabaseCase, ROOT


class BundleTests(DatabaseCase):
    def test_roundtrip_values_null_empty_and_fk_semantics(self):
        path, _ = self.export([{'table': 'task', 'pk': i} for i in (100, 103, 104)])
        self.restore(path)
        self.assertEqual(self.target.execute('SELECT id,project_id,title,done,effort FROM restored.task ORDER BY id').fetchall(),
                         [(100, 10, 'texto,"quoted"\nlinha — ação', False, -4), (103, None, '\\N', False, None), (104, None, None, True, 7)])
        self.assertEqual(self.target.execute('SELECT label FROM restored.project').fetchall(), [('',)])
        actual = self.target.execute("SELECT conname,confmatchtype,confupdtype,confdeltype,condeferrable,condeferred,convalidated "
                                     "FROM pg_constraint WHERE connamespace='restored'::regnamespace AND contype='f' ORDER BY conname").fetchall()
        self.assertEqual(actual, [('node_next_fk', 'f', 'a', 'a', True, True, True),
                                  ('project_organization_fk', 's', 'c', 'r', True, False, True),
                                  ('task_project_fk', 's', 'a', 'n', True, True, True)])
        self.assertEqual(self.target.execute("SELECT attname,attnotnull FROM pg_attribute WHERE attrelid='restored.task'::regclass AND attnum>0 ORDER BY attnum").fetchall(),
                         [('id', True), ('project_id', False), ('title', False), ('done', True), ('effort', False)])

    def test_copy_null_marker_is_independent_of_session_string_setting(self):
        self.source.execute("SET standard_conforming_strings='off'")
        self.target.execute("SET standard_conforming_strings='off'")
        try:
            path, _ = self.export([{'table': 'task', 'pk': 103}, {'table': 'task', 'pk': 104}])
            self.restore(path)
            self.assertEqual(self.target.execute('SELECT id,project_id,title,effort FROM restored.task ORDER BY id').fetchall(),
                             [(103, None, '\\N', None), (104, None, None, 7)])
            manifest = self.manifest(path)
            task = next(t for t in manifest['tables'] if t['name'] == 'task')
            data = (path / task['file']).read_bytes()
            self.assertIn(b'"\\N"', data)
            self.assertIn(b',\\N,', data)
            self.assertEqual(self.source.execute('SHOW standard_conforming_strings').fetchone()[0], 'off')
            self.assertEqual(self.target.execute('SHOW standard_conforming_strings').fetchone()[0], 'off')
        finally:
            self.source.execute("SET standard_conforming_strings='on'")
            self.target.execute("SET standard_conforming_strings='on'")

    def test_rehashed_corrupt_reference_rolls_back_then_original_succeeds(self):
        original, _ = self.export()
        changed = self.root / 'changed'
        corrupt_reference(original, changed)
        self.reject('FOREIGN_KEY', lambda: import_bundle(self.target, 'restored', changed))
        self.assertEqual(table_count(self.target), 0)
        self.assertIsNone(self.target.execute("SELECT to_regnamespace('restored')").fetchone()[0])
        self.target.execute('CREATE SCHEMA restored')
        self.reject('FOREIGN_KEY', lambda: import_bundle(self.target, 'restored', changed))
        self.assertEqual(table_count(self.target), 0)
        self.assertIsNotNone(self.target.execute("SELECT to_regnamespace('restored')").fetchone()[0])
        self.restore(original)
        self.target.execute((ROOT / 'tests/sql/assert_task.sql').read_text(encoding='utf-8'))

    def test_digest_and_row_count_are_verified(self):
        path, _ = self.export()
        manifest = self.manifest(path)
        entry = next(t for t in manifest['tables'] if t['name'] == 'task')
        data_path = path / entry['file']
        original = data_path.read_bytes()
        data_path.write_bytes(original.replace(b'-4', b'-3'))
        self.reject('DIGEST', lambda: import_bundle(self.target, 'restored', path))
        self.assertEqual(table_count(self.target), 0)
        data_path.write_bytes(original)
        entry['rows'] += 1
        manifest['total_rows'] += 1
        self.write_manifest(path, manifest)
        self.reject('ROW_COUNT', lambda: import_bundle(self.target, 'restored', path))
        self.assertEqual(table_count(self.target), 0)

    def test_symlink_and_extra_file_rejection(self):
        path, _ = self.export()
        entry = self.manifest(path)['tables'][0]
        item = path / entry['file']
        data = item.read_bytes()
        item.unlink()
        external = self.root / 'external'
        external.write_bytes(data)
        item.symlink_to(external)
        with self.assertRaises(OSError):
            import_bundle(self.target, 'restored', path)
        self.assertEqual(table_count(self.target), 0)
        item.unlink()
        item.write_bytes(data)
        (path / 'extra.sql').write_text('SELECT 1;', encoding='utf-8')
        self.reject('PATH', lambda: import_bundle(self.target, 'restored', path))

    def test_hardlinks_and_fifo_are_not_accepted_as_csv(self):
        path, _ = self.export()
        entry = self.manifest(path)['tables'][0]
        item = path / entry['file']
        data = item.read_bytes()
        external = self.root / 'hardlink'
        os.link(item, external)
        self.reject('PATH', lambda: import_bundle(self.target, 'restored', path))
        self.assertEqual(table_count(self.target), 0)
        external.unlink()
        item.unlink()
        os.mkfifo(item, 0o600)
        self.reject('PATH', lambda: import_bundle(self.target, 'restored', path))
        self.assertEqual(table_count(self.target), 0)
        item.unlink()
        item.write_bytes(data)
        self.restore(path)

    def test_nonempty_target_is_never_overwritten(self):
        path, _ = self.export()
        self.target.execute('CREATE SCHEMA restored; CREATE TABLE restored.sentinel(id integer); INSERT INTO restored.sentinel VALUES(42)')
        self.reject('TARGET_NOT_EMPTY', lambda: import_bundle(self.target, 'restored', path))
        self.assertEqual(self.target.execute('SELECT * FROM restored.sentinel').fetchall(), [(42,)])

    def test_nonrelation_schema_object_makes_target_nonempty(self):
        path, _ = self.export()
        self.target.execute('CREATE SCHEMA restored; CREATE COLLATION restored.sentinel FROM pg_catalog."C"')
        self.reject('TARGET_NOT_EMPTY', lambda: import_bundle(self.target, 'restored', path))
        self.assertEqual(table_count(self.target), 0)
        self.assertEqual(self.target.execute("SELECT collname FROM pg_catalog.pg_collation WHERE collnamespace='restored'::regnamespace").fetchall(), [('sentinel',)])
