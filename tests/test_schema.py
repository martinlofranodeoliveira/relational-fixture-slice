from psycopg import sql

from fixture_slice.bundle import export_bundle, import_bundle
from support import DatabaseCase, ROOT


class SchemaTests(DatabaseCase):
    def test_composite_rejected_before_any_csv_publication(self):
        self.source.execute((ROOT / 'tests/sql/unsupported.sql').read_text(encoding='utf-8'))
        path = self.root / 'unsupported'
        self.reject('UNSUPPORTED_SCHEMA', lambda: export_bundle(self.source, 'bad', [{'table': 'task', 'pk': 100}], path))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unsupported_constructs(self):
        alterations = {
            'default': 'ALTER TABLE sample.task ALTER COLUMN effort SET DEFAULT 1',
            'check': 'ALTER TABLE sample.task ADD CHECK (effort >= -4)',
            'unique': 'ALTER TABLE sample.task ADD UNIQUE(title)',
            'index': 'CREATE INDEX task_title_idx ON sample.task(title)',
            'rls': 'ALTER TABLE sample.task ENABLE ROW LEVEL SECURITY',
            'identity': 'ALTER TABLE sample.task ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY',
            'generated': 'ALTER TABLE sample.task ADD COLUMN derived bigint GENERATED ALWAYS AS (id+1) STORED',
            'domain': 'CREATE DOMAIN sample.amount AS bigint; ALTER TABLE sample.task ADD COLUMN amount sample.amount',
            'array': 'ALTER TABLE sample.task ADD COLUMN values_list bigint[]',
            'external-fk': 'CREATE SCHEMA bad; CREATE TABLE bad.parent(id bigint PRIMARY KEY); ALTER TABLE sample.task ADD COLUMN outside_id bigint REFERENCES bad.parent(id) DEFERRABLE',
            'not-deferrable': 'ALTER TABLE sample.task ALTER CONSTRAINT task_project_fk NOT DEFERRABLE',
            'not-valid': 'ALTER TABLE sample.task DROP CONSTRAINT task_project_fk; ALTER TABLE sample.task ADD FOREIGN KEY(project_id) REFERENCES sample.project(id) DEFERRABLE NOT VALID',
            'partition': 'CREATE TABLE sample.parts(id bigint PRIMARY KEY) PARTITION BY RANGE(id)',
            'user-trigger': "CREATE FUNCTION sample.noop() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NEW; END$$; CREATE TRIGGER custom BEFORE INSERT ON sample.task FOR EACH ROW EXECUTE FUNCTION sample.noop()",
        }
        for label, statement in alterations.items():
            with self.subTest(label=label):
                self.reset()
                self.source.execute(statement)
                self.reject('UNSUPPORTED_SCHEMA', lambda: self.export())
                self.assertEqual(list(self.root.iterdir()), [])

    def test_internal_fk_triggers_are_allowed(self):
        count = self.source.execute('SELECT count(*) FROM pg_trigger WHERE tgrelid=\'sample.task\'::regclass AND tgisinternal').fetchone()[0]
        self.assertGreater(count, 0)
        self.export()

    def test_identifiers_are_catalog_quoted(self):
        table = 'select;--'
        column = 'a"b'
        parent = 'parent "quoted"'
        fk = 'fk; "quoted"'
        self.source.execute('CREATE SCHEMA odd')
        self.source.execute(sql.SQL('CREATE TABLE {} ({} bigint CONSTRAINT {} PRIMARY KEY, {} text NOT NULL)').format(
            sql.Identifier('odd', parent), sql.Identifier('parent id'), sql.Identifier('parent pk'), sql.Identifier(column)))
        self.source.execute(sql.SQL('CREATE TABLE {} ({} bigint CONSTRAINT {} PRIMARY KEY, {} bigint, '
                                    'CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {} ({}) DEFERRABLE)').format(
            sql.Identifier('odd', table), sql.Identifier('big id'), sql.Identifier('pk quote'),
            sql.Identifier('parent ref'), sql.Identifier(fk), sql.Identifier('parent ref'),
            sql.Identifier('odd', parent), sql.Identifier('parent id')))
        self.source.execute(sql.SQL('INSERT INTO {} VALUES (-9,%s)').format(sql.Identifier('odd', parent)), ('ação\n"x"',))
        self.source.execute(sql.SQL('INSERT INTO {} VALUES (1,-9)').format(sql.Identifier('odd', table)))
        path = self.root / 'quoted'
        report = export_bundle(self.source, 'odd', [{'table': table, 'pk': 1}], path)
        self.assertEqual(report['rows'], 2)
        import_bundle(self.target, 'restored', path)
        self.assertEqual(self.target.execute(sql.SQL('SELECT {},{} FROM {}').format(
            sql.Identifier('parent id'), sql.Identifier(column), sql.Identifier('restored', parent))).fetchall(), [(-9, 'ação\n"x"')])
        self.assertEqual(self.target.execute(sql.SQL('SELECT {},{} FROM {}').format(
            sql.Identifier('big id'), sql.Identifier('parent ref'), sql.Identifier('restored', table))).fetchall(), [(1, -9)])
        self.assertEqual(self.target.execute("SELECT conname FROM pg_catalog.pg_constraint WHERE connamespace='restored'::regnamespace AND contype='f'").fetchall(), [(fk,)])
